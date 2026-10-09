from decimal import Decimal
from uuid import UUID

import pytest

from events import BaseEvent, OrderCreated, OrderCreatedPayload, OrderItem, uuid7
from platform_lib.consumer import IdempotentConsumer, KafkaMessage, RetryPolicy

from .fakes import FakeDeadLetters, FakeInbox, FakeMessage, FakeTx

pytestmark = pytest.mark.unit

ORDER_ID = UUID("0192f0a0-0000-7000-8000-000000000004")


def make_event() -> OrderCreated:
    return OrderCreated(
        producer="order-service",
        correlation_id=ORDER_ID,
        payload=OrderCreatedPayload(
            order_id=ORDER_ID,
            user_id=uuid7(),
            items=[OrderItem(product_id=uuid7(), quantity=1, unit_price=Decimal("5.00"))],
            total_amount=Decimal("5.00"),
            currency="RUB",
        ),
    )


class Setup:
    def __init__(self, event: BaseEvent | None = None, *, decode_error: bool = False) -> None:
        self.event = event or make_event()
        self.inbox = FakeInbox()
        self.dlq = FakeDeadLetters()
        self.sleeps: list[float] = []

        def decode(_message: KafkaMessage) -> BaseEvent:
            if decode_error:
                raise ValueError("bad json")
            return self.event

        async def sleep(seconds: float) -> None:
            self.sleeps.append(seconds)

        self.consumer = IdempotentConsumer(
            group_id="inventory-service",
            inbox=self.inbox,
            decoder=decode,
            dead_letters=self.dlq,
            retry=RetryPolicy(delays_seconds=(0.5, 2.0, 8.0)),
            sleep=sleep,
        )


async def test_handler_called_once_and_event_marked() -> None:
    s = Setup()
    calls: list[BaseEvent] = []

    @s.consumer.handler("order.created")
    async def handle(event: BaseEvent, tx: FakeTx) -> None:
        calls.append(event)
        tx.effects.append("reserved")

    await s.consumer.process(FakeMessage("order.created"))

    assert calls == [s.event]
    assert s.inbox.effects == ["reserved"]
    assert (s.event.event_id, "inventory-service") in s.inbox.processed
    assert s.dlq.sent == []


async def test_redelivered_event_is_skipped() -> None:
    s = Setup()
    calls = 0

    @s.consumer.handler("order.created")
    async def handle(_event: BaseEvent, _tx: FakeTx) -> None:
        nonlocal calls
        calls += 1

    await s.consumer.process(FakeMessage("order.created", offset_no=1))
    await s.consumer.process(FakeMessage("order.created", offset_no=2))

    assert calls == 1


async def test_failure_rolls_back_mark_and_retries_then_dlq() -> None:
    s = Setup()
    attempts = 0

    @s.consumer.handler("order.created")
    async def handle(_event: BaseEvent, tx: FakeTx) -> None:
        nonlocal attempts
        attempts += 1
        tx.effects.append("partial write")
        raise ConnectionError("db down")

    await s.consumer.process(FakeMessage("order.created"))

    assert attempts == 4  # первая попытка + 3 повтора
    assert s.sleeps == [0.5, 2.0, 8.0]
    assert s.inbox.processed == set()
    assert s.inbox.effects == []
    assert len(s.dlq.sent) == 1
    topic, error = s.dlq.sent[0]
    assert topic == "order.created"
    assert "ConnectionError" in error


async def test_transient_failure_recovers_without_dlq() -> None:
    s = Setup()
    attempts = 0

    @s.consumer.handler("order.created")
    async def handle(_event: BaseEvent, tx: FakeTx) -> None:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise TimeoutError
        tx.effects.append("ok")

    await s.consumer.process(FakeMessage("order.created"))

    assert attempts == 3
    assert s.inbox.effects == ["ok"]
    assert s.dlq.sent == []


async def test_decode_error_goes_straight_to_dlq() -> None:
    s = Setup(decode_error=True)
    called = False

    @s.consumer.handler("order.created")
    async def handle(_event: BaseEvent, _tx: FakeTx) -> None:
        nonlocal called
        called = True

    await s.consumer.process(FakeMessage("order.created", payload=b"garbage"))

    assert not called
    assert s.sleeps == []
    assert s.dlq.sent[0][1].startswith("decode:")


async def test_message_without_handler_goes_to_dlq() -> None:
    s = Setup()
    await s.consumer.process(FakeMessage("order.created"))
    assert len(s.dlq.sent) == 1


def test_handler_for_unknown_topic_rejected() -> None:
    s = Setup()
    with pytest.raises(ValueError, match="Неизвестный топик"):
        s.consumer.handler("no.such.topic")


def test_topics_lists_registered_handlers() -> None:
    s = Setup()

    @s.consumer.handler("order.created")
    async def a(_event: BaseEvent, _tx: FakeTx) -> None: ...

    @s.consumer.handler("order.status-changed")
    async def b(_event: BaseEvent, _tx: FakeTx) -> None: ...

    assert s.consumer.topics == ["order.created", "order.status-changed"]
