import os
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from testcontainers.community.postgres import PostgresContainer

from events import AuthProvider, UserCreated, UserCreatedPayload, uuid7
from platform_lib.testing import TokenFactory
from src.config import Settings
from src.main import create_app
from src.services.users import UserService

SERVICE_DIR = Path(__file__).resolve().parents[1]
ADMIN_EMAIL = "root@example.com"


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


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(database_url)
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE user_roles, users, outbox, processed_events CASCADE"))
    yield engine
    await engine.dispose()


@pytest.fixture
async def client(
    database_url: str, engine: AsyncEngine, tokens: TokenFactory
) -> AsyncIterator[AsyncClient]:
    settings = Settings(database_url=database_url, bootstrap_admin_email=ADMIN_EMAIL)
    app = create_app(settings, verifier=tokens.verifier)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        c.app = app  # type: ignore[attr-defined]
        yield c


CreateUser = Callable[..., Awaitable[UUID]]


@pytest.fixture
def create_user(client: AsyncClient) -> CreateUser:
    """Имитирует доставку user.created в consumer user-service."""
    service: UserService = client.app.state.user_service  # type: ignore[attr-defined]

    async def create(email: str | None = None, event: UserCreated | None = None) -> UUID:
        if event is None:
            user_id = uuid7()
            event = UserCreated(
                producer="auth-service",
                correlation_id=user_id,
                payload=UserCreatedPayload(
                    user_id=user_id,
                    email=email or f"user-{user_id}@example.com",
                    created_at=datetime.now(UTC),
                    auth_provider=AuthProvider.PASSWORD,
                ),
            )
        async with service._session_factory() as session, session.begin():
            await service.on_user_created(event, session)
        return event.payload.user_id

    return create
