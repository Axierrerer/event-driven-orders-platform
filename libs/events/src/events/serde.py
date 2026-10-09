"""Сериализация событий через Confluent Schema Registry (JSON Schema)."""

import json

from confluent_kafka.schema_registry import SchemaRegistryClient
from confluent_kafka.schema_registry.json_schema import JSONDeserializer, JSONSerializer
from confluent_kafka.serialization import SerializationContext

from events.base import BaseEvent, schema_document


def subject_name(topic: str) -> str:
    """TopicNameStrategy: схема значения топика хранится в subject `<topic>-value`."""
    return f"{topic}-value"


def make_serializer(
    event_cls: type[BaseEvent],
    client: SchemaRegistryClient,
    *,
    auto_register: bool = False,
) -> JSONSerializer:
    """Сериализатор события. По умолчанию схема должна быть заранее зарегистрирована
    (`register` в events.schemas_cli): producer не может тихо опубликовать новую схему."""

    def to_dict(event: object, _ctx: SerializationContext | None) -> dict[str, object]:
        if not isinstance(event, event_cls):
            raise TypeError(f"Ожидалось {event_cls.__name__}, получено {type(event).__name__}")
        return event.model_dump(mode="json")

    serializer: JSONSerializer = JSONSerializer(
        json.dumps(schema_document(event_cls)),
        client,
        to_dict=to_dict,
        conf={"auto.register.schemas": auto_register, "normalize.schemas": True},
    )
    return serializer


def make_deserializer(event_cls: type[BaseEvent], client: SchemaRegistryClient) -> JSONDeserializer:
    """Десериализатор: проверяет данные схемой writer’а из реестра и строит модель."""

    def from_dict(data: dict[str, object], _ctx: SerializationContext | None) -> BaseEvent:
        return event_cls.model_validate(data)

    deserializer: JSONDeserializer = JSONDeserializer(
        None, from_dict=from_dict, schema_registry_client=client
    )
    return deserializer
