from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID


class ReservationStatus(StrEnum):
    ACTIVE = "ACTIVE"  # ждёт оплаты, истекает по TTL
    CONFIRMED = "CONFIRMED"  # заказ оплачен, не истекает
    RELEASED = "RELEASED"  # товар вернулся в доступный остаток
    COMMITTED = "COMMITTED"  # товар отгружен и списан


class MovementReason(StrEnum):
    RESERVE = "RESERVE"
    RELEASE = "RELEASE"
    SHIP = "SHIP"
    ADJUST = "ADJUST"


@dataclass(frozen=True, slots=True)
class StockLevel:
    product_id: UUID
    on_hand: int
    reserved: int

    @property
    def available(self) -> int:
        return self.on_hand - self.reserved


@dataclass(frozen=True, slots=True)
class Shortage:
    product_id: UUID
    requested: int
    available: int


def merge_quantities(items: Iterable[tuple[UUID, int]]) -> dict[UUID, int]:
    """Одинаковые товары в заказе объединяются; порядок — по product_id (против deadlock)."""
    totals: Counter[UUID] = Counter()
    for product_id, quantity in items:
        totals[product_id] += quantity
    return dict(sorted(totals.items(), key=lambda item: item[0]))


def find_shortages(
    requested: Mapping[UUID, int], stock: Mapping[UUID, StockLevel]
) -> tuple[list[UUID], list[Shortage]]:
    """Неизвестные товары и позиции, которых не хватает. Пусто в обоих — можно резервировать."""
    unknown = [product_id for product_id in requested if product_id not in stock]
    shortages = [
        Shortage(product_id, quantity, max(stock[product_id].available, 0))
        for product_id, quantity in requested.items()
        if product_id in stock and stock[product_id].available < quantity
    ]
    return unknown, shortages
