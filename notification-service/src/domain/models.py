from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class NotificationStatus(StrEnum):
    PENDING = "PENDING"  # ждёт отправки
    PENDING_CONTACT = "PENDING_CONTACT"  # email пользователя ещё неизвестен
    THROTTLED = "THROTTLED"  # отложено rate limit’ом, отправится позже
    RETRY = "RETRY"  # SMTP-ошибка, повтор с backoff
    SENT = "SENT"
    FAILED = "FAILED"


DUE_STATUSES = (
    NotificationStatus.PENDING,
    NotificationStatus.THROTTLED,
    NotificationStatus.RETRY,
)


class Bucket(StrEnum):
    USER = "user"  # обычные уведомления пользователя
    VERIFICATION = "verification"  # письма подтверждения email


class Notification(BaseModel):
    """Запись журнала. context нужен только до отправки и затем удаляется."""

    id: str  # = event_id: одно событие — одно уведомление
    user_id: UUID
    email: str | None
    template: str
    bucket: Bucket
    status: NotificationStatus
    attempts: int
    next_attempt_at: datetime
    last_error: str | None = None
    sent_at: datetime | None = None
    created_at: datetime
    context: dict[str, Any] | None = None


class EmailTemplate(BaseModel):
    key: str
    subject: str
    body_html: str
    body_text: str
    locale: str = "ru"


def order_status_template(status: str) -> str:
    return f"order_status_{status}"


def backoff_seconds(attempt: int) -> float:
    """Пауза перед повторной попыткой: 5, 10, 20, 40 с."""
    return float(5 * 2 ** (attempt - 1))
