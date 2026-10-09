"""Проверки на настоящем Schema Registry (по умолчанию — локальный стенд `make dev-up`)."""

import copy
import json
import os
from collections.abc import Iterator
from typing import Any

import pytest
from confluent_kafka.schema_registry import Schema, SchemaRegistryClient
from confluent_kafka.schema_registry.error import SchemaRegistryError

from events import EVENTS_BY_TOPIC, OrderCreated, schema_document, subject_name, uuid7
from events.schemas_cli import compat, register

pytestmark = pytest.mark.integration

REGISTRY_URL = os.environ.get("SCHEMA_REGISTRY_URL", "http://localhost:8081")


@pytest.fixture(scope="module")
def client() -> SchemaRegistryClient:
    registry = SchemaRegistryClient({"url": REGISTRY_URL})
    try:
        registry.get_subjects()
    except Exception as exc:  # реестр недоступен — стенд не поднят
        pytest.skip(f"Schema Registry недоступен по {REGISTRY_URL}: {exc}")
    return registry


@pytest.fixture
def temp_subject(client: SchemaRegistryClient) -> Iterator[str]:
    subject = f"test-{uuid7()}-value"
    yield subject
    try:
        client.delete_subject(subject, permanent=False)
        client.delete_subject(subject, permanent=True)
    except SchemaRegistryError:
        pass


def _as_schema(document: dict[str, Any]) -> Schema:
    return Schema(json.dumps(document), "JSON")


def _register_v1(client: SchemaRegistryClient, subject: str) -> dict[str, Any]:
    document = schema_document(OrderCreated)
    client.set_compatibility(subject, "BACKWARD")
    client.register_schema(subject, _as_schema(document))
    return document


def test_register_all_schemas_is_idempotent(client: SchemaRegistryClient) -> None:
    register(client)
    versions_before = {topic: client.get_versions(subject_name(topic)) for topic in EVENTS_BY_TOPIC}

    register(client)

    for topic in EVENTS_BY_TOPIC:
        assert client.get_versions(subject_name(topic)) == versions_before[topic]
        assert client.get_compatibility(subject_name(topic)) == "BACKWARD"


def test_current_models_compatible_with_registry(client: SchemaRegistryClient) -> None:
    register(client)
    assert compat(client) == 0


def test_adding_optional_field_is_backward_compatible(
    client: SchemaRegistryClient, temp_subject: str
) -> None:
    document = copy.deepcopy(_register_v1(client, temp_subject))
    document["properties"]["new_optional_field"] = {"type": "string"}

    assert client.test_compatibility(temp_subject, _as_schema(document)) is True


def test_removing_field_is_rejected(client: SchemaRegistryClient, temp_subject: str) -> None:
    document = copy.deepcopy(_register_v1(client, temp_subject))
    del document["properties"]["producer"]
    document["required"].remove("producer")

    assert client.test_compatibility(temp_subject, _as_schema(document)) is False


def test_changing_field_type_is_rejected(client: SchemaRegistryClient, temp_subject: str) -> None:
    document = copy.deepcopy(_register_v1(client, temp_subject))
    document["properties"]["event_version"] = {"type": "string"}

    assert client.test_compatibility(temp_subject, _as_schema(document)) is False
