from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from events import (
    InventoryReleased,
    InventoryReleasedPayload,
    InventoryReservationFailed,
    InventoryReservationFailedPayload,
    InventoryReserved,
    InventoryReservedPayload,
    ReleaseReason,
    ReservationFailureReason,
    ReservedItem,
    Role,
    uuid7,
)
from platform_lib.consumer import IdempotentConsumer, PgInbox, RetryPolicy
from src import db

from ..conftest import World

pytestmark = pytest.mark.integration


def reserved_event(order: dict, *, ttl: timedelta = timedelta(minutes=15)) -> InventoryReserved:
    order_id = order["id"]
    return InventoryReserved(
        producer="inventory-service",
        correlation_id=order_id,
        payload=InventoryReservedPayload(
            order_id=order_id,
            reservation_id=uuid7(),
            items=[
                ReservedItem(product_id=i["product_id"], quantity=i["quantity"])
                for i in order["items"]
            ],
            expires_at=datetime(2026, 10, 9, 12, 0, tzinfo=UTC) + ttl,
        ),
    )


async def placed(world: World, user_id: object | None = None) -> dict:
    product = world.catalog.add("100.00")
    world.inventory.stock[product] = 10
    response = await world.place(user_id or uuid7(), [(product, 2)])
    assert response.status_code == 201, response.text
    return dict(response.json())


async def reserved(world: World, user_id: object) -> dict:
    order = await placed(world, user_id)
    await world.handle(world.service.on_inventory_reserved, reserved_event(order))
    return order


# ---------- оформление ----------


async def test_create_uses_catalog_prices_and_publishes_event(world: World) -> None:
    cup = world.catalog.add("0.10", name="Чашка")
    pot = world.catalog.add("1499.99", name="Чайник")
    world.inventory.stock |= {cup: 10, pot: 10}
    user = uuid7()

    response = await world.place(user, [(cup, 1), (pot, 2), (cup, 2)])

    assert response.status_code == 201
    order = response.json()
    assert order["status"] == "NEW"
    assert order["total_amount"] == "3000.28"
    assert {i["product_name"]: (i["quantity"], i["unit_price"]) for i in order["items"]} == {
        "Чашка": (3, "0.10"),
        "Чайник": (2, "1499.99"),
    }
    assert [h["to_status"] for h in order["history"]] == ["NEW"]
    [event] = await world.outbox()
    assert event["topic"] == "order.created"
    assert event["key"] == order["id"]
    assert event["payload"]["payload"]["total_amount"] == "3000.28"


async def test_client_price_is_rejected(world: World) -> None:
    product = world.catalog.add("10.00")
    response = await world.client.post(
        "/api/v1/orders",
        json={"items": [{"product_id": str(product), "quantity": 1, "unit_price": "0.01"}]},
        headers=world.headers(uuid7(), key="key-12345678"),
    )
    assert response.status_code == 422


async def test_hidden_or_unknown_product_rejected(world: World) -> None:
    hidden = world.catalog.add("10.00", published=False)
    for product in (hidden, uuid7()):
        response = await world.place(uuid7(), [(product, 1)])
        assert response.status_code == 422
        assert response.json()["detail"]["product_ids"] == [str(product)]


async def test_out_of_stock_rejected_early(world: World) -> None:
    product = world.catalog.add("10.00")
    world.inventory.stock[product] = 1
    response = await world.place(uuid7(), [(product, 2)])
    assert response.status_code == 409
    assert response.json()["detail"]["items"][0]["available"] == 1
    assert await world.outbox() == []


async def test_inventory_down_does_not_block_checkout(world: World) -> None:
    product = world.catalog.add("10.00")
    world.inventory.fail = True
    assert (await world.place(uuid7(), [(product, 1)])).status_code == 201


async def test_catalog_down_returns_503(world: World) -> None:
    product = world.catalog.add("10.00")
    world.catalog.fail = True
    assert (await world.place(uuid7(), [(product, 1)])).status_code == 503


