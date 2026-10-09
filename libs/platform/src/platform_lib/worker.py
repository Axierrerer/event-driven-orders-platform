"""Фоновые процессы сервисов: outbox relay + consumer Kafka + heartbeat."""

import asyncio
import signal
import socket
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from confluent_kafka.schema_registry import SchemaRegistryClient
from sqlalchemy import Table
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from platform_lib.consumer import (
    IdempotentConsumer,
    InboxStore,
    KafkaConsumerRunner,
    KafkaDeadLetterSink,
    MongoInbox,
    PgInbox,
    schema_registry_decoder,
)
from platform_lib.heartbeat import heartbeat
from platform_lib.kafka import make_consumer, make_producer
from platform_lib.logging import get_logger
from platform_lib.metrics import start_metrics_server
from platform_lib.outbox import KafkaEventPublisher, MongoOutboxRelay, PgOutboxRelay
from platform_lib.settings import KafkaSettings, ServiceSettings
from platform_lib.telemetry import configure_tracing

log = get_logger(__name__)

Handler = Callable[[Any, Any], Awaitable[None]]
BackgroundTask = Callable[[asyncio.Event], Awaitable[None]]


async def _run(
    settings: ServiceSettings,
    *,
    relay_factory: Callable[[KafkaEventPublisher], Any],
    inbox: InboxStore,
    handlers: Mapping[str, Handler],
    extra_tasks: list[BackgroundTask] | None,
) -> None:
    if not isinstance(settings, KafkaSettings):
        raise TypeError("settings must include KafkaSettings")
    configure_tracing(settings.service_name, settings.otel_exporter_otlp_endpoint)
    start_metrics_server(settings.worker_metrics_port)
    client_id = f"{settings.service_name}-{socket.gethostname()}"
    registry = SchemaRegistryClient({"url": settings.schema_registry_url})
    producer = make_producer(settings.kafka_bootstrap, client_id)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)

    relay = relay_factory(KafkaEventPublisher(producer, registry))
    tasks: list[Awaitable[None]] = [relay.run_forever(stop), heartbeat(stop)]

    if handlers:
        consumer = IdempotentConsumer(
            group_id=settings.service_name,
            inbox=inbox,
            decoder=schema_registry_decoder(registry),
            dead_letters=KafkaDeadLetterSink(producer),
        )
        for topic, handler in handlers.items():
            consumer.handler(topic)(handler)
        kafka_consumer = make_consumer(settings.kafka_bootstrap, settings.service_name, client_id)
        tasks.append(KafkaConsumerRunner(consumer, kafka_consumer).run(stop))

    tasks.extend(task(stop) for task in extra_tasks or [])

    log.info("worker_started", topics=sorted(handlers))
    try:
        await asyncio.gather(*tasks)
    finally:
        producer.flush(10)
        log.info("worker_stopped")


async def run_pg_worker(
    settings: ServiceSettings,
    *,
    engine: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
    outbox: Table,
    processed_events: Table,
    handlers: Mapping[str, Handler],
    extra_tasks: list[BackgroundTask] | None = None,
) -> None:
    """Сервис на PostgreSQL: relay outbox, consumer (если есть обработчики), heartbeat."""
    try:
        await _run(
            settings,
            relay_factory=lambda publisher: PgOutboxRelay(session_factory, outbox, publisher),
            inbox=PgInbox(session_factory, processed_events),
            handlers=handlers,
            extra_tasks=extra_tasks,
        )
    finally:
        await engine.dispose()


async def run_mongo_worker(
    settings: ServiceSettings,
    *,
    client: Any,
    database: Any,
    handlers: Mapping[str, Handler],
    extra_tasks: list[BackgroundTask] | None = None,
) -> None:
    """Сервис на MongoDB: коллекции outbox, leases и processed_events в `database`."""
    owner = f"{settings.service_name}-{socket.gethostname()}"
    try:
        await _run(
            settings,
            relay_factory=lambda publisher: MongoOutboxRelay(
                database.outbox, database.leases, publisher, owner_id=owner
            ),
            inbox=MongoInbox(client, database.processed_events),
            handlers=handlers,
            extra_tasks=extra_tasks,
        )
    finally:
        client.close()
