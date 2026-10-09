from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from testcontainers.community.redis import RedisContainer

from events import (
    AuthProvider,
    BaseEvent,
    OrderCreated,
    OrderCreatedPayload,
    OrderItem,
    OrderStatus,
    OrderStatusChanged,
    OrderStatusChangedPayload,
    UserCreated,
    UserCreatedPayload,
    UserVerificationRequested,
    UserVerificationRequestedPayload,
    uuid7,
)
from platform_lib.consumer import IdempotentConsumer, MongoInbox, RetryPolicy
from platform_lib.testing import TokenFactory, mongo_replica_set
from src import db
from src.config import Settings
from src.main import build_service, create_app, prepare_database
from src.services.email import FakeEmailSender
from src.services.notifications import NotificationService


@pytest.fixture(scope="session")
def mongo_url() -> Iterator[str]:
    with mongo_replica_set() as url:
        yield url


@pytest.fixture(scope="session")
def redis_url() -> Iterator[str]:
    with RedisContainer("redis:7-alpine") as container:
        yield f"redis://{container.get_container_host_ip()}:{container.get_exposed_port(6379)}/0"


@pytest.fixture(scope="session")
def tokens() -> TokenFactory:
    return TokenFactory()


@pytest.fixture
def settings(mongo_url: str, redis_url: str) -> Settings:
    return Settings(mongo_url=mongo_url, redis_url=redis_url, mongo_db=f"n_{uuid7().hex}")


class Clock:
    def __init__(self) -> None:
        self.now = datetime.now(UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **delta: float) -> None:
        self.now += timedelta(**delta)


class Message:
    def __init__(self, topic: str) -> None:
        self._topic = topic

    def topic(self) -> str:
        return self._topic

    def key(self) -> bytes:
        return b""

    def value(self) -> bytes:
        return b""

    def headers(self) -> None:
        return None

    def partition(self) -> int:
        return 0

    def offset(self) -> int:
        return 0


class NoDlq:
    async def send(self, message: object, error: str) -> None:
        raise AssertionError(f"unexpected DLQ: {error}")


@dataclass
class World:
    service: NotificationService
    sender: FakeEmailSender
    database: Any
    client: Any
    clock: Clock
    redis: Redis

    async def deliver(self, event: BaseEvent) -> None:
        """Доставка события через настоящий идемпотентный consumer (транзакция MongoDB)."""
        consumer = IdempotentConsumer(
            group_id="notification-service",
            inbox=MongoInbox(self.client, self.database.processed_events),
            decoder=lambda _m: event,
            dead_letters=NoDlq(),
            retry=RetryPolicy(delays_seconds=()),
        )
        handlers = {
            "user.created": self.service.on_user_created,
            "user.verification-requested": self.service.on_verification_requested,
            "order.created": self.service.on_order_created,
            "order.status-changed": self.service.on_order_status_changed,
        }
        consumer.handler(event.TOPIC)(handlers[event.TOPIC])
        await consumer.process(Message(event.TOPIC))

    async def journal(self, **query: Any) -> list[dict[str, Any]]:
        return await self.database.notifications.find(query).sort("created_at", 1).to_list(None)


@pytest.fixture
async def world(settings: Settings) -> AsyncIterator[World]:
    client = db.make_client(settings.mongo_url)
    database = client[settings.mongo_db]
    redis = Redis.from_url(settings.redis_url)
    await redis.flushdb()
    await prepare_database(database)
    sender = FakeEmailSender()
    clock = Clock()
    service = build_service(settings, database, redis, sender)
    service._now = clock
    yield World(service, sender, database, client, clock, redis)
    await client.drop_database(settings.mongo_db)
    client.close()
    await redis.aclose()


@pytest.fixture
async def api(settings: Settings, tokens: TokenFactory) -> AsyncIterator[AsyncClient]:
    app = create_app(settings, verifier=tokens.verifier)
    async with LifespanManager(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c


# ---------- события ----------


def user_created(user_id: UUID, email: str = "buyer@example.com") -> UserCreated:
    return UserCreated(
        producer="auth-service",
        correlation_id=user_id,
        payload=UserCreatedPayload(
            user_id=user_id,
            email=email,
            created_at=datetime.now(UTC),
            auth_provider=AuthProvider.PASSWORD,
        ),
    )


def verification(user_id: UUID, url: str = "https://shop.test/verify-email?token=t0k") -> Any:
    return UserVerificationRequested(
        producer="auth-service",
        correlation_id=user_id,
        payload=UserVerificationRequestedPayload(
            user_id=user_id,
            email="buyer@example.com",
            verification_url=url,
            expires_at=datetime(2026, 10, 10, 12, 0, tzinfo=UTC),
        ),
    )


def order_created(user_id: UUID) -> OrderCreated:
    order_id = uuid7()
    return OrderCreated(
        producer="order-service",
        correlation_id=order_id,
        payload=OrderCreatedPayload(
            order_id=order_id,
            user_id=user_id,
            items=[OrderItem(product_id=uuid7(), quantity=2, unit_price=Decimal("1490.00"))],
            total_amount=Decimal("2980.00"),
            currency="RUB",
        ),
    )


def status_changed(
    user_id: UUID,
    new: OrderStatus,
    old: OrderStatus = OrderStatus.RESERVED,
    *,
    reason: str | None = None,
) -> OrderStatusChanged:
    order_id = uuid7()
    return OrderStatusChanged(
        producer="order-service",
        correlation_id=order_id,
        payload=OrderStatusChangedPayload(
            order_id=order_id,
            user_id=user_id,
            old_status=old,
            new_status=new,
            reason=reason,
            changed_at=datetime.now(UTC),
        ),
    )
