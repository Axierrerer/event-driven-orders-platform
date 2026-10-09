from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BeforeValidator,
    Field,
    PlainSerializer,
    WithJsonSchema,
)

_CENT = Decimal("0.01")


def _reject_float(value: object) -> object:
    if isinstance(value, float):
        raise ValueError("float запрещён для денежных сумм: передайте Decimal или строку")
    return value


def _money_to_str(value: Decimal) -> str:
    return str(value.quantize(_CENT))


Money = Annotated[
    Decimal,
    BeforeValidator(_reject_float),
    Field(ge=0, max_digits=12, decimal_places=2),
    PlainSerializer(_money_to_str, return_type=str, when_used="json"),
    WithJsonSchema(
        {"type": "string", "pattern": r"^\d{1,10}\.\d{2}$"},
        mode="serialization",
    ),
]
"""Денежная сумма: Decimal в коде, строка с двумя знаками («10.10») на проводе."""


def _to_utc(value: datetime) -> datetime:
    return value.astimezone(UTC)


UtcDateTime = Annotated[AwareDatetime, AfterValidator(_to_utc)]
"""Момент времени с часовым поясом; хранится и передаётся в UTC."""

Currency = Annotated[str, Field(pattern=r"^[A-Z]{3}$")]
"""Код валюты ISO 4217."""

PositiveQuantity = Annotated[int, Field(gt=0)]


class Role(StrEnum):
    USER = "ROLE_USER"
    MANAGER = "ROLE_MANAGER"
    ADMIN = "ROLE_ADMIN"


class AuthProvider(StrEnum):
    PASSWORD = "password"  # noqa: S105 — способ входа, не секрет
    GOOGLE = "google"
    GITHUB = "github"


class OrderStatus(StrEnum):
    NEW = "NEW"
    RESERVED = "RESERVED"
    PAID = "PAID"
    SHIPPED = "SHIPPED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ReservationFailureReason(StrEnum):
    OUT_OF_STOCK = "OUT_OF_STOCK"
    UNKNOWN_PRODUCT = "UNKNOWN_PRODUCT"
    ERROR = "ERROR"


class ReleaseReason(StrEnum):
    ORDER_CANCELLED = "ORDER_CANCELLED"
    EXPIRED = "EXPIRED"
