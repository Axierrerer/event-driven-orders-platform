from decimal import Decimal
from typing import Any

import pytest

from events import ProductChanged, ProductChangedPayload, uuid7
from platform_lib.consumer import IdempotentConsumer, MongoInbox, RetryPolicy
from platform_lib.outbox import MongoOutbox, MongoOutboxRelay, ensure_outbox_indexes

from ..fakes import FakeDeadLetters, FakeMessage, FakePublisher, no_sleep

pytestmark = pytest.mark.integration


def make_event() -> ProductChanged:
    product_id = uuid7()
    return ProductChanged(
        producer="product-service",
        correlation_id=product_id,
        payload=ProductChangedPayload(
            product_id=product_id,
            sku=f"SKU-{product_id}",
            name="Кружка",
            price=Decimal("10.10"),
            currency="RUB",
            is_published=True,
            is_deleted=False,
        ),
    )


async def test_outbox_written_in_transaction_with_document(mongo: Any) -> None:
    client, db = mongo
    await ensure_outbox_indexes(db.outbox)
    event = make_event()

    async with await client.start_session() as session, session.start_transaction():
        await db.products.insert_one({"_id": str(event.payload.product_id)}, session=session)
        await MongoOutbox(db.outbox).add(event, session=session)

    doc = await db.outbox.find_one({"_id": str(event.event_id)})
    assert doc is not None
    assert doc["topic"] == "product.changed"
    assert doc["published_at"] is None
    assert doc["payload"]["payload"]["price"] == "10.10"


async def test_aborted_transaction_leaves_no_outbox(mongo: Any) -> None:
    client, db = mongo
    await db.create_collection("outbox")
    await db.create_collection("products")

    with pytest.raises(RuntimeError):
        async with await client.start_session() as session, session.start_transaction():
            await db.products.insert_one({"_id": "p1"}, session=session)
            await MongoOutbox(db.outbox).add(make_event(), session=session)
            raise RuntimeError("бизнес-ошибка")

    assert await db.outbox.count_documents({}) == 0
    assert await db.products.count_documents({}) == 0


async def test_relay_publishes_and_only_lease_holder_works(mongo: Any) -> None:
    client, db = mongo
    events = [make_event() for _ in range(3)]
    async with await client.start_session() as session, session.start_transaction():
        for event in events:
            await MongoOutbox(db.outbox).add(event, session=session)

    publisher = FakePublisher()
    leader = MongoOutboxRelay(db.outbox, db.leases, publisher, owner_id="replica-a")
    follower = MongoOutboxRelay(db.outbox, db.leases, publisher, owner_id="replica-b")

    assert await leader.run_once() == 3
    assert await follower.run_once() == 0  # аренда у replica-a
    assert [r.id for r in publisher.published] == [e.event_id for e in events]
    assert await db.outbox.count_documents({"published_at": None}) == 0


async def test_relay_marks_failures(mongo: Any) -> None:
    client, db = mongo
    event = make_event()
    async with await client.start_session() as session, session.start_transaction():
        await MongoOutbox(db.outbox).add(event, session=session)

    publisher = FakePublisher(fail_ids={event.event_id})
    relay = MongoOutboxRelay(db.outbox, db.leases, publisher, owner_id="replica-a")
    assert await relay.run_once() == 0

    doc = await db.outbox.find_one({"_id": str(event.event_id)})
    assert doc["published_at"] is None
    assert doc["attempts"] == 1


async def test_mongo_inbox_deduplicates_and_rolls_back(mongo: Any) -> None:
    client, db = mongo
    await db.create_collection("processed_events")
    await db.create_collection("notifications")
    event = make_event()
    dlq = FakeDeadLetters()
    consumer = IdempotentConsumer(
        group_id="notification-service",
        inbox=MongoInbox(client, db.processed_events),
        decoder=lambda _msg: event,
        dead_letters=dlq,
        retry=RetryPolicy(delays_seconds=(0.0,)),
        sleep=no_sleep,
    )
    fail = True

    @consumer.handler("product.changed")
    async def handle(_event: ProductChanged, session: Any) -> None:
        await db.notifications.insert_one({"n": 1}, session=session)
        if fail:
            raise ConnectionError("smtp down")

    await consumer.process(FakeMessage("product.changed"))
    assert await db.notifications.count_documents({}) == 0
    assert await db.processed_events.count_documents({}) == 0
    assert len(dlq.sent) == 1

    fail = False
    await consumer.process(FakeMessage("product.changed"))
    await consumer.process(FakeMessage("product.changed"))  # повторная доставка
    assert await db.notifications.count_documents({}) == 1
    assert await db.processed_events.count_documents({}) == 1
