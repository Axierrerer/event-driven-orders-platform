from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine

from events import AuthProvider, Role, UserCreated, UserCreatedPayload, uuid7
from platform_lib.testing import TokenFactory
from src import db

from ..conftest import ADMIN_EMAIL, CreateUser

pytestmark = pytest.mark.integration


async def outbox(engine: AsyncEngine) -> list[dict[str, Any]]:
    async with engine.connect() as conn:
        rows = await conn.execute(select(db.outbox).order_by(db.outbox.c.seq))
        return [dict(r._mapping) for r in rows]


async def make_admin(create_user: CreateUser) -> UUID:
    return await create_user(ADMIN_EMAIL)


# ---------- user.created ----------


async def test_user_created_makes_profile_with_user_role(
    client: AsyncClient, create_user: CreateUser, tokens: TokenFactory
) -> None:
    user_id = await create_user("Ann@Example.com")

    response = await client.get("/api/v1/users/me", headers=tokens.headers(user_id))
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(user_id)
    assert body["email"] == "Ann@example.com"  # домен нормализуется
    assert body["roles"] == ["ROLE_USER"]


async def test_redelivered_user_created_changes_nothing(
    create_user: CreateUser, engine: AsyncEngine
) -> None:
    user_id = uuid7()
    event = UserCreated(
        producer="auth-service",
        correlation_id=user_id,
        payload=UserCreatedPayload(
            user_id=user_id,
            email="dup@example.com",
            created_at=datetime.now(UTC),
            auth_provider=AuthProvider.PASSWORD,
        ),
    )
    await create_user(event=event)
    await create_user(event=event)

    async with engine.connect() as conn:
        assert await conn.scalar(select(func.count()).select_from(db.users)) == 1
        assert await conn.scalar(select(func.count()).select_from(db.user_roles)) == 1


async def test_bootstrap_admin_gets_admin_role_and_event(
    client: AsyncClient, create_user: CreateUser, tokens: TokenFactory, engine: AsyncEngine
) -> None:
    admin_id = await make_admin(create_user)

    me = (await client.get("/api/v1/users/me", headers=tokens.headers(admin_id))).json()
    assert me["roles"] == ["ROLE_ADMIN", "ROLE_USER"]
    events = await outbox(engine)
    assert [e["topic"] for e in events] == ["user.roles-changed"]
    assert events[0]["payload"]["payload"]["roles"] == ["ROLE_ADMIN", "ROLE_USER"]


# ---------- роли ----------


async def test_admin_changes_roles_and_publishes_event(
    client: AsyncClient, create_user: CreateUser, tokens: TokenFactory, engine: AsyncEngine
) -> None:
    admin_id = await make_admin(create_user)
    user_id = await create_user()

    response = await client.put(
        f"/api/v1/users/{user_id}/roles",
        json={"roles": ["ROLE_USER", "ROLE_MANAGER"]},
        headers=tokens.headers(admin_id, [Role.ADMIN]),
    )
    assert response.status_code == 200
    assert response.json()["roles"] == ["ROLE_MANAGER", "ROLE_USER"]

    event = (await outbox(engine))[-1]
    assert event["topic"] == "user.roles-changed"
    assert event["key"] == str(user_id)
    assert event["payload"]["payload"]["changed_by"] == str(admin_id)


@pytest.mark.parametrize("roles", [[Role.USER], [Role.MANAGER]])
async def test_only_admin_changes_roles(
    client: AsyncClient, create_user: CreateUser, tokens: TokenFactory, roles: list[Role]
) -> None:
    user_id = await create_user()
    response = await client.put(
        f"/api/v1/users/{user_id}/roles",
        json={"roles": ["ROLE_ADMIN"]},
        headers=tokens.headers(uuid7(), roles),
    )
    assert response.status_code == 403


async def test_last_admin_cannot_be_demoted(
    client: AsyncClient, create_user: CreateUser, tokens: TokenFactory
) -> None:
    admin_id = await make_admin(create_user)
    other_admin = await create_user()
    headers = tokens.headers(admin_id, [Role.ADMIN])
    await client.put(
        f"/api/v1/users/{other_admin}/roles", json={"roles": ["ROLE_ADMIN"]}, headers=headers
    )

    # Второй администратор снимает роль с первого — можно, админ остаётся
    response = await client.put(
        f"/api/v1/users/{admin_id}/roles",
        json={"roles": ["ROLE_USER"]},
        headers=tokens.headers(other_admin, [Role.ADMIN]),
    )
    assert response.status_code == 200

    # Последнего администратора понизить нельзя (делает это бывший админ с устаревшим токеном)
    response = await client.put(
        f"/api/v1/users/{other_admin}/roles", json={"roles": ["ROLE_USER"]}, headers=headers
    )
    assert response.status_code == 409


async def test_admin_cannot_demote_self(
    client: AsyncClient, create_user: CreateUser, tokens: TokenFactory
) -> None:
    admin_id = await make_admin(create_user)
    second = await create_user()
    headers = tokens.headers(admin_id, [Role.ADMIN])
    await client.put(
        f"/api/v1/users/{second}/roles", json={"roles": ["ROLE_ADMIN"]}, headers=headers
    )

    response = await client.put(
        f"/api/v1/users/{admin_id}/roles", json={"roles": ["ROLE_USER"]}, headers=headers
    )
    assert response.status_code == 409


@pytest.mark.parametrize("body", [{"roles": []}, {"roles": ["ROLE_ROOT"]}])
async def test_invalid_roles_rejected(
    client: AsyncClient, create_user: CreateUser, tokens: TokenFactory, body: dict[str, Any]
) -> None:
    admin_id = await make_admin(create_user)
    user_id = await create_user()
    response = await client.put(
        f"/api/v1/users/{user_id}/roles", json=body, headers=tokens.headers(admin_id, [Role.ADMIN])
    )
    assert response.status_code == 422


