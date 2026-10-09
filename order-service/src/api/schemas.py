from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from events import Money, OrderStatus
from src.domain.models import MAX_ITEMS, MAX_QUANTITY, Order


class OrderItemIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: UUID
    quantity: int = Field(ge=1, le=MAX_QUANTITY)


class CreateOrderRequest(BaseModel):
    """Только товары и количества: цену назначает сервер по каталогу."""

    model_config = ConfigDict(extra="forbid")

    items: list[OrderItemIn] = Field(min_length=1, max_length=MAX_ITEMS)


class CancelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=500)


class OrderLineOut(BaseModel):
    product_id: UUID
    product_name: str
    unit_price: Money
    quantity: int
    line_total: Money


class StatusChangeOut(BaseModel):
    from_status: OrderStatus | None
    to_status: OrderStatus
    reason: str | None
    actor: str
    created_at: datetime


class OrderOut(BaseModel):
    id: UUID
    user_id: UUID
    status: OrderStatus
    total_amount: Money
    currency: str
    items: list[OrderLineOut]
    cancel_reason: str | None
    reserved_until: datetime | None
    created_at: datetime
    updated_at: datetime
    history: list[StatusChangeOut]

    @classmethod
    def of(cls, order: Order) -> "OrderOut":
        return cls(
            id=order.id,
            user_id=order.user_id,
            status=order.status,
            total_amount=order.total_amount,
            currency=order.currency,
            items=[
                OrderLineOut(
                    product_id=line.product_id,
                    product_name=line.product_name,
                    unit_price=line.unit_price,
                    quantity=line.quantity,
                    line_total=line.line_total,
                )
                for line in order.lines
            ],
            cancel_reason=order.cancel_reason,
            reserved_until=order.reserved_until,
            created_at=order.created_at,
            updated_at=order.updated_at,
            history=[
                StatusChangeOut(
                    from_status=change.from_status,
                    to_status=change.to_status,
                    reason=change.reason,
                    actor=change.actor,
                    created_at=change.created_at,
                )
                for change in order.history
            ],
        )
