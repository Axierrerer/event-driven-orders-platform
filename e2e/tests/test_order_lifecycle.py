"""Сценарии полного жизненного цикла заказа через публичный API."""

import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import pytest
from confluent_kafka import Consumer, Producer, TopicPartition

from .conftest import Platform, User, compose, wait_for, wait_until

pytestmark = pytest.mark.e2e

KAFKA = "localhost:9094"


def test_1_happy_path(platform: Platform, admin: User, manager: User, buyer: User) -> None:
    product = platform.product_with_stock(admin, stock=5, price="1490.00")
    found = platform.http.get(
        f"{platform_api()}/products", params={"q": "E2E", "limit": 100}
    ).json()["items"]
    assert any(p["id"] == product for p in found), "product is not searchable"

    created = platform.place_order(buyer, [(product, 2)])
    assert created.status_code == 201, created.text
    order_id = created.json()["id"]
    assert created.json()["total_amount"] == "2980.00"

    platform.wait_status(buyer, order_id, "RESERVED")
    assert platform.action(buyer, order_id, "pay").json()["status"] == "PAID"
    assert platform.action(manager, order_id, "ship").json()["status"] == "SHIPPED"
    done = platform.action(manager, order_id, "complete").json()
    assert done["status"] == "COMPLETED"
    assert [h["to_status"] for h in done["history"]] == [
        "NEW",
        "RESERVED",
        "PAID",
        "SHIPPED",
        "COMPLETED",
    ]

    stock = wait_until(
        lambda: platform.stock(manager, product),
        lambda level: level["on_hand"] == 3,
        "stock written off",
    )
    assert stock["reserved"] == 0

    expected = ["оформлен", "зарезервирован", "оплачен", "отправлен", "выполнен"]
    subjects = wait_until(
        lambda: [x for x in platform.email_subjects(buyer.email) if order_id in x],
        lambda found: all(any(part in x for x in found) for part in expected),
        "five order emails",
    )
    assert len([x for x in subjects if order_id in x]) == 5


def test_2_out_of_stock_race_is_compensated(platform: Platform, admin: User, manager: User) -> None:
    product = platform.product_with_stock(admin, stock=1)
    buyers = [platform.register_verified() for _ in range(4)]

    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(lambda u: platform.place_order(u, [(product, 1)]), buyers))

    placed = [
        (u, r.json()["id"]) for u, r in zip(buyers, responses, strict=True) if r.status_code == 201
    ]
    assert all(r.status_code in (201, 409) for r in responses)
    assert len(placed) >= 2, "expected several orders to pass the availability check"

    def settled() -> list[dict[str, object]] | None:
        orders = [platform.order(u, oid) for u, oid in placed]
        return orders if all(o["status"] in ("RESERVED", "CANCELLED") for o in orders) else None

    orders = wait_for(settled, "saga outcome for every order")
    statuses = sorted(str(o["status"]) for o in orders)
    assert statuses.count("RESERVED") == 1
    assert {o["cancel_reason"] for o in orders if o["status"] == "CANCELLED"} == {"OUT_OF_STOCK"}
    assert platform.stock(manager, product) == {
        "product_id": product,
        "on_hand": 1,
        "reserved": 1,
        "available": 0,
    }
    cancelled = next(
        (u, o) for (u, _), o in zip(placed, orders, strict=True) if o["status"] == "CANCELLED"
    )
    wait_for(lambda: platform.find_email(cancelled[0].email, "отменён"), "cancellation email")


def test_3_cancel_after_reservation_releases_stock(
    platform: Platform, admin: User, manager: User, buyer: User
) -> None:
    product = platform.product_with_stock(admin, stock=3)
    order_id = platform.place_order(buyer, [(product, 2)]).json()["id"]
    platform.wait_status(buyer, order_id, "RESERVED")
    assert platform.stock(manager, product)["reserved"] == 2

    cancelled = platform.action(buyer, order_id, "cancel")
    assert cancelled.json()["status"] == "CANCELLED"
    wait_for(lambda: platform.stock(manager, product)["reserved"] == 0, "reservation released")


