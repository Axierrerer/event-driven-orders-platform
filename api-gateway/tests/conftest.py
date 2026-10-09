from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field
from typing import Any

import grpc
import httpx
import pytest
from asgi_lifespan import LifespanManager
from orders_proto.catalog.v1 import product_pb2, product_pb2_grpc
from redis.asyncio import Redis
from testcontainers.community.redis import RedisContainer

from platform_lib.testing import TokenFactory
from src.config import Settings
from src.main import create_app

PUBLISHED = "01a11f66-e72b-7620-8bb6-007ad63c9837"
HIDDEN = "01a11f66-e72b-7620-8bb6-007ad63c9838"


@pytest.fixture(scope="session")
def redis_url() -> Iterator[str]:
    with RedisContainer("redis:7-alpine") as container:
        yield f"redis://{container.get_container_host_ip()}:{container.get_exposed_port(6379)}/0"


@pytest.fixture(scope="session")
def tokens() -> TokenFactory:
    return TokenFactory()


class Catalog(product_pb2_grpc.ProductServiceServicer):
    def __init__(self) -> None:
        self.calls = 0

    async def GetProduct(self, request: Any, context: Any) -> Any:
        self.calls += 1
        if request.product_id not in (PUBLISHED, HIDDEN):
            await context.abort(grpc.StatusCode.NOT_FOUND, "not found")
        return product_pb2.Product(
            id=request.product_id,
            sku="SKU",
            name="Чайник",
            price="1490.00",
            currency="RUB",
            is_published=request.product_id == PUBLISHED,
            version=3,
            images=["https://cdn.test/t.png"],
            attributes_json='{"volume_l": 1}',
            created_at="2026-10-09T06:00:00+00:00",
            updated_at="2026-10-09T06:00:00+00:00",
        )


@dataclass
class Upstreams:
    """Фейковые сервисы: запоминают запросы, отвечают по таблице."""

    requests: list[httpx.Request] = field(default_factory=list)
    fail: dict[str, type[Exception]] = field(default_factory=dict)

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        host = request.url.host
        if host in self.fail:
            raise self.fail[host]("boom", request=request)
        if request.url.path == "/openapi.json":
            service = host.split("-")[0]
            return httpx.Response(
                200,
                json={
                    "paths": {f"/api/v1/{service}": {"get": {"summary": service}}},
                    "components": {"schemas": {}},
                },
            )
        return httpx.Response(
            200,
            json={"service": host, "path": request.url.path, "query": request.url.query.decode()},
            headers={"ETag": '"7"', "Content-Encoding": "identity", "Connection": "close"},
        )


@dataclass
class Env:
    client: httpx.AsyncClient
    upstreams: Upstreams
    catalog: Catalog
    tokens: TokenFactory


@pytest.fixture
async def grpc_catalog() -> AsyncIterator[tuple[Catalog, int]]:
    server = grpc.aio.server()
    catalog = Catalog()
    product_pb2_grpc.add_ProductServiceServicer_to_server(catalog, server)  # type: ignore[no-untyped-call]
    port = server.add_insecure_port("127.0.0.1:0")
    await server.start()
    yield catalog, port
    await server.stop(None)


async def make_env(
    redis_url: str,
    tokens: TokenFactory,
    grpc_catalog: tuple[Catalog, int],
    **overrides: Any,
) -> AsyncIterator[Env]:
    redis = Redis.from_url(redis_url)
    await redis.flushdb()
    await redis.aclose()
    upstreams = Upstreams()
    settings = Settings(
        redis_url=redis_url,
        product_grpc_target=f"127.0.0.1:{grpc_catalog[1]}",
        **overrides,
    )
    app = create_app(
        settings, verifier=tokens.verifier, transport=httpx.MockTransport(upstreams.handler)
    )
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app, client=("203.0.113.9", 5000))
        async with httpx.AsyncClient(transport=transport, base_url="http://gw") as client:
            yield Env(client, upstreams, grpc_catalog[0], tokens)


@pytest.fixture
async def env(
    redis_url: str, tokens: TokenFactory, grpc_catalog: tuple[Catalog, int]
) -> AsyncIterator[Env]:
    async for value in make_env(redis_url, tokens, grpc_catalog):
        yield value