async def test_unverified_email_cannot_order(world: World) -> None:
    product = world.catalog.add("10.00")
    response = await world.client.post(
        "/api/v1/orders",
        json={"items": [{"product_id": str(product), "quantity": 1}]},
        headers=world.headers(uuid7(), verified=False, key="key-12345678"),
    )
    assert response.status_code == 403


@pytest.mark.parametrize(
    "items",
    [[], [(0, 101)], [(i, 1) for i in range(51)], [(0, 60), (0, 41)]],
    ids=["empty", "quantity-101", "51-products", "merged-over-100"],
)
async def test_order_limits(world: World, items: list[tuple[int, int]]) -> None:
    products = [world.catalog.add("1.00") for _ in range(51)]
    response = await world.place(uuid7(), [(products[i], q) for i, q in items])
    assert response.status_code == 422


async def test_mixed_currencies_rejected(world: World) -> None:
    rub = world.catalog.add("1.00")
    usd = world.catalog.add("1.00", currency="USD")
    assert (await world.place(uuid7(), [(rub, 1), (usd, 1)])).status_code == 422


# ---------- идемпотентность ----------


async def test_same_idempotency_key_returns_same_order(world: World) -> None:
    product = world.catalog.add("10.00")
    world.inventory.stock[product] = 10
    user = uuid7()
    first = await world.place(user, [(product, 1)], key="checkout-0001")
    again = await world.place(user, [(product, 1)], key="checkout-0001")

    assert first.status_code == 201
    assert again.status_code == 200
    assert again.json()["id"] == first.json()["id"]
    assert len(await world.outbox()) == 1

    other_body = await world.place(user, [(product, 2)], key="checkout-0001")
    assert other_body.status_code == 422
    other_user = await world.place(uuid7(), [(product, 1)], key="checkout-0001")
    assert other_user.status_code == 201  # ключ уникален в паре с пользователем


async def test_idempotency_key_is_required(world: World) -> None:
    product = world.catalog.add("10.00")
    response = await world.client.post(
        "/api/v1/orders",
        json={"items": [{"product_id": str(product), "quantity": 1}]},
        headers=world.tokens.headers(uuid7()),
    )
    assert response.status_code == 422


async def test_old_idempotency_keys_are_cleaned(world: World) -> None:
    await placed(world)
    world.clock.advance(hours=23)
    assert await world.service.cleanup_idempotency_keys(timedelta(hours=24)) == 0
    world.clock.advance(hours=2)
    assert await world.service.cleanup_idempotency_keys(timedelta(hours=24)) == 1
    async with world.session_factory() as session:
        count = await session.scalar(select(func.count()).select_from(db.idempotency_keys))
    assert count == 0


# ---------- сага ----------


async def test_reserved_event_moves_order_to_reserved(world: World) -> None:
    order = await placed(world)
    await world.handle(world.service.on_inventory_reserved, reserved_event(order))

    body = (
        await world.client.get(
            f"/api/v1/orders/{order['id']}", headers=world.headers(order["user_id"])
        )
    ).json()
    assert body["status"] == "RESERVED"
    assert body["reserved_until"] == "2026-10-09T12:15:00Z"
    changed = (await world.outbox())[-1]
    assert changed["topic"] == "order.status-changed"
    assert changed["payload"]["payload"]["old_status"] == "NEW"
    assert changed["payload"]["payload"]["new_status"] == "RESERVED"


async def test_reservation_failed_cancels_with_reason(world: World) -> None:
    order = await placed(world)
    event = InventoryReservationFailed(
        producer="inventory-service",
        correlation_id=order["id"],
        payload=InventoryReservationFailedPayload(
            order_id=order["id"], reason=ReservationFailureReason.OUT_OF_STOCK
        ),
    )
    await world.handle(world.service.on_reservation_failed, event)

    response = await world.client.get(
        f"/api/v1/orders/{order['id']}", headers=world.headers(order["user_id"])
    )
    body = response.json()
    assert body["status"] == "CANCELLED"
    assert body["cancel_reason"] == "OUT_OF_STOCK"
    assert [h["to_status"] for h in body["history"]] == ["NEW", "CANCELLED"]


