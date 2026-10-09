import asyncio
from decimal import Decimal

import pytest
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from events import OrderStatus, ProductChanged, ProductChangedPayload, uuid7
from platform_lib.consumer import IdempotentConsumer, PgInbox, RetryPolicy
from src import db
from src.services.inventory import InventoryService

from ..conftest import (
    Clock,
    Handle,
    order_created,
    outbox,
    put_stock,
    status_changed,
    stock_row,
)

pytestmark = pytest.mark.integration


async def reservations_count(session_factory: async_sessionmaker[AsyncSession]) -> int:
    async with session_factory() as session:
        return int(await session.scalar(select(func.count()).select_from(db.reservations)) or 0)


async def reservation_status(
    session_factory: async_sessionmaker[AsyncSession], order_id: object
) -> str:
    async with session_factory() as session:
        status = await session.scalar(
            select(db.reservations.c.status).where(db.reservations.c.order_id == order_id)
        )
    return str(status)


# ---------- каталог ----------


async def test_product_changed_creates_stock_row_once(
    handle: Handle, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    product_id = uuid7()
    event = ProductChanged(
        producer="product-service",
        correlation_id=product_id,
        payload=ProductChangedPayload(
            product_id=product_id,
            sku="SKU-1",
            name="Кружка",
            price=Decimal("10.00"),
            currency="RUB",
            is_published=True,
            is_deleted=False,
        ),
    )
    await handle(event)
    await handle(event)
    assert await stock_row(session_factory, product_id) == (0, 0)


# ---------- резервирование ----------


async def test_order_reserved_when_stock_is_enough(
    handle: Handle, session_factory: async_sessionmaker[AsyncSession], clock: Clock
) -> None:
    mug, plate = uuid7(), uuid7()
    await put_stock(session_factory, mug, 5)
    await put_stock(session_factory, plate, 2)
    event = order_created([(mug, 2), (plate, 2), (mug, 1)])  # одинаковые позиции объединяются

    await handle(event)

    assert await stock_row(session_factory, mug) == (5, 3)
    assert await stock_row(session_factory, plate) == (2, 2)
    assert await reservation_status(session_factory, event.payload.order_id) == "ACTIVE"
    [published] = await outbox(session_factory)
    assert published["topic"] == "inventory.reserved"
    assert published["key"] == str(event.payload.order_id)
    payload = published["payload"]["payload"]
    assert {i["product_id"]: i["quantity"] for i in payload["items"]} == {
        str(mug): 3,
        str(plate): 2,
    }
    assert payload["expires_at"] == "2026-10-09T12:15:00Z"


async def test_partial_shortage_reserves_nothing(
    handle: Handle, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    mug, plate = uuid7(), uuid7()
    await put_stock(session_factory, mug, 5)
    await put_stock(session_factory, plate, 1)

    await handle(order_created([(mug, 2), (plate, 3)]))

    assert await stock_row(session_factory, mug) == (5, 0)
    assert await stock_row(session_factory, plate) == (1, 0)
    assert await reservations_count(session_factory) == 0
    [failed] = await outbox(session_factory)
    assert failed["topic"] == "inventory.reservation-failed"
    payload = failed["payload"]["payload"]
    assert payload["reason"] == "OUT_OF_STOCK"
    assert payload["missing"] == [{"product_id": str(plate), "requested": 3, "available": 1}]


async def test_unknown_product_fails_reservation(
    handle: Handle, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    known, unknown = uuid7(), uuid7()
    await put_stock(session_factory, known, 5)

    await handle(order_created([(known, 1), (unknown, 1)]))

    [failed] = await outbox(session_factory)
    assert failed["payload"]["payload"]["reason"] == "UNKNOWN_PRODUCT"
    assert await stock_row(session_factory, known) == (5, 0)


async def test_same_order_with_new_event_id_is_not_reserved_twice(
    handle: Handle, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    mug = uuid7()
    await put_stock(session_factory, mug, 5)
    first = order_created([(mug, 2)])
    second = order_created([(mug, 2)], order_id=first.payload.order_id)  # другой event_id

    await handle(first)
    await handle(second)

    assert await stock_row(session_factory, mug) == (5, 2)
    assert await reservations_count(session_factory) == 1


class Message:
    """Минимальное Kafka-сообщение для IdempotentConsumer."""

    def __init__(self, topic: str, offset: int) -> None:
        self._topic, self._offset = topic, offset

    def topic(self) -> str:
        return self._topic

    def key(self) -> bytes:
        return b""

    def value(self) -> bytes:
        return b""

    def headers(self) -> None:
        return None

    def partition(self) -> int:
        return 0

    def offset(self) -> int:
        return self._offset


class NoDeadLetters:
    async def send(self, message: object, error: str) -> None:
        raise AssertionError(f"unexpected DLQ: {error}")


async def test_redelivered_event_is_processed_once(
    session_factory: async_sessionmaker[AsyncSession], service: InventoryService
) -> None:
    mug = uuid7()
    await put_stock(session_factory, mug, 5)
    event = order_created([(mug, 1)])
    consumer = IdempotentConsumer(
        group_id="inventory-service",
        inbox=PgInbox(session_factory, db.processed_events),
        decoder=lambda _message: event,
        dead_letters=NoDeadLetters(),
        retry=RetryPolicy(delays_seconds=()),
    )
    consumer.handler("order.created")(service.on_order_created)

    await consumer.process(Message("order.created", 1))
    await consumer.process(Message("order.created", 2))  # повторная доставка того же event_id

    assert await stock_row(session_factory, mug) == (5, 1)
    assert len(await outbox(session_factory)) == 1


async def test_parallel_orders_never_oversell(
    handle: Handle, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    mug = uuid7()
    await put_stock(session_factory, mug, 10)

    await asyncio.gather(*(handle(order_created([(mug, 1)])) for _ in range(20)))

    assert await stock_row(session_factory, mug) == (10, 10)
    topics = [e["topic"] for e in await outbox(session_factory)]
    assert topics.count("inventory.reserved") == 10
    assert topics.count("inventory.reservation-failed") == 10


async def test_parallel_orders_on_overlapping_products_do_not_deadlock(
    handle: Handle, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    a, b = uuid7(), uuid7()
    await put_stock(session_factory, a, 100)
    await put_stock(session_factory, b, 100)
    orders = [order_created([(a, 1), (b, 1)]) for _ in range(10)]
    orders += [order_created([(b, 1), (a, 1)]) for _ in range(10)]  # обратный порядок позиций

    await asyncio.wait_for(asyncio.gather(*(handle(o) for o in orders)), timeout=30)

    assert await stock_row(session_factory, a) == (100, 20)
    assert await stock_row(session_factory, b) == (100, 20)


# ---------- статусы заказа ----------


async def test_cancel_releases_reservation_once(
    handle: Handle, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    mug = uuid7()
    await put_stock(session_factory, mug, 5)
    order = order_created([(mug, 2)])
    order_id = order.payload.order_id
    await handle(order)

    cancel = status_changed(order_id, OrderStatus.RESERVED, OrderStatus.CANCELLED)
    await handle(cancel)
    await handle(status_changed(order_id, OrderStatus.RESERVED, OrderStatus.CANCELLED))

    assert await stock_row(session_factory, mug) == (5, 0)
    assert await reservation_status(session_factory, order_id) == "RELEASED"
    released = [e for e in await outbox(session_factory) if e["topic"] == "inventory.released"]
    assert len(released) == 1
    assert released[0]["payload"]["payload"]["reason"] == "ORDER_CANCELLED"


async def test_cancel_without_reservation_is_ignored(handle: Handle) -> None:
    await handle(status_changed(uuid7(), OrderStatus.NEW, OrderStatus.CANCELLED))


async def test_paid_confirms_and_shipped_commits(
    handle: Handle,
    session_factory: async_sessionmaker[AsyncSession],
    service: InventoryService,
    clock: Clock,
) -> None:
    mug = uuid7()
    await put_stock(session_factory, mug, 5)
    order = order_created([(mug, 2)])
    order_id = order.payload.order_id
    await handle(order)

    await handle(status_changed(order_id, OrderStatus.RESERVED, OrderStatus.PAID))
    assert await reservation_status(session_factory, order_id) == "CONFIRMED"

    clock.advance(hours=1)  # оплаченный резерв не истекает
    assert await service.expire_reservations() == 0

    await handle(status_changed(order_id, OrderStatus.PAID, OrderStatus.SHIPPED))
    assert await stock_row(session_factory, mug) == (3, 0)
    assert await reservation_status(session_factory, order_id) == "COMMITTED"

    # повторная отгрузка не списывает второй раз
    await handle(status_changed(order_id, OrderStatus.PAID, OrderStatus.SHIPPED))
    assert await stock_row(session_factory, mug) == (3, 0)


async def test_paid_cancelled_order_releases_confirmed_reservation(
    handle: Handle, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    mug = uuid7()
    await put_stock(session_factory, mug, 5)
    order = order_created([(mug, 2)])
    order_id = order.payload.order_id
    await handle(order)
    await handle(status_changed(order_id, OrderStatus.RESERVED, OrderStatus.PAID))
    await handle(status_changed(order_id, OrderStatus.PAID, OrderStatus.CANCELLED))
    assert await stock_row(session_factory, mug) == (5, 0)


# ---------- истечение резервов ----------


async def test_expired_reservation_is_released(
    handle: Handle,
    session_factory: async_sessionmaker[AsyncSession],
    service: InventoryService,
    clock: Clock,
) -> None:
    mug = uuid7()
    await put_stock(session_factory, mug, 5)
    order = order_created([(mug, 2)])
    await handle(order)

    clock.advance(minutes=14)
    assert await service.expire_reservations() == 0
    clock.advance(minutes=2)
    assert await service.expire_reservations() == 1

    assert await stock_row(session_factory, mug) == (5, 0)
    released = (await outbox(session_factory))[-1]
    assert released["topic"] == "inventory.released"
    assert released["payload"]["payload"]["reason"] == "EXPIRED"
    # отмена уже истёкшего резерва ничего не ломает
    await handle(
        status_changed(order.payload.order_id, OrderStatus.RESERVED, OrderStatus.CANCELLED)
    )
    assert await stock_row(session_factory, mug) == (5, 0)


async def test_two_replicas_release_each_reservation_once(
    handle: Handle,
    session_factory: async_sessionmaker[AsyncSession],
    service: InventoryService,
    clock: Clock,
    redis: Redis,
) -> None:
    mug = uuid7()
    await put_stock(session_factory, mug, 30)
    for _ in range(30):
        await handle(order_created([(mug, 1)]))
    clock.advance(hours=1)

    stop = asyncio.Event()
    replicas = [
        asyncio.create_task(service.run_expiry_loop(stop, redis, interval_seconds=0.05))
        for _ in range(2)
    ]
    for _ in range(100):
        if await stock_row(session_factory, mug) == (30, 0):
            break
        await asyncio.sleep(0.05)
    stop.set()
    await asyncio.gather(*replicas)

    assert await stock_row(session_factory, mug) == (30, 0)
    released = [e for e in await outbox(session_factory) if e["topic"] == "inventory.released"]
    assert len(released) == 30