def test_4_expired_reservation_cancels_order(
    platform: Platform, admin: User, manager: User, buyer: User
) -> None:
    product = platform.product_with_stock(admin, stock=2)
    order_id = platform.place_order(buyer, [(product, 1)]).json()["id"]
    reserved = platform.wait_status(buyer, order_id, "RESERVED")
    ttl = datetime.fromisoformat(reserved["reserved_until"]) - datetime.now(UTC)
    if ttl.total_seconds() > 60:
        pytest.skip("stack runs with the default reservation TTL; `make e2e` shortens it")

    expired = wait_until(
        lambda: platform.order(buyer, order_id),
        lambda order: order["status"] == "CANCELLED",
        "reservation expiry",
        timeout=ttl.total_seconds() + 30,
    )
    assert expired["cancel_reason"] == "RESERVATION_EXPIRED"
    assert platform.stock(manager, product)["reserved"] == 0
    assert platform.action(buyer, order_id, "pay").status_code == 409


def test_5_cancel_paid_order_refunds_and_releases(
    platform: Platform, admin: User, manager: User, buyer: User
) -> None:
    product = platform.product_with_stock(admin, stock=2)
    order_id = platform.place_order(buyer, [(product, 1)]).json()["id"]
    platform.wait_status(buyer, order_id, "RESERVED")
    assert platform.action(buyer, order_id, "pay").json()["status"] == "PAID"
    assert platform.action(buyer, order_id, "cancel").status_code == 403

    cancelled = platform.action(manager, order_id, "cancel", reason="нет в наличии на складе")
    assert cancelled.json()["status"] == "CANCELLED"
    assert cancelled.json()["cancel_reason"] == "нет в наличии на складе"
    wait_for(lambda: platform.stock(manager, product)["reserved"] == 0, "reservation released")


def test_6_order_survives_inventory_worker_outage(
    platform: Platform, admin: User, buyer: User
) -> None:
    product = platform.product_with_stock(admin, stock=2)
    compose("stop", "inventory-worker")
    try:
        order_id = platform.place_order(buyer, [(product, 1)]).json()["id"]
        time.sleep(3)
        assert platform.order(buyer, order_id)["status"] == "NEW"
    finally:
        compose("start", "inventory-worker")
    platform.wait_status(buyer, order_id, "RESERVED")


def test_7_idempotency(platform: Platform, admin: User, manager: User, buyer: User) -> None:
    product = platform.product_with_stock(admin, stock=5)
    key = f"e2e-{uuid.uuid4()}"
    first = platform.place_order(buyer, [(product, 1)], key=key)
    again = platform.place_order(buyer, [(product, 1)], key=key)
    assert (first.status_code, again.status_code) == (201, 200)
    assert first.json()["id"] == again.json()["id"]
    order_id = first.json()["id"]
    platform.wait_status(buyer, order_id, "RESERVED")

    redeliver_order_created(order_id)  # то же событие ещё раз в Kafka
    time.sleep(5)
    assert platform.stock(manager, product)["reserved"] == 1
    assert [h["to_status"] for h in platform.order(buyer, order_id)["history"]] == [
        "NEW",
        "RESERVED",
    ]


def test_8_access_rules(platform: Platform, admin: User, buyer: User) -> None:
    product = platform.product_with_stock(admin, stock=2)
    order_id = platform.place_order(buyer, [(product, 1)]).json()["id"]
    platform.wait_status(buyer, order_id, "RESERVED")

    stranger = platform.register_verified()
    assert platform.action(buyer, order_id, "ship").status_code == 403
    assert (
        platform.http.get(
            f"{platform_api()}/orders/{order_id}", headers=stranger.headers
        ).status_code
        == 404
    )
    anonymous = platform.http.post(
        f"{platform_api()}/orders",
        json={"items": [{"product_id": product, "quantity": 1}]},
        headers={"Idempotency-Key": "anonymous-key"},
    )
    assert anonymous.status_code == 401


# ---------- вспомогательное ----------


def platform_api() -> str:
    from .conftest import API

    return API


def redeliver_order_created(order_id: str) -> None:
    """Находит исходное сообщение order.created этого заказа и публикует его повторно."""
    consumer = Consumer(
        {"bootstrap.servers": KAFKA, "group.id": f"e2e-{uuid.uuid4()}", "enable.auto.commit": False}
    )
    try:
        metadata = consumer.list_topics("order.created", timeout=10)
        partitions = [
            TopicPartition("order.created", p, 0)
            for p in metadata.topics["order.created"].partitions
        ]
        consumer.assign(partitions)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            message = consumer.poll(1.0)
            if message is None or message.error():
                continue
            if message.key() == order_id.encode():
                producer = Producer({"bootstrap.servers": KAFKA})
                producer.produce(
                    "order.created",
                    key=message.key(),
                    value=message.value(),
                    headers=message.headers(),
                )
                assert producer.flush(10) == 0
                return
        raise AssertionError("original order.created message not found")
    finally:
        consumer.close()
