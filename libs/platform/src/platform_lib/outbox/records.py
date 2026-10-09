from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from events import BaseEvent


@dataclass(frozen=True, slots=True)
class OutboxRecord:
    """Событие, ожидающее публикации в Kafka. id совпадает с event_id."""

    id: UUID
    topic: str
    key: str
    event_type: str
    payload: dict[str, Any]
    headers: dict[str, str] = field(default_factory=dict)


def record_from_event(event: BaseEvent, headers: Mapping[str, str] | None = None) -> OutboxRecord:
    return OutboxRecord(
        id=event.event_id,
        topic=event.TOPIC,
        key=event.key(),
        event_type=event.event_type,
        payload=event.model_dump(mode="json"),
        headers={
            "event_type": event.event_type,
            "correlation_id": str(event.correlation_id),
            **(headers or {}),
        },
    )
