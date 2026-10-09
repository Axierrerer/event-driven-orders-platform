"""Модели событий Kafka. Меняются только обратно совместимо:
новые поля — с default, существующие не удаляются и не переименовываются."""

from typing import ClassVar, Literal
from uuid import UUID

from pydantic import EmailStr, Field

from events.base import BaseEvent, ContractModel
from events.types import (
    AuthProvider,
    Currency,
    Money,
    OrderStatus,
    PositiveQuantity,
    ReleaseReason,
    ReservationFailureReason,
    Role,
    UtcDateTime,
)

# ---------------- user ----------------


class UserCreatedPayload(ContractModel):
    user_id: UUID
    email: EmailStr
    created_at: UtcDateTime
    auth_provider: AuthProvider


class UserCreated(BaseEvent):
    TOPIC: ClassVar[str] = "user.created"
    KEY_FIELD: ClassVar[str] = "user_id"
    event_type: Literal["user.created"] = "user.created"
    payload: UserCreatedPayload


class UserVerificationRequestedPayload(ContractModel):
    user_id: UUID
    email: EmailStr
    verification_url: str = Field(min_length=1)
    expires_at: UtcDateTime


class UserVerificationRequested(BaseEvent):
    TOPIC: ClassVar[str] = "user.verification-requested"
    KEY_FIELD: ClassVar[str] = "user_id"
    event_type: Literal["user.verification-requested"] = "user.verification-requested"
    payload: UserVerificationRequestedPayload


class UserRolesChangedPayload(ContractModel):
    user_id: UUID
    roles: list[Role]
    changed_by: UUID


class UserRolesChanged(BaseEvent):
    TOPIC: ClassVar[str] = "user.roles-changed"
    KEY_FIELD: ClassVar[str] = "user_id"
    event_type: Literal["user.roles-changed"] = "user.roles-changed"
    payload: UserRolesChangedPayload


# ---------------- product ----------------


class ProductChangedPayload(ContractModel):
    product_id: UUID
    sku: str = Field(min_length=1)
    name: str = Field(min_length=1)
    price: Money
    currency: Currency
    is_published: bool
    is_deleted: bool


class ProductChanged(BaseEvent):
    TOPIC: ClassVar[str] = "product.changed"
    KEY_FIELD: ClassVar[str] = "product_id"
    event_type: Literal["product.changed"] = "product.changed"
    payload: ProductChangedPayload


# ---------------- order ----------------


class OrderItem(ContractModel):
    product_id: UUID
    quantity: PositiveQuantity
    unit_price: Money


class OrderCreatedPayload(ContractModel):
    order_id: UUID
    user_id: UUID
    items: list[OrderItem] = Field(min_length=1)
    total_amount: Money
    currency: Currency


class OrderCreated(BaseEvent):
    TOPIC: ClassVar[str] = "order.created"
    KEY_FIELD: ClassVar[str] = "order_id"
    event_type: Literal["order.created"] = "order.created"
    payload: OrderCreatedPayload


class OrderStatusChangedPayload(ContractModel):
    order_id: UUID
    user_id: UUID
    old_status: OrderStatus
    new_status: OrderStatus
    reason: str | None = None
    changed_at: UtcDateTime


class OrderStatusChanged(BaseEvent):
    TOPIC: ClassVar[str] = "order.status-changed"
    KEY_FIELD: ClassVar[str] = "order_id"
    event_type: Literal["order.status-changed"] = "order.status-changed"
    payload: OrderStatusChangedPayload


# ---------------- inventory ----------------


class ReservedItem(ContractModel):
    product_id: UUID
    quantity: PositiveQuantity


class InventoryReservedPayload(ContractModel):
    order_id: UUID
    reservation_id: UUID
    items: list[ReservedItem] = Field(min_length=1)
    expires_at: UtcDateTime


class InventoryReserved(BaseEvent):
    TOPIC: ClassVar[str] = "inventory.reserved"
    KEY_FIELD: ClassVar[str] = "order_id"
    event_type: Literal["inventory.reserved"] = "inventory.reserved"
    payload: InventoryReservedPayload


class MissingItem(ContractModel):
    product_id: UUID
    requested: PositiveQuantity
    available: int = Field(ge=0)


class InventoryReservationFailedPayload(ContractModel):
    order_id: UUID
    reason: ReservationFailureReason
    missing: list[MissingItem] = Field(default_factory=list)


class InventoryReservationFailed(BaseEvent):
    TOPIC: ClassVar[str] = "inventory.reservation-failed"
    KEY_FIELD: ClassVar[str] = "order_id"
    event_type: Literal["inventory.reservation-failed"] = "inventory.reservation-failed"
    payload: InventoryReservationFailedPayload


class InventoryReleasedPayload(ContractModel):
    order_id: UUID
    reservation_id: UUID
    reason: ReleaseReason


class InventoryReleased(BaseEvent):
    TOPIC: ClassVar[str] = "inventory.released"
    KEY_FIELD: ClassVar[str] = "order_id"
    event_type: Literal["inventory.released"] = "inventory.released"
    payload: InventoryReleasedPayload


# ---------------- реестр ----------------

ALL_EVENTS: tuple[type[BaseEvent], ...] = (
    UserCreated,
    UserVerificationRequested,
    UserRolesChanged,
    ProductChanged,
    OrderCreated,
    OrderStatusChanged,
    InventoryReserved,
    InventoryReservationFailed,
    InventoryReleased,
)

EVENTS_BY_TOPIC: dict[str, type[BaseEvent]] = {cls.TOPIC: cls for cls in ALL_EVENTS}
TOPICS: tuple[str, ...] = tuple(EVENTS_BY_TOPIC)


def dlq_topic(topic: str) -> str:
    """Топик для сообщений, которые не удалось обработать."""
    return f"{topic}.dlq"
