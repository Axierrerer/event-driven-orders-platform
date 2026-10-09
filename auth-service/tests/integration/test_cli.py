import pytest
from httpx import AsyncClient

from src import cli
from src.config import Settings, get_settings

pytestmark = pytest.mark.integration


@pytest.fixture
def cli_env(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", settings.database_url)
    monkeypatch.setenv("REDIS_URL", settings.redis_url)
    monkeypatch.setenv("JWT_PRIVATE_KEY_PATH", str(settings.jwt_private_key_path))
    get_settings.cache_clear()


async def test_create_user_is_idempotent_and_verified(
    client: AsyncClient, cli_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NEW_USER_PASSWORD", "admin strong passphrase")
    assert await cli.create_user("Admin@Example.com", verified=True) == 0
    assert await cli.create_user("admin@example.com", verified=True) == 0  # уже существует

    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "admin strong passphrase"},
    )
    assert response.status_code == 200


async def test_create_user_requires_password_env(
    cli_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("NEW_USER_PASSWORD", raising=False)
    assert await cli.create_user("admin@example.com", verified=True) == 2


async def test_create_user_rejects_weak_password(
    client: AsyncClient, cli_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NEW_USER_PASSWORD", "password123")
    assert await cli.create_user("admin@example.com", verified=True) == 2