async def test_redelivered_saga_event_is_applied_once(world: World) -> None:
    order = await placed(world)
    event = reserved_event(order)

    class Message:
        def __init__(self, offset: int) -> None:
            self._offset = offset

        def topic(self) -> str:
            return "inventory.reserved"

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

    class NoDlq:
        async def send(self, message: object, error: str) -> None:
            raise AssertionError(error)

    consumer = IdempotentConsumer(
        group_id="order-service",
        inbox=PgInbox(world.session_factory, db.processed_events),
        decoder=lambda _m: event,
        dead_letters=NoDlq(),
        retry=RetryPolicy(delays_seconds=()),
    )
    consumer.handler("inventory.reserved")(world.service.on_inventory_reserved)
    await consumer.process(Message(1))
    await consumer.process(Message(2))

    async with world.session_factory() as session:
        history = await session.scalar(select(func.count()).select_from(db.order_status_history))
    assert history == 2  # NEW + RESERVED


async def test_reserved_after_cancel_requests_release(world: World) -> None:
    order = await placed(world)
    user = order["user_id"]
    cancelled = await world.client.post(
        f"/api/v1/orders/{order['id']}/cancel", headers=world.headers(user)
    )
    assert cancelled.json()["status"] == "CANCELLED"

    await world.handle(world.service.on_inventory_reserved, reserved_event(order))

    body = (
        await world.client.get(f"/api/v1/orders/{order['id']}", headers=world.headers(user))
    ).json()
    assert body["status"] == "CANCELLED"
    compensation = (await world.outbox())[-1]["payload"]["payload"]
    assert compensation["new_status"] == "CANCELLED"
    assert compensation["reason"] == "RESERVED_AFTER_CANCEL"


async def test_expired_reservation_cancels_order(world: World) -> None:
    user = uuid7()
    order = await reserved(world, user)
    released = InventoryReleased(
        producer="inventory-service",
        correlation_id=order["id"],
        payload=InventoryReleasedPayload(
            order_id=order["id"], reservation_id=uuid7(), reason=ReleaseReason.EXPIRED
        ),
    )
    await world.handle(world.service.on_inventory_released, released)
    body = (
        await world.client.get(f"/api/v1/orders/{order['id']}", headers=world.headers(user))
    ).json()
    assert body["status"] == "CANCELLED"
    assert body["cancel_reason"] == "RESERVATION_EXPIRED"


async def test_release_after_our_cancel_is_only_audit(world: World) -> None:
    user = uuid7()
    order = await reserved(world, user)
    released = InventoryReleased(
        producer="inventory-service",
        correlation_id=order["id"],
        payload=InventoryReleasedPayload(
            order_id=order["id"], reservation_id=uuid7(), reason=ReleaseReason.ORDER_CANCELLED
        ),
    )
    await world.handle(world.service.on_inventory_released, released)
    body = (
        await world.client.get(f"/api/v1/orders/{order['id']}", headers=world.headers(user))
    ).json()
    assert body["status"] == "RESERVED"


# ---------- оплата, отгрузка, отмена ----------


async def test_full_lifecycle(world: World) -> None:
    user, manager = uuid7(), world.headers(uuid7(), [Role.MANAGER])
    order = await reserved(world, user)
    url = f"/api/v1/orders/{order['id']}"

    paid = await world.client.post(f"{url}/pay", headers=world.headers(user))
    assert paid.status_code == 200
    assert paid.json()["status"] == "PAID"
    assert (await world.client.post(f"{url}/ship", headers=manager)).json()["status"] == "SHIPPED"
    done = await world.client.post(f"{url}/complete", headers=manager)
    assert done.json()["status"] == "COMPLETED"
    assert [h["to_status"] for h in done.json()["history"]] == [
        "NEW",
        "RESERVED",
        "PAID",
        "SHIPPED",
        "COMPLETED",
    ]
    statuses = [
        e["payload"]["payload"]["new_status"]
        for e in await world.outbox()
        if e["topic"] == "order.status-changed"
    ]
    assert statuses == ["RESERVED", "PAID", "SHIPPED", "COMPLETED"]


async def test_pay_requires_reserved_status(world: World) -> None:
    order = await placed(world)
    response = await world.client.post(
        f"/api/v1/orders/{order['id']}/pay", headers=world.headers(order["user_id"])
    )
    assert response.status_code == 409


