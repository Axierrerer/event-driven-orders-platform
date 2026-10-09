"""Контейнеры для интеграционных тестов (testcontainers, нужен Docker)."""

import time
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient
from redis.asyncio import Redis
from sqlalchemy import Column, Integer, MetaData, Table, Text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from testcontainers.community.kafka import KafkaContainer
from testcontainers.community.postgres import PostgresContainer
from testcontainers.community.redis import RedisContainer
from testcontainers.core.container import DockerContainer

from platform_lib.outbox import outbox_table, processed_events_table

# ---------------- PostgreSQL ----------------


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine", driver="asyncpg") as pg:
        yield pg.get_connection_url()


class PgSchema:
    def __init__(self) -> None:
        self.metadata = MetaData()
        self.outbox = outbox_table(self.metadata)
        self.processed = processed_events_table(self.metadata)
        self.accounts = Table(
            "accounts",
            self.metadata,
            Column("id", Integer, primary_key=True),
            Column("note", Text, nullable=False),
        )


@pytest.fixture
async def pg(postgres_url: str) -> AsyncIterator[tuple[AsyncEngine, PgSchema]]:
    engine = create_async_engine(postgres_url)
    schema = PgSchema()
    async with engine.begin() as conn:
        await conn.run_sync(schema.metadata.drop_all)
        await conn.run_sync(schema.metadata.create_all)
    yield engine, schema
    await engine.dispose()


@pytest.fixture
def session_factory(pg: tuple[AsyncEngine, PgSchema]) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(pg[0], expire_on_commit=False)


# ---------------- MongoDB (replica set из одного узла) ----------------


@pytest.fixture(scope="session")
def mongo_url() -> Iterator[str]:
    container = (
        DockerContainer("mongo:7")
        .with_command("--replSet rs0 --bind_ip_all")
        .with_exposed_ports(27017)
    )
    with container:
        host = container.get_container_host_ip()
        port = container.get_exposed_port(27017)
        url = f"mongodb://{host}:{port}/?directConnection=true"
        client: MongoClient[dict[str, Any]] = MongoClient(url, serverSelectionTimeoutMS=1000)
        deadline = time.monotonic() + 60
        while True:
            try:
                client.admin.command(
                    "replSetInitiate",
                    {"_id": "rs0", "members": [{"_id": 0, "host": "localhost:27017"}]},
                )
                break
            except Exception as exc:
                if "already initialized" in str(exc):
                    break
                if time.monotonic() > deadline:
                    raise
                time.sleep(0.5)
        while not client.admin.command("hello").get("isWritablePrimary"):
            if time.monotonic() > deadline:
                raise TimeoutError("MongoDB не стал primary")
            time.sleep(0.3)
        client.close()
        yield url


@pytest.fixture
async def mongo(mongo_url: str) -> AsyncIterator[Any]:
    client: Any = AsyncIOMotorClient(mongo_url, tz_aware=True)
    db = client[f"test_{time.time_ns()}"]
    yield client, db
    await client.drop_database(db.name)
    client.close()


# ---------------- Redis ----------------


@pytest.fixture(scope="session")
def redis_url() -> Iterator[str]:
    with RedisContainer("redis:7-alpine") as container:
        host = container.get_container_host_ip()
        port = container.get_exposed_port(6379)
        yield f"redis://{host}:{port}/0"


@pytest.fixture
async def redis(redis_url: str) -> AsyncIterator[Redis]:
    client = Redis.from_url(redis_url)
    await client.flushdb()
    yield client
    await client.aclose()


# ---------------- Kafka ----------------


@pytest.fixture(scope="session")
def kafka_bootstrap() -> Iterator[str]:
    with KafkaContainer("confluentinc/cp-kafka:7.7.1").with_kraft() as kafka:
        yield kafka.get_bootstrap_server()
