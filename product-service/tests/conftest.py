from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from typing import Any

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from testcontainers.community.redis import RedisContainer

from events import Role, uuid7
from platform_lib.testing import TokenFactory, mongo_replica_set
from src.config import Settings
from src.main import create_app


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
    return Settings(
        mongo_url=mongo_url,
        redis_url=redis_url,
        mongo_db=f"catalog_{uuid7().hex}",  # отдельная БД на тест
        grpc_port=0,  # свободный порт
    )


@pytest.fixture
async def client(settings: Settings, tokens: TokenFactory) -> AsyncIterator[AsyncClient]:
    redis = Redis.from_url(settings.redis_url)
    await redis.flushdb()
    await redis.aclose()
    app = create_app(settings, verifier=tokens.verifier)
    async with LifespanManager(app):  # создаёт индексы и gRPC-сервер
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            c.app = app  # type: ignore[attr-defined]
            yield c
        await app.state.database.client.drop_database(settings.mongo_db)


@pytest.fixture
def admin(tokens: TokenFactory) -> dict[str, str]:
    return tokens.headers(uuid7(), [Role.ADMIN])


@pytest.fixture
def manager(tokens: TokenFactory) -> dict[str, str]:
    return tokens.headers(uuid7(), [Role.MANAGER])


@pytest.fixture
def user(tokens: TokenFactory) -> dict[str, str]:
    return tokens.headers(uuid7(), [Role.USER])


CreateProduct = Callable[..., Awaitable[dict[str, Any]]]


@pytest.fixture
def create_product(client: AsyncClient, admin: dict[str, str]) -> CreateProduct:
    async def create(**overrides: Any) -> dict[str, Any]:
        body = {
            "sku": f"SKU-{uuid7().hex[-12:]}",
            "name": "Товар",
            "price": "100.00",
            "is_published": True,
            **overrides,
        }
        response = await client.post("/api/v1/products", json=body, headers=admin)
        assert response.status_code == 201, response.text
        return dict(response.json())

    return create
