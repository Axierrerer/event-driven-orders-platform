import os
from collections.abc import AsyncIterator, Iterable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from testcontainers.community.postgres import PostgresContainer

from events import Role, uuid7
from platform_lib.testing import TokenFactory
from src import db
from src.config import Settings
from src.main import create_app
from src.services.orders import OrderService
from src.services.payment import FakePaymentGateway
from src.services.ports import Availability, CatalogProduct, PaymentResult

SERVICE_DIR = Path(__file__).resolve().parents[1]
TABLES = ", ".join(
    [
        "order_items",
        "order_status_history",
        "idempotency_keys",
        "payments",
        "orders",
        "outbox",
        "processed_events",
    ]
)


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine", driver="asyncpg") as pg:
        url = pg.get_connection_url()
        os.environ["DATABASE_URL"] = url
        command.upgrade(Config(str(SERVICE_DIR / "alembic.ini")), "head")
        yield url


@pytest.fixture(scope="session")
def tokens() -> TokenFactory:
    return TokenFactory()


# ---------- фейки портов ----------


@dataclass
class FakeCatalog:
    products: dict[UUID, CatalogProduct] = field(default_factory=dict)
    fail: bool = False

    def add(
        self,
        price: str,
        *,
        name: str = "Товар",
        published: bool = True,
        currency: str = "RUB",
    ) -> UUID:
        product_id = uuid7()
        self.products[product_id] = CatalogProduct(
            product_id, name, Decimal(price), currency, published
        )
        return product_id

    async def get_products(self, product_ids: Iterable[UUID]) -> dict[UUID, CatalogProduct]:
        if self.fail:
            raise ConnectionError("catalog down")
        return {pid: self.products[pid] for pid in product_ids if pid in self.products}


@dataclass
class FakeInventory:
    stock: dict[UUID, int] = field(default_factory=dict)
    fail: bool = False

    async def check(self, items: dict[UUID, int]) -> Availability:
        if self.fail:
            raise TimeoutError("inventory timeout")
        details = [(pid, qty, self.stock.get(pid, 0)) for pid, qty in items.items()]
        return Availability(all(a >= q for _, q, a in details), details)


class RecordingPayments(FakePaymentGateway):
    def __init__(self) -> None:
        self.refunds: list[str] = []

    async def refund(self, provider_ref: str, amount: Decimal, currency: str) -> PaymentResult:
        self.refunds.append(provider_ref)
        return await super().refund(provider_ref, amount, currency)


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **delta: float) -> None:
        self.now += timedelta(**delta)


@dataclass
class World:
    client: AsyncClient
    catalog: FakeCatalog
    inventory: FakeInventory
    payments: RecordingPayments
    clock: Clock
    tokens: TokenFactory
    session_factory: async_sessionmaker[AsyncSession]

    @property
    def service(self) -> OrderService:
        service: OrderService = self.client.app.state.orders  # type: ignore[attr-defined]
        return service

    def headers(
        self,
        user_id: UUID,
        roles: Iterable[Role] = (Role.USER,),
        *,
        verified: bool = True,
        key: str | None = None,
    ) -> dict[str, str]:
        headers = self.tokens.headers(user_id, roles, email_verified=verified)
        if key is not None:
            headers["Idempotency-Key"] = key
        return headers

    async def place(
        self, user_id: UUID, items: list[tuple[UUID, int]], *, key: str | None = None
    ) -> Any:
        return await self.client.post(
            "/api/v1/orders",
            json={"items": [{"product_id": str(p), "quantity": q} for p, q in items]},
            headers=self.headers(user_id, key=key or f"key-{uuid7()}"),
        )

    async def outbox(self) -> list[dict[str, Any]]:
        async with self.session_factory() as session:
            rows = await session.execute(select(db.outbox).order_by(db.outbox.c.seq))
            return [dict(r._mapping) for r in rows]

    async def handle(self, handler: Any, event: Any) -> None:
        async with self.session_factory() as session, session.begin():
            await handler(event, session)


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(database_url)
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {TABLES} CASCADE"))
    yield engine
    await engine.dispose()


@pytest.fixture
async def world(
    database_url: str, engine: AsyncEngine, tokens: TokenFactory
) -> AsyncIterator[World]:
    catalog, inventory, payments, clock = (
        FakeCatalog(),
        FakeInventory(),
        RecordingPayments(),
        Clock(),
    )
    app = create_app(
        Settings(database_url=database_url),
        verifier=tokens.verifier,
        catalog=catalog,
        inventory=inventory,
        payments=payments,
    )
    app.state.orders._now = clock  # управляемое время в тестах
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        client.app = app  # type: ignore[attr-defined]
        yield World(
            client=client,
            catalog=catalog,
            inventory=inventory,
            payments=payments,
            clock=clock,
            tokens=tokens,
            session_factory=async_sessionmaker(engine, expire_on_commit=False),
        )