# ---------- доступ к профилям ----------


async def test_user_sees_own_profile_but_not_others(
    client: AsyncClient, create_user: CreateUser, tokens: TokenFactory
) -> None:
    me = await create_user()
    other = await create_user()
    headers = tokens.headers(me)

    assert (await client.get(f"/api/v1/users/{me}", headers=headers)).status_code == 200
    assert (await client.get(f"/api/v1/users/{other}", headers=headers)).status_code == 403
    assert (await client.get("/api/v1/users", headers=headers)).status_code == 403


async def test_staff_lists_and_filters_users(
    client: AsyncClient, create_user: CreateUser, tokens: TokenFactory
) -> None:
    await create_user("alice@shop.example.org")
    await create_user("bob@shop.example.org")
    await create_user("carol@other.example.org")
    headers = tokens.headers(uuid7(), [Role.MANAGER])

    all_users = (await client.get("/api/v1/users", headers=headers)).json()
    assert len(all_users) == 3
    filtered = (await client.get("/api/v1/users?email=SHOP.example", headers=headers)).json()
    assert sorted(u["email"] for u in filtered) == [
        "alice@shop.example.org",
        "bob@shop.example.org",
    ]
    page = (await client.get("/api/v1/users?limit=1&offset=1", headers=headers)).json()
    assert [u["email"] for u in page] == ["bob@shop.example.org"]
    wildcard = (await client.get("/api/v1/users?email=%25", headers=headers)).json()
    assert wildcard == []  # % экранируется, а не работает как шаблон


async def test_requests_without_token_rejected(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/users/me")).status_code == 401
    assert (await client.get("/api/v1/users")).status_code == 401


async def test_profile_missing_until_event_arrives(
    client: AsyncClient, tokens: TokenFactory
) -> None:
    assert (await client.get("/api/v1/users/me", headers=tokens.headers())).status_code == 404


# ---------- PATCH /me ----------


async def test_update_me_changes_profile_fields(
    client: AsyncClient, create_user: CreateUser, tokens: TokenFactory
) -> None:
    user_id = await create_user()
    headers = tokens.headers(user_id)
    body = {
        "full_name": "Анна Петрова",
        "phone": "+79991234567",
        "address": {"city": "Москва", "street": "Тверская, 1", "postal_code": "125009"},
    }
    response = await client.patch("/api/v1/users/me", json=body, headers=headers)
    assert response.status_code == 200
    profile = response.json()
    assert profile["full_name"] == "Анна Петрова"
    assert profile["phone"] == "+79991234567"
    assert profile["address"] == {
        "country": None,
        "city": "Москва",
        "street": "Тверская, 1",
        "postal_code": "125009",
    }

    cleared = await client.patch("/api/v1/users/me", json={"phone": None}, headers=headers)
    assert cleared.json()["phone"] is None
    assert cleared.json()["full_name"] == "Анна Петрова"  # не переданное поле не трогаем


@pytest.mark.parametrize(
    "body",
    [
        {"phone": "89991234567"},
        {"phone": "+0123456789"},
        {"email": "new@example.com"},
        {"roles": ["ROLE_ADMIN"]},
        {"address": {"planet": "Mars"}},
    ],
    ids=["no-plus", "leading-zero", "email", "roles", "unknown-address-field"],
)
async def test_update_me_rejects_invalid_or_forbidden_fields(
    client: AsyncClient, create_user: CreateUser, tokens: TokenFactory, body: dict[str, Any]
) -> None:
    user_id = await create_user()
    response = await client.patch("/api/v1/users/me", json=body, headers=tokens.headers(user_id))
    assert response.status_code == 422


# ---------- удаление ----------


async def test_soft_delete_hides_user_and_anonymizes(
    client: AsyncClient, create_user: CreateUser, tokens: TokenFactory, engine: AsyncEngine
) -> None:
    admin_id = await make_admin(create_user)
    user_id = await create_user("victim@example.com")
    admin = tokens.headers(admin_id, [Role.ADMIN])

    assert (await client.delete(f"/api/v1/users/{user_id}", headers=admin)).status_code == 204
    assert (await client.delete(f"/api/v1/users/{user_id}", headers=admin)).status_code == 404
    assert (await client.get(f"/api/v1/users/{user_id}", headers=admin)).status_code == 404
    listed = (await client.get("/api/v1/users", headers=admin)).json()
    assert str(user_id) not in [u["id"] for u in listed]

    async with engine.connect() as conn:
        row = (
            (await conn.execute(select(db.users).where(db.users.c.id == user_id))).mappings().one()
        )
    assert row["email"] == f"deleted+{user_id}@invalid"
    assert row["deleted_at"] is not None
    event = (await outbox(engine))[-1]
    assert event["topic"] == "user.roles-changed"
    assert event["payload"]["payload"]["roles"] == []


async def test_delete_requires_admin_and_protects_self(
    client: AsyncClient, create_user: CreateUser, tokens: TokenFactory
) -> None:
    admin_id = await make_admin(create_user)
    user_id = await create_user()

    manager = tokens.headers(uuid7(), [Role.MANAGER])
    assert (await client.delete(f"/api/v1/users/{user_id}", headers=manager)).status_code == 403
    admin = tokens.headers(admin_id, [Role.ADMIN])
    assert (await client.delete(f"/api/v1/users/{admin_id}", headers=admin)).status_code == 409
