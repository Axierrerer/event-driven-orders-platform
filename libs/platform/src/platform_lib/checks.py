"""Готовые проверки зависимостей для HealthRegistry."""

import asyncio
from typing import Any

from confluent_kafka.admin import AdminClient
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from platform_lib.health import HealthCheck


def postgres_check(engine: AsyncEngine) -> HealthCheck:
    async def check() -> None:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))

    return check


def redis_check(redis: Redis) -> HealthCheck:
    async def check() -> None:
        await redis.ping()

    return check


def mongo_check(client: Any) -> HealthCheck:
    async def check() -> None:
        await client.admin.command("ping")

    return check


def kafka_check(bootstrap: str, timeout_seconds: float = 1.5) -> HealthCheck:
    admin = AdminClient({"bootstrap.servers": bootstrap})

    async def check() -> None:
        await asyncio.to_thread(admin.list_topics, timeout=timeout_seconds)

    return check
