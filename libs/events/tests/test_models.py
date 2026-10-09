import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest
from confluent_kafka.schema_registry import SchemaRegistryClient
from confluent_kafka.serialization import MessageField, SerializationContext
from pydantic import ValidationError

from events import (
    EVENTS_BY_TOPIC,
    TOPICS,
    BaseEvent,
    OrderCreated,
    OrderCreatedPayload,
    OrderItem,
    UserCreatedPayload,
    make_deserializer,
    make_serializer,
    schema_document,
    uuid7,
)
from events.schemas_cli import SCHEMAS_DIR

from .conftest import NOW, ORDER_ID, PRODUCT_ID, USER_ID, sample_events

pytestmark = pytest.mark.unit

EXPECTED_TOPICS = {
    "user.created",
    "user.verification-requested",
    "user.roles-changed",
    "product.changed",
    "order.created",
    "inventory.reserved",
    "inventory.reservation-failed",
    "inventory.released",
    "order.status-changed",
}


def test_every_topic_has_a_model() -> None:
    assert set(TOPICS) == EXPECTED_TOPICS
    assert set(EVENTS_BY_TOPIC) == EXPECTED_TOPICS
    assert {type(event).TOPIC for event in sample_events()} == EXPECTED_TOPICS


@pytest.mark.parametrize("event", sample_events(), ids=lambda e: type(e).TOPIC)
def test_round_trip_through_schema_registry_serde(event: BaseEvent) -> None:
    client = SchemaRegistryClient.new_client({"url": "mock://round-trip"})
    event_cls = type(event)
    ctx = SerializationContext(event_cls.TOPIC, MessageField.VALUE)

    data = make_serializer(event_cls, client, auto_register=True)(event, ctx)
    restored = make_deserializer(event_cls, client)(data, ctx)

    assert restored == event


@pytest.mark.parametrize("event", sample_events(), ids=lambda e: type(e).TOPIC)
def test_event_key_is_aggregate_id(event: BaseEvent) -> None:
    key_field = type(event).KEY_FIELD
    assert event.key() == str(getattr(event.payload, key_field))


@pytest.mark.parametrize("topic", sorted(EXPECTED_TOPICS))
def test_committed_schema_matches_model(topic: str) -> None:
    committed = json.loads((SCHEMAS_DIR / f"{topic}.json").read_text())
    assert committed == schema_document(EVENTS_BY_TOPIC[topic]), (
        "Схема устарела: выполните `make export-schemas`"
    )


def test_no_stale_schema_files() -> None:
    files = {p.stem for p in Path(SCHEMAS_DIR).glob("*.json")}
    assert files == EXPECTED_TOPICS


def _order_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "order_id": ORDER_ID,
        "user_id": USER_ID,
        "items": [{"product_id": PRODUCT_ID, "quantity": 3, "unit_price": "0.10"}],
        "total_amount": "0.30",
        "currency": "RUB",
    }
    payload.update(overrides)
    return payload


def test_money_is_decimal_and_serialized_as_string() -> None:
    payload = OrderCreatedPayload.model_validate(_order_payload())
    assert isinstance(payload.total_amount, Decimal)
    assert payload.items[0].unit_price * 3 == payload.total_amount

    dumped = payload.model_dump(mode="json")
    assert dumped["total_amount"] == "0.30"
    assert dumped["items"][0]["unit_price"] == "0.10"


def test_money_keeps_two_decimal_places_on_wire() -> None:
    item = OrderItem(product_id=PRODUCT_ID, quantity=1, unit_price=Decimal("10"))
    assert item.model_dump(mode="json")["unit_price"] == "10.00"


@pytest.mark.parametrize(
    "bad_amount",
    [0.3, -1, "0.001", "1e20", "abc"],
    ids=["float", "negative", "three-decimals", "too-many-digits", "not-a-number"],
)
def test_invalid_money_rejected(bad_amount: object) -> None:
    with pytest.raises(ValidationError):
        OrderCreatedPayload.model_validate(_order_payload(total_amount=bad_amount))


def test_naive_datetime_rejected() -> None:
    with pytest.raises(ValidationError):
        UserCreatedPayload(
            user_id=USER_ID,
            email="user@example.com",
            created_at=datetime(2026, 10, 9, 12, 0),  # noqa: DTZ001 — проверяем отказ
            auth_provider="password",
        )


def test_aware_datetime_normalized_to_utc() -> None:
    moscow = datetime.fromisoformat("2026-10-09T15:00:00+03:00")
    payload = UserCreatedPayload(
        user_id=USER_ID, email="user@example.com", created_at=moscow, auth_provider="password"
    )
    assert payload.created_at == NOW
    assert payload.created_at.utcoffset() is not None
    assert payload.model_dump(mode="json")["created_at"] == "2026-10-09T12:00:00Z"


def test_order_requires_at_least_one_item_with_positive_quantity() -> None:
    with pytest.raises(ValidationError):
        OrderCreatedPayload.model_validate(_order_payload(items=[]))
    with pytest.raises(ValidationError):
        OrderCreatedPayload.model_validate(
            _order_payload(items=[{"product_id": PRODUCT_ID, "quantity": 0, "unit_price": "1"}])
        )


def test_event_type_is_fixed_per_class() -> None:
    event = sample_events()[4]
    assert isinstance(event, OrderCreated)
    assert event.event_type == "order.created"
    with pytest.raises(ValidationError):
        OrderCreated.model_validate({**event.model_dump(), "event_type": "user.created"})


def test_consumer_ignores_unknown_fields_from_newer_producer() -> None:
    event = sample_events()[4]
    data = event.model_dump(mode="json")
    data["new_optional_field"] = "x"
    data["payload"]["another_new_field"] = 1
    assert OrderCreated.model_validate(data) == event


def test_events_are_immutable() -> None:
    event = sample_events()[0]
    with pytest.raises(ValidationError):
        event.producer = "other"  # type: ignore[misc]


def test_event_defaults() -> None:
    event = OrderCreated(
        producer="order-service",
        correlation_id=ORDER_ID,
        payload=OrderCreatedPayload.model_validate(_order_payload()),
    )
    assert event.event_version == 1
    assert event.occurred_at.utcoffset() is not None
    assert event.event_id.version == 7


def test_uuid7_is_strictly_increasing_and_unique() -> None:
    ids = [uuid7() for _ in range(10_000)]  # много значений в одной миллисекунде
    assert all(
        isinstance(i, UUID) and i.version == 7 and i.variant == "specified in RFC 4122" for i in ids
    )
    assert ids == sorted(ids)
    assert len(set(ids)) == len(ids)


def test_schema_is_closed_and_money_is_string() -> None:
    schema = schema_document(OrderCreated)
    assert schema["additionalProperties"] is False
    item_schema = schema["$defs"]["OrderItem"]
    assert item_schema["additionalProperties"] is False
    assert item_schema["properties"]["unit_price"]["type"] == "string"


def test_events_lib_has_no_platform_or_service_imports() -> None:
    src = Path(__file__).resolve().parents[1] / "src" / "events"
    forbidden = ("platform_lib", "from src", "import src")
    for path in src.rglob("*.py"):
        text = path.read_text()
        assert not any(name in text for name in forbidden), path
