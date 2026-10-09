import asyncio

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from platform_lib.health import HealthRegistry, health_router

pytestmark = pytest.mark.unit


def make_client(registry: HealthRegistry) -> AsyncClient:
    app = FastAPI()
    app.include_router(health_router(registry))
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_live_is_always_ok() -> None:
    async with make_client(HealthRegistry()) as client:
        response = await client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_ready_ok_when_all_checks_pass() -> None:
    registry = HealthRegistry()

    async def ok() -> None:
        return None

    registry.register("db", ok)
    async with make_client(registry) as client:
        response = await client.get("/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "checks": {"db": "ok"}}


async def test_ready_503_when_check_raises() -> None:
    registry = HealthRegistry()

    async def ok() -> None:
        return None

    async def broken() -> None:
        raise ConnectionError("db down")

    registry.register("db", broken)
    registry.register("redis", ok)
    async with make_client(registry) as client:
        response = await client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["checks"] == {"db": "fail", "redis": "ok"}


async def test_ready_503_when_check_times_out() -> None:
    registry = HealthRegistry(timeout_seconds=0.01)

    async def slow() -> None:
        await asyncio.sleep(1)

    registry.register("kafka", slow)
    async with make_client(registry) as client:
        response = await client.get("/health/ready")
    assert response.status_code == 503
