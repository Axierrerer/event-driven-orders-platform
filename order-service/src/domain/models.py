import hashlib
import json
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from events import OrderStatus

CENT = Decimal("0.01")
MAX_ITEMS = 50
MAX_QUANTITY = 100


@dataclass(frozen=True, slots=True)
class OrderLine:
    product_id: UUID
    product_name: str
    unit_price: Decimal
    quantity: int

    @property
    def line_total(self) -> Decimal:
        return (self.unit_price * self.quantity).quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True, slots=True)
class StatusChange:
    from_status: OrderStatus | None
    to_status: OrderStatus
    reason: str | None
    actor: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class Order:
    id: UUID
    user_id: UUID
    status: OrderStatus
    total_amount: Decimal
    currency: str
    lines: tuple[OrderLine, ...]
    cancel_reason: str | None
    created_at: datetime
    updated_at: datetime
    reserved_until: datetime | None = None
    history: tuple[StatusChange, ...] = ()


def order_total(lines: Iterable[OrderLine]) -> Decimal:
    """Σ цена × количество в Decimal, округление ROUND_HALF_UP до копейки."""
    total = sum((line.unit_price * line.quantity for line in lines), Decimal("0"))
    return total.quantize(CENT, rounding=ROUND_HALF_UP)


def merge_items(items: Iterable[tuple[UUID, int]]) -> dict[UUID, int]:
    """Одинаковые товары объединяются; порядок сохраняется по первому вхождению."""
    merged: Counter[UUID] = Counter()
    for product_id, quantity in items:
        merged[product_id] += quantity
    return dict(merged)


def request_fingerprint(items: dict[UUID, int]) -> str:
    """Отпечаток тела запроса для Idempotency-Key: не зависит от порядка позиций."""
    canonical = json.dumps(sorted((str(pid), qty) for pid, qty in items.items()))
    return hashlib.sha256(canonical.encode()).hexdigest()