async def test_declined_payment_keeps_order_reserved(world: World) -> None:
    user = uuid7()
    product = world.catalog.add("10.13")
    world.inventory.stock[product] = 5
    order = (await world.place(user, [(product, 1)])).json()
    await world.handle(world.service.on_inventory_reserved, reserved_event(order))

    response = await world.client.post(
        f"/api/v1/orders/{order['id']}/pay", headers=world.headers(user)
    )
    assert response.status_code == 402
    body = (
        await world.client.get(f"/api/v1/orders/{order['id']}", headers=world.headers(user))
    ).json()
    assert body["status"] == "RESERVED"
    async with world.session_factory() as session:
        statuses = (await session.execute(select(db.payments.c.status))).scalars().all()
    assert statuses == ["DECLINED"]


async def test_pay_after_reservation_deadline_rejected(world: World) -> None:
    user = uuid7()
    order = await reserved(world, user)
    world.clock.advance(minutes=16)
    response = await world.client.post(
        f"/api/v1/orders/{order['id']}/pay", headers=world.headers(user)
    )
    assert response.status_code == 409


async def test_staff_cancel_of_paid_order_refunds(world: World) -> None:
    user = uuid7()
    order = await reserved(world, user)
    url = f"/api/v1/orders/{order['id']}"
    await world.client.post(f"{url}/pay", headers=world.headers(user))

    by_customer = await world.client.post(f"{url}/cancel", headers=world.headers(user))
    assert by_customer.status_code == 403

    by_manager = await world.client.post(
        f"{url}/cancel",
        json={"reason": "нет на складе"},
        headers=world.headers(uuid7(), [Role.MANAGER]),
    )
    assert by_manager.status_code == 200
    assert by_manager.json()["status"] == "CANCELLED"
    assert by_manager.json()["cancel_reason"] == "нет на складе"
    assert len(world.payments.refunds) == 1


async def test_customer_cancels_reserved_order(world: World) -> None:
    user = uuid7()
    order = await reserved(world, user)
    response = await world.client.post(
        f"/api/v1/orders/{order['id']}/cancel", headers=world.headers(user)
    )
    assert response.json()["cancel_reason"] == "CANCELLED_BY_CUSTOMER"


async def test_ship_rules(world: World) -> None:
    user = uuid7()
    order = await reserved(world, user)
    url = f"/api/v1/orders/{order['id']}"
    assert (await world.client.post(f"{url}/ship", headers=world.headers(user))).status_code == 403
    manager = world.headers(uuid7(), [Role.MANAGER])
    assert (await world.client.post(f"{url}/ship", headers=manager)).status_code == 409


# ---------- доступ ----------


async def test_foreign_orders_are_invisible(world: World) -> None:
    owner, stranger = uuid7(), uuid7()
    order = await reserved(world, owner)
    url = f"/api/v1/orders/{order['id']}"
    for method, path in (("get", url), ("post", f"{url}/pay"), ("post", f"{url}/cancel")):
        response = await getattr(world.client, method)(path, headers=world.headers(stranger))
        assert response.status_code == 404, path


async def test_listing_scoped_by_role(world: World) -> None:
    alice, bob = uuid7(), uuid7()
    await placed(world, alice)
    await placed(world, alice)
    await reserved(world, bob)

    mine = (await world.client.get("/api/v1/orders", headers=world.headers(alice))).json()
    assert len(mine) == 2
    sneaky = await world.client.get(f"/api/v1/orders?user_id={bob}", headers=world.headers(alice))
    assert len(sneaky.json()) == 2  # фильтр по чужому user_id игнорируется

    manager = world.headers(uuid7(), [Role.MANAGER])
    assert len((await world.client.get("/api/v1/orders", headers=manager)).json()) == 3
    reserved_only = (
        await world.client.get("/api/v1/orders?status=RESERVED", headers=manager)
    ).json()
    assert [o["user_id"] for o in reserved_only] == [str(bob)]
    assert (await world.client.get("/api/v1/orders")).status_code == 401
