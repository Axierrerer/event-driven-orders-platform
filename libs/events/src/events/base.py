from datetime import UTC, datetime
from typing import Any, ClassVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from events.ids import uuid7
from events.types import UtcDateTime


class ContractModel(BaseModel):
    """База всех моделей контракта.

    - frozen: событие — неизменяемый факт;
    - extra="ignore": consumer на старой версии читает события от более нового producer;
    - additionalProperties=false в JSON Schema: закрытая модель, для которой Schema Registry
      считает добавление необязательного поля совместимым (BACKWARD), а удаление — нет.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="ignore",
        json_schema_extra={"additionalProperties": False},
    )


class BaseEvent(ContractModel):
    """Конверт события. Подклассы задают TOPIC, KEY_FIELD, event_type и payload."""

    TOPIC: ClassVar[str]
    KEY_FIELD: ClassVar[str]

    event_id: UUID = Field(default_factory=uuid7)
    event_type: str
    event_version: int = Field(default=1, ge=1)
    occurred_at: UtcDateTime = Field(default_factory=lambda: datetime.now(UTC))
    producer: str = Field(min_length=1)
    correlation_id: UUID
    payload: ContractModel

    def key(self) -> str:
        """Ключ сообщения Kafka — id агрегата: события одного агрегата идут по порядку."""
        return str(getattr(self.payload, self.KEY_FIELD))


def schema_document(event_cls: type[BaseEvent]) -> dict[str, Any]:
    """JSON Schema события в том виде, в котором её видит Schema Registry."""
    schema = event_cls.model_json_schema(mode="serialization")
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", **schema}
