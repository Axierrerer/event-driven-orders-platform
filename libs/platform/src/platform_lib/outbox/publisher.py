import asyncio
from collections.abc import Sequence
from typing import Any, Protocol

from confluent_kafka import KafkaError, Message, Producer
from confluent_kafka.schema_registry import SchemaRegistryClient
from confluent_kafka.schema_registry.json_schema import JSONSerializer
from confluent_kafka.serialization import MessageField, SerializationContext

from events import EVENTS_BY_TOPIC, make_serializer
from platform_lib.outbox.records import OutboxRecord


class EventPublisher(Protocol):
    async def publish(self, records: Sequence[OutboxRecord]) -> list[str | None]:
        """Опубликовать записи. Для каждой: None — доставлено, иначе текст ошибки."""
        ...


class KafkaEventPublisher:
    """Публикует записи outbox в Kafka, сериализуя через Schema Registry."""

    def __init__(
        self,
        producer: Producer,
        registry: SchemaRegistryClient,
        *,
        flush_timeout_seconds: float = 10.0,
        auto_register_schemas: bool = False,
    ) -> None:
        self._producer = producer
        self._registry = registry
        self._flush_timeout = flush_timeout_seconds
        self._auto_register = auto_register_schemas
        self._serializers: dict[str, JSONSerializer] = {}

    async def publish(self, records: Sequence[OutboxRecord]) -> list[str | None]:
        return await asyncio.to_thread(self._publish_sync, records)

    def _serializer(self, topic: str) -> JSONSerializer:
        if topic not in self._serializers:
            self._serializers[topic] = make_serializer(
                EVENTS_BY_TOPIC[topic], self._registry, auto_register=self._auto_register
            )
        return self._serializers[topic]

    def _publish_sync(self, records: Sequence[OutboxRecord]) -> list[str | None]:
        results: list[str | None] = ["не подтверждено брокером до таймаута"] * len(records)

        for index, record in enumerate(records):
            try:
                event = EVENTS_BY_TOPIC[record.topic].model_validate(record.payload)
                ctx = SerializationContext(record.topic, MessageField.VALUE)
                value = self._serializer(record.topic)(event, ctx)
                self._producer.produce(
                    record.topic,
                    key=record.key.encode(),
                    value=value,
                    headers=list(record.headers.items()),
                    on_delivery=self._on_delivery(results, index),
                )
            except Exception as exc:
                results[index] = f"{type(exc).__name__}: {exc}"
            self._producer.poll(0)

        self._producer.flush(self._flush_timeout)
        return results

    @staticmethod
    def _on_delivery(results: list[str | None], index: int) -> Any:
        def callback(err: KafkaError | None, _msg: Message) -> None:
            results[index] = None if err is None else str(err)

        return callback
