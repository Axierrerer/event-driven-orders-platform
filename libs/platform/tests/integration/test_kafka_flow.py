"""Сквозной поток на настоящей Kafka: outbox-публикатор → consumer → DLQ.

Schema Registry — in-memory mock: публикатор и consumer работают в одном процессе.
"""

import asyncio
from decimal import Decimal
from typing import Any

import pytest
from confluent_kafka import Consumer, Producer
from confluent_kafka.admin import AdminClient, NewTopic
from confluent_kafka.schema_registry import SchemaRegistryClient

from events import OrderCreated, OrderCreatedPayload, OrderItem, dlq_topic, uuid7
from platform_lib.consumer import (
    IdempotentConsumer,
    KafkaConsumerRunner,
    KafkaDeadLetterSink,
    schema_registry_decoder,
)
from platform_lib.kafka import make_consumer, make_producer
from platform_lib.outbox import KafkaEventPublisher, record_from_event

from ..fakes import FakeInbox, FakeTx

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def topics(kafka_bootstrap: str) -> None:
    admin = AdminClient({"bootstrap.servers": kafka_bootstrap})
    futures = admin.create_topics(
        [
            NewTopic(name, num_partitions=1, replication_factor=1)
            for name in ("order.created", dlq_topic("order.created"))
        ]
    )
    for future in futures.values():
        try:
            future.result()
        except Exception as exc:
            if "already exists" not in str(exc).lower():
                raise


def make_event() -> OrderCreated:
    order_id = uuid7()
    return OrderCreated(
        producer="order-service",
        correlation_id=order_id,
        payload=OrderCreatedPayload(
            order_id=order_id,
            user_id=uuid7(),
            items=[OrderItem(product_id=uuid7(), quantity=1, unit_price=Decimal("9.99"))],
            total_amount=Decimal("9.99"),
            currency="RUB",
        ),
    )


async def wait_until(condition: Any) -> None:
    while not condition():  # noqa: ASYNC110 — опрос внешнего брокера
        await asyncio.sleep(0.1)


async def test_publish_consume_dedupe_and_dlq(kafka_bootstrap: str, topics: None) -> None:
    registry = SchemaRegistryClient.new_client({"url": "mock://kafka-flow"})
    producer: Producer = make_producer(kafka_bootstrap, "test-producer")
    publisher = KafkaEventPublisher(producer, registry, auto_register_schemas=True)

    event = make_event()
    record = record_from_event(event, headers={"traceparent": "00-trace-01"})
    # одно и то же событие дважды (как при падении relay между send и update) + мусор
    assert await publisher.publish([record, record]) == [None, None]
    producer.produce("order.created", key=b"bad", value=b"not a schema registry message")
    producer.flush(10)

    inbox = FakeInbox()
    received: list[OrderCreated] = []
    consumer = IdempotentConsumer(
        group_id=f"test-{uuid7()}",
        inbox=inbox,
        decoder=schema_registry_decoder(registry),
        dead_letters=KafkaDeadLetterSink(producer),
    )

    @consumer.handler("order.created")
    async def handle(evt: OrderCreated, tx: FakeTx) -> None:
        received.append(evt)
        tx.effects.append(evt.event_id)

    kafka_consumer: Consumer = make_consumer(kafka_bootstrap, consumer.group_id, "test")
    runner = KafkaConsumerRunner(consumer, kafka_consumer, poll_timeout_seconds=0.2)
    stop = asyncio.Event()
    task = asyncio.create_task(runner.run(stop))

    dlq_reader: Consumer = make_consumer(kafka_bootstrap, f"dlq-{uuid7()}", "test-dlq")
    dlq_reader.subscribe([dlq_topic("order.created")])
    dlq_messages: list[Any] = []

    def poll_dlq() -> bool:
        msg = dlq_reader.poll(0.1)
        if msg is not None and not msg.error():
            dlq_messages.append(msg)
        return bool(dlq_messages) and len(inbox.effects) >= 1

    try:
        async with asyncio.timeout(30):
            await wait_until(poll_dlq)
        await asyncio.sleep(1)  # дать шанс второй копии события (она должна быть пропущена)
    finally:
        stop.set()
        await asyncio.wait_for(task, timeout=10)
        dlq_reader.close()

    assert received == [event]
    assert inbox.effects == [event.event_id]
    headers = dict(dlq_messages[0].headers())
    assert dlq_messages[0].value() == b"not a schema registry message"
    assert headers["dlq.original_topic"] == b"order.created"
    assert headers["dlq.error"].startswith(b"decode:")
