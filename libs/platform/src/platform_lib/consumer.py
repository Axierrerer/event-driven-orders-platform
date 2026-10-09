"""Идемпотентный consumer Kafka.

Порядок обработки сообщения:
1. Десериализация. Ошибка → сразу в DLQ (повтор не поможет).
2. В одной транзакции БД: отметка event_id в processed_events и вызов обработчика.
   Если event_id уже обработан — сообщение пропускается.
3. Ошибка обработчика → откат транзакции (вместе с отметкой) и повтор с задержкой;
   после исчерпания попыток — в DLQ.
4. Offset коммитится только после шагов 1–3 (успех, дубль или DLQ).
"""

import asyncio
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

from confluent_kafka import Consumer, Producer
from confluent_kafka.schema_registry import SchemaRegistryClient
from confluent_kafka.serialization import MessageField, SerializationContext
from opentelemetry.trace import SpanKind
from sqlalchemy import Table, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from events import EVENTS_BY_TOPIC, BaseEvent, dlq_topic, make_deserializer
from platform_lib.logging import get_logger
from platform_lib.metrics import CONSUMER_LAG, DLQ_MESSAGES, EVENTS_PROCESSED
from platform_lib.telemetry import context_from_headers, tracer

log = get_logger(__name__)


class KafkaMessage(Protocol):
    """Подмножество confluent_kafka.Message, которое использует consumer."""

    def topic(self) -> str | None: ...
    def key(self) -> bytes | None: ...
    def value(self) -> bytes | None: ...
    def headers(self) -> Any: ...
    def partition(self) -> int | None: ...
    def offset(self) -> int | None: ...


EventDecoder = Callable[[KafkaMessage], BaseEvent]
Handler = Callable[[Any, Any], Awaitable[None]]


class InboxStore(Protocol):
    """Хранилище обработанных событий + транзакция, в которой работает обработчик."""

    def transaction(self) -> AbstractAsyncContextManager[Any]: ...

    async def mark_processed(self, tx: Any, event_id: UUID, consumer_group: str) -> bool:
        """True — событие отмечено впервые; False — уже обрабатывалось."""
        ...


class DeadLetterSink(Protocol):
    async def send(self, message: KafkaMessage, error: str) -> None: ...


@dataclass(frozen=True)
class RetryPolicy:
    delays_seconds: Sequence[float] = (0.5, 2.0, 8.0)


class IdempotentConsumer:
    def __init__(
        self,
        *,
        group_id: str,
        inbox: InboxStore,
        decoder: EventDecoder,
        dead_letters: DeadLetterSink,
        retry: RetryPolicy | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.group_id = group_id
        self._inbox = inbox
        self._decode = decoder
        self._dead_letters = dead_letters
        self._retry = retry or RetryPolicy()
        self._sleep = sleep
        self._handlers: dict[str, Handler] = {}

    def handler(self, topic: str) -> Callable[[Handler], Handler]:
        """Регистрирует обработчик: `async def handle(event, tx) -> None`."""
        if topic not in EVENTS_BY_TOPIC:
            raise ValueError(f"Неизвестный топик: {topic}")

        def register(func: Handler) -> Handler:
            self._handlers[topic] = func
            return func

        return register

    @property
    def topics(self) -> list[str]:
        return list(self._handlers)

    async def process(self, message: KafkaMessage) -> None:
        """Обработать сообщение. После возврата offset можно коммитить.

        Span обработки — дочерний к span’у бизнес-операции producer’а (traceparent
        из заголовков сообщения), поэтому весь путь заказа виден одним трейсом.
        """
        topic = message.topic() or ""
        with tracer().start_as_current_span(
            f"consume {topic}",
            context=context_from_headers(message.headers()),
            kind=SpanKind.CONSUMER,
            attributes={"messaging.system": "kafka", "messaging.destination.name": topic},
        ) as span:
            result = await self._process(message, topic)
            span.set_attribute("orders.consumer.result", result)
            EVENTS_PROCESSED.labels(topic, result).inc()

    async def _process(self, message: KafkaMessage, topic: str) -> str:
        handler = self._handlers.get(topic)
        if handler is None:
            await self._dead_letters.send(message, f"нет обработчика для топика {topic}")
            return "no_handler"

        try:
            event = self._decode(message)
        except Exception as exc:
            log.warning("event_decode_failed", topic=topic, error=str(exc))
            await self._dead_letters.send(message, f"decode: {type(exc).__name__}: {exc}")
            return "decode_error"

        context = {"topic": topic, "event_id": str(event.event_id), "group": self.group_id}
        last_error: Exception | None = None
        for delay in (0.0, *self._retry.delays_seconds):
            if delay:
                await self._sleep(delay)
            try:
                async with self._inbox.transaction() as tx:
                    if not await self._inbox.mark_processed(tx, event.event_id, self.group_id):
                        log.info("event_duplicate_skipped", **context)
                        return "duplicate"
                    await handler(event, tx)
                log.info("event_processed", **context)
                return "processed"
            except Exception as exc:
                last_error = exc
                log.warning("event_handler_failed", error=repr(exc), **context)

        await self._dead_letters.send(message, f"handler: {last_error!r}")
        log.error("event_sent_to_dlq", **context)
        return "dead_letter"


# ---------------- хранилища processed_events ----------------


class PgInbox:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession], table: Table) -> None:
        self._session_factory = session_factory
        self._table = table

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[AsyncSession]:
        async with self._session_factory() as session, session.begin():
            yield session

    async def mark_processed(self, tx: AsyncSession, event_id: UUID, consumer_group: str) -> bool:
        stmt = (
            pg_insert(self._table)
            .values(event_id=event_id, consumer_group=consumer_group)
            .on_conflict_do_nothing()
            .returning(self._table.c.event_id)
        )
        return (await tx.execute(stmt)).first() is not None

    async def is_processed(self, event_id: UUID, consumer_group: str) -> bool:
        t = self._table
        async with self._session_factory() as session:
            found = await session.scalar(
                select(t.c.event_id).where(
                    t.c.event_id == event_id, t.c.consumer_group == consumer_group
                )
            )
        return found is not None


