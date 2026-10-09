import os
from collections.abc import AsyncIterator, Callable, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy import insert, select, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from testcontainers.community.postgres import PostgresContainer
from testcontainers.community.redis import RedisContainer

from events import (
    OrderCreated,
    OrderCreatedPayload,
    OrderItem,
    OrderStatus,
    OrderStatusChanged,
    OrderStatusChangedPayload,
    uuid7,
)
from platform_lib.outbox import PgOutbox
from platform_lib.testing import TokenFactory
from src import db
from src.config import Settings
from src.main import create_app
from src.services.inventory import InventoryService

SERVICE_DIR = Path(__file__).resolve().parents[1]
TABLES = "reservation_items, reservations, stock_movements, stock, outbox, processed_events"


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine", driver="asyncpg") as pg:
        url = pg.get_connection_url()
        os.environ["DATABASE_URL"] = url
        command.upgrade(Config(str(SERVICE_DIR / "alembic.ini")), "head")
        yield url


@pytest.fixture(scope="session")
def redis_url() -> Iterator[str]:
    with RedisContainer("redis:7-alpine") as container:
        yield f"redis://{container.get_container_host_ip()}:{container.get_exposed_port(6379)}/0"


@pytest.fixture(scope="session")
def tokens() -> TokenFactory:
    return TokenFactory()


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(database_url, pool_size=25)
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {TABLES} CASCADE"))
    yield engine
    await engine.dispose()


@pytest.fixture
def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **delta: float) -> None:
        self.now += timedelta(**delta)


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def service(session_factory: async_sessionmaker[AsyncSession], clock: Clock) -> InventoryService:
    return InventoryService(
        session_factory, PgOutbox(db.outbox), reservation_ttl=timedelta(minutes=15), clock=clock
    )


@pytest.fixture
async def redis(redis_url: str) -> AsyncIterator[Redis]:
    client = Redis.from_url(redis_url)
    await client.flushdb()
    yield client
    await client.aclose()


@pytest.fixture
async def client(
    database_url: str, redis_url: str, engine: AsyncEngine, tokens: TokenFactory
) -> AsyncIterator[AsyncClient]:
    settings = Settings(database_url=database_url, redis_url=redis_url, grpc_port=0)
    app = create_app(settings, verifier=tokens.verifier)
    async with LifespanManager(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            c.app = app  # type: ignore[attr-defined]
            yield c


# ---------- данные ----------


async def put_stock(
    session_factory: async_sessionmaker[AsyncSession], product_id: UUID, on_hand: int
) -> None:
    async with session_factory() as session, session.begin():
        await session.execute(insert(db.stock).values(product_id=product_id, on_hand=on_hand))


async def stock_row(
    session_factory: async_sessionmaker[AsyncSession], product_id: UUID
) -> tuple[int, int]:
    async with session_factory() as session:
        row = (
            await session.execute(select(db.stock).where(db.stock.c.product_id == product_id))
        ).one()
    return row.on_hand, row.reserved


async def outbox(session_factory: async_sessionmaker[AsyncSession]) -> list[dict[str, Any]]:
    async with session_factory() as session:
        rows = await session.execute(select(db.outbox).order_by(db.outbox.c.seq))
        return [dict(r._mapping) for r in rows]


def order_created(items: list[tuple[UUID, int]], order_id: UUID | None = None) -> OrderCreated:
    order_id = order_id or uuid7()
    total = Decimal("1.00") * sum(q for _, q in items)
    return OrderCreated(
        producer="order-service",
        correlation_id=order_id,
        payload=OrderCreatedPayload(
            order_id=order_id,
            user_id=uuid7(),
            items=[
                OrderItem(product_id=p, quantity=q, unit_price=Decimal("1.00")) for p, q in items
            ],
            total_amount=total,
            currency="RUB",
        ),
    )


def status_changed(order_id: UUID, old: OrderStatus, new: OrderStatus) -> OrderStatusChanged:
    return OrderStatusChanged(
        producer="order-service",
        correlation_id=order_id,
        payload=OrderStatusChangedPayload(
            order_id=order_id,
            user_id=uuid7(),
            old_status=old,
            new_status=new,
            changed_at=datetime.now(UTC),
        ),
    )


Handle = Callable[..., Any]


@pytest.fixture
def handle(session_factory: async_sessionmaker[AsyncSession], service: InventoryService) -> Handle:
    """Выполняет обработчик события в отдельной транзакции, как consumer."""

    async def run(event: Any) -> None:
        handler = {
            "order.created": service.on_order_created,
            "order.status-changed": service.on_order_status_changed,
            "product.changed": service.on_product_changed,
        }[event.TOPIC]
        async with session_factory() as session, session.begin():
            await handler(event, session)

    return run
