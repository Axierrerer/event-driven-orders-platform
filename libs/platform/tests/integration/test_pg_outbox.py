import asyncio
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import func, insert, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from events import OrderCreated, OrderCreatedPayload, OrderItem, uuid7
from platform_lib.consumer import IdempotentConsumer, PgInbox, RetryPolicy
from platform_lib.outbox import PgOutbox, PgOutboxRelay

from ..fakes import FakeDeadLetters, FakeMessage, FakePublisher, no_sleep
from .conftest import PgSchema

pytestmark = pytest.mark.integration


def make_event(order_id: UUID | None = None) -> OrderCreated:
    order_id = order_id or uuid7()
    return OrderCreated(
        producer="order-service",
        correlation_id=order_id,
        payload=OrderCreatedPayload(
            order_id=order_id,
            user_id=uuid7(),
            items=[OrderItem(product_id=uuid7(), quantity=2, unit_price=Decimal("1.50"))],
            total_amount=Decimal("3.00"),
            currency="RUB",
        ),
    )


async def count(session_factory: async_sessionmaker[AsyncSession], table: object) -> int:
    async with session_factory() as session:
        return int(await session.scalar(select(func.count()).select_from(table)) or 0)  # type: ignore[arg-type]


async def add_events(
    session_factory: async_sessionmaker[AsyncSession], schema: PgSchema, events: list[OrderCreated]
) -> None:
    outbox = PgOutbox(schema.outbox)
    async with session_factory() as session, session.begin():
        for event in events:
            await outbox.add(session, event)


# ---------- запись в outbox атомарна с бизнес-изменением ----------


async def test_outbox_row_committed_with_business_change(
    pg: tuple[AsyncEngine, PgSchema], session_factory: async_sessionmaker[AsyncSession]
) -> None:
    _, schema = pg
    event = make_event()
    async with session_factory() as session, session.begin():
        await session.execute(insert(schema.accounts).values(id=1, note="created"))
        await PgOutbox(schema.outbox).add(session, event, headers={"traceparent": "00-abc-01"})

    async with session_factory() as session:
        row = (await session.execute(select(schema.outbox))).mappings().one()
    assert row["id"] == event.event_id
    assert row["topic"] == "order.created"
    assert row["key"] == str(event.payload.order_id)
    assert row["published_at"] is None
    assert row["payload"]["payload"]["total_amount"] == "3.00"
    assert row["headers"]["traceparent"] == "00-abc-01"
    assert row["headers"]["event_type"] == "order.created"


async def test_rollback_leaves_no_outbox_row(
    pg: tuple[AsyncEngine, PgSchema], session_factory: async_sessionmaker[AsyncSession]
) -> None:
    _, schema = pg
    with pytest.raises(RuntimeError):
        async with session_factory() as session, session.begin():
            await session.execute(insert(schema.accounts).values(id=1, note="created"))
            await PgOutbox(schema.outbox).add(session, make_event())
            raise RuntimeError("бизнес-ошибка после записи")

    assert await count(session_factory, schema.outbox) == 0
    assert await count(session_factory, schema.accounts) == 0


# ---------- relay ----------


async def test_relay_publishes_in_order_and_marks_published(
    pg: tuple[AsyncEngine, PgSchema], session_factory: async_sessionmaker[AsyncSession]
) -> None:
    _, schema = pg
    events = [make_event() for _ in range(5)]
    await add_events(session_factory, schema, events)
    publisher = FakePublisher()
    relay = PgOutboxRelay(session_factory, schema.outbox, publisher)

    assert await relay.run_once() == 5
    assert [r.id for r in publisher.published] == [e.event_id for e in events]
    assert await relay.pending_count() == 0
    assert await relay.run_once() == 0  # повторно ничего не отправляет


async def test_relay_keeps_failed_records_and_retries_later(
    pg: tuple[AsyncEngine, PgSchema], session_factory: async_sessionmaker[AsyncSession]
) -> None:
    _, schema = pg
    events = [make_event() for _ in range(3)]
    await add_events(session_factory, schema, events)
    failing = events[1].event_id
    publisher = FakePublisher(fail_ids={failing})
    relay = PgOutboxRelay(session_factory, schema.outbox, publisher)

    assert await relay.run_once() == 2
    async with session_factory() as session:
        row = (
            (await session.execute(select(schema.outbox).where(schema.outbox.c.id == failing)))
            .mappings()
            .one()
        )
    assert row["published_at"] is None
    assert row["attempts"] == 1
    assert row["last_error"] == "broker unavailable"

    publisher.fail_ids.clear()  # брокер восстановился
    assert await relay.run_once() == 1
    assert await relay.pending_count() == 0


