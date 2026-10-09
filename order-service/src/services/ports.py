"""Порты к внешним зависимостям: сервис работает с ними, не зная о gRPC и платёжке."""

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class CatalogProduct:
    product_id: UUID
    name: str
    price: Decimal
    currency: str
    is_published: bool


@dataclass(frozen=True, slots=True)
class Availability:
    available: bool
    items: list[tuple[UUID, int, int]]  # (product_id, requested, available)


class CatalogPort(Protocol):
    async def get_products(self, product_ids: Iterable[UUID]) -> dict[UUID, CatalogProduct]:
        """Товары по id; неизвестных в результате нет. Ошибка связи — исключение."""
        ...


class InventoryPort(Protocol):
    async def check(self, items: dict[UUID, int]) -> Availability:
        """Проверка наличия без резервирования. Ошибка связи или таймаут — исключение."""
        ...


@dataclass(frozen=True, slots=True)
class PaymentResult:
    success: bool
    provider_ref: str
    error: str | None = None


class PaymentGateway(Protocol):
    async def charge(self, order_id: UUID, amount: Decimal, currency: str) -> PaymentResult: ...

    async def refund(self, provider_ref: str, amount: Decimal, currency: str) -> PaymentResult: ...