class MongoInbox:
    """processed_events в MongoDB; обработчик получает сессию с открытой транзакцией."""

    def __init__(self, client: Any, collection: Any) -> None:
        self._client = client
        self._collection = collection

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[Any]:
        async with await self._client.start_session() as session:
            async with session.start_transaction():
                yield session

    async def mark_processed(self, tx: Any, event_id: UUID, consumer_group: str) -> bool:
        doc_id = f"{consumer_group}:{event_id}"
        if await self._collection.find_one({"_id": doc_id}, session=tx) is not None:
            return False
        # Конкурентный дубль упадёт на уникальном _id → транзакция откатится и при
        # повторе find_one увидит отметку.
        await self._collection.insert_one(
            {
                "_id": doc_id,
                "event_id": str(event_id),
                "consumer_group": consumer_group,
                "processed_at": datetime.now(UTC),
            },
            session=tx,
        )
        return True


# ---------------- Kafka: декодер, DLQ, цикл чтения ----------------


def schema_registry_decoder(registry: SchemaRegistryClient) -> EventDecoder:
    deserializers = {
        topic: make_deserializer(cls, registry) for topic, cls in EVENTS_BY_TOPIC.items()
    }

    def decode(message: KafkaMessage) -> BaseEvent:
        topic = message.topic() or ""
        event = deserializers[topic](
            message.value(), SerializationContext(topic, MessageField.VALUE)
        )
        if not isinstance(event, BaseEvent):
            raise TypeError(f"Пустое сообщение в {topic}")
        return event

    return decode


class KafkaDeadLetterSink:
    def __init__(self, producer: Producer, *, flush_timeout_seconds: float = 10.0) -> None:
        self._producer = producer
        self._flush_timeout = flush_timeout_seconds

    async def send(self, message: KafkaMessage, error: str) -> None:
        await asyncio.to_thread(self._send_sync, message, error)

    def _send_sync(self, message: KafkaMessage, error: str) -> None:
        topic = message.topic() or "unknown"
        original = message.headers() or []
        if isinstance(original, dict):
            original = list(original.items())
        headers: list[tuple[str, str | bytes | None]] = [
            *original,
            ("dlq.error", error[:2000].encode()),
            ("dlq.original_topic", topic.encode()),
            ("dlq.original_partition", str(message.partition()).encode()),
            ("dlq.original_offset", str(message.offset()).encode()),
        ]
        self._producer.produce(
            dlq_topic(topic), key=message.key(), value=message.value(), headers=headers
        )
        remaining = self._producer.flush(self._flush_timeout)
        if remaining:
            raise RuntimeError(f"DLQ-сообщение для {topic} не доставлено")
        DLQ_MESSAGES.labels(topic).inc()


class KafkaConsumerRunner:
    """Цикл чтения: poll → process → commit offset. Блокирующий poll — в отдельном потоке."""

    def __init__(
        self,
        consumer: IdempotentConsumer,
        kafka_consumer: Consumer,
        *,
        poll_timeout_seconds: float = 1.0,
        lag_interval_seconds: float = 15.0,
    ) -> None:
        self._consumer = consumer
        self._kafka = kafka_consumer
        self._poll_timeout = poll_timeout_seconds
        self._lag_interval = lag_interval_seconds
        self._lag_reported_at = 0.0

    async def _report_lag(self) -> None:
        now = time.monotonic()
        if now - self._lag_reported_at < self._lag_interval:
            return
        self._lag_reported_at = now
        try:
            lags = await asyncio.to_thread(_partition_lag, self._kafka)
        except Exception as exc:
            log.warning("consumer_lag_unavailable", error=str(exc))
            return
        for topic, partition, lag in lags:
            CONSUMER_LAG.labels(topic, str(partition)).set(lag)

    async def run(self, stop: asyncio.Event) -> None:
        self._kafka.subscribe(self._consumer.topics)
        log.info("consumer_started", group=self._consumer.group_id, topics=self._consumer.topics)
        try:
            while not stop.is_set():
                await self._report_lag()
                message = await asyncio.to_thread(self._kafka.poll, self._poll_timeout)
                if message is None:
                    continue
                if message.error():
                    log.warning("kafka_poll_error", error=str(message.error()))
                    continue
                await self._consumer.process(message)
                await asyncio.to_thread(self._kafka.commit, message=message, asynchronous=False)
        finally:
            await asyncio.to_thread(self._kafka.close)
            log.info("consumer_stopped", group=self._consumer.group_id)


def _partition_lag(kafka: Consumer) -> list[tuple[str, int, int]]:
    """(topic, partition, lag) для назначенных consumer’у партиций."""
    result = []
    for tp in kafka.assignment():
        low, high = kafka.get_watermark_offsets(tp, timeout=1.0, cached=False)
        [position] = kafka.position([tp])
        offset = position.offset if position.offset >= 0 else low
        result.append((tp.topic, tp.partition, max(high - offset, 0)))
    return result


__all__ = [
    "DeadLetterSink",
    "EventDecoder",
    "IdempotentConsumer",
    "InboxStore",
    "KafkaConsumerRunner",
    "KafkaDeadLetterSink",
    "KafkaMessage",
    "MongoInbox",
    "PgInbox",
    "RetryPolicy",
    "schema_registry_decoder",
]