async def test_parallel_relays_publish_each_record_once(
    pg: tuple[AsyncEngine, PgSchema], session_factory: async_sessionmaker[AsyncSession]
) -> None:
    _, schema = pg
    events = [make_event() for _ in range(20)]
    await add_events(session_factory, schema, events)
    publisher = FakePublisher(delay=0.2)
    relays = [
        PgOutboxRelay(session_factory, schema.outbox, publisher, batch_size=5) for _ in range(4)
    ]

    while await relays[0].pending_count():
        await asyncio.gather(*(r.run_once() for r in relays))

    published_ids = [r.id for r in publisher.published]
    assert sorted(published_ids) == sorted(e.event_id for e in events)
    assert len(published_ids) == len(set(published_ids))
    assert published_ids == [e.event_id for e in events]  # порядок сохранён


async def test_run_forever_stops_on_event(
    pg: tuple[AsyncEngine, PgSchema], session_factory: async_sessionmaker[AsyncSession]
) -> None:
    _, schema = pg
    await add_events(session_factory, schema, [make_event()])
    publisher = FakePublisher()
    relay = PgOutboxRelay(session_factory, schema.outbox, publisher, poll_interval_seconds=0.05)
    stop = asyncio.Event()
    task = asyncio.create_task(relay.run_forever(stop))

    for _ in range(50):
        if publisher.published:
            break
        await asyncio.sleep(0.05)
    stop.set()
    await asyncio.wait_for(task, timeout=2)
    assert len(publisher.published) == 1


# ---------- идемпотентный consumer на PostgreSQL ----------


def make_consumer(
    session_factory: async_sessionmaker[AsyncSession], schema: PgSchema, event: OrderCreated
) -> tuple[IdempotentConsumer, PgInbox, FakeDeadLetters]:
    inbox = PgInbox(session_factory, schema.processed)
    dlq = FakeDeadLetters()
    consumer = IdempotentConsumer(
        group_id="inventory-service",
        inbox=inbox,
        decoder=lambda _msg: event,
        dead_letters=dlq,
        retry=RetryPolicy(delays_seconds=(0.0, 0.0, 0.0)),
        sleep=no_sleep,
    )
    return consumer, inbox, dlq


async def test_consumer_processes_event_once(
    pg: tuple[AsyncEngine, PgSchema], session_factory: async_sessionmaker[AsyncSession]
) -> None:
    _, schema = pg
    event = make_event()
    consumer, inbox, _ = make_consumer(session_factory, schema, event)
    next_id = iter(range(1, 100))

    @consumer.handler("order.created")
    async def handle(_event: OrderCreated, session: AsyncSession) -> None:
        await session.execute(insert(schema.accounts).values(id=next(next_id), note="reserved"))

    await consumer.process(FakeMessage("order.created", offset_no=1))
    await consumer.process(FakeMessage("order.created", offset_no=2))  # повторная доставка

    assert await count(session_factory, schema.accounts) == 1
    assert await inbox.is_processed(event.event_id, "inventory-service")


async def test_consumer_failure_rolls_back_mark_and_changes(
    pg: tuple[AsyncEngine, PgSchema], session_factory: async_sessionmaker[AsyncSession]
) -> None:
    _, schema = pg
    event = make_event()
    consumer, inbox, dlq = make_consumer(session_factory, schema, event)

    @consumer.handler("order.created")
    async def handle(_event: OrderCreated, session: AsyncSession) -> None:
        await session.execute(insert(schema.accounts).values(id=1, note="partial"))
        raise ConnectionError("downstream unavailable")

    await consumer.process(FakeMessage("order.created"))

    assert await count(session_factory, schema.accounts) == 0
    assert not await inbox.is_processed(event.event_id, "inventory-service")
    assert len(dlq.sent) == 1
