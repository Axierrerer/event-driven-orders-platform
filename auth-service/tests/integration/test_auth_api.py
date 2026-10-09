from typing import Any
from urllib.parse import parse_qs, urlparse
from uuid import UUID

import jwt
import pytest
from httpx import AsyncClient
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncEngine

from events import Role, UserRolesChanged, UserRolesChangedPayload, uuid7
from src import db
from src.services.roles_projection import apply_roles_changed

pytestmark = pytest.mark.integration

EMAIL = "User@Example.com"
PASSWORD = "correct horse battery staple"


async def register(client: AsyncClient, email: str = EMAIL, password: str = PASSWORD) -> UUID:
    response = await client.post(
        "/api/v1/auth/register", json={"email": email, "password": password}
    )
    assert response.status_code == 201, response.text
    return UUID(response.json()["user_id"])


async def login(client: AsyncClient, email: str = EMAIL, password: str = PASSWORD) -> Any:
    return await client.post("/api/v1/auth/login", json={"email": email, "password": password})


async def outbox_events(engine: AsyncEngine) -> list[dict[str, Any]]:
    async with engine.connect() as conn:
        rows = await conn.execute(select(db.outbox).order_by(db.outbox.c.seq))
        return [dict(row._mapping) for row in rows]


async def verification_token(engine: AsyncEngine) -> str:
    events = [e for e in await outbox_events(engine) if e["topic"] == "user.verification-requested"]
    url = events[-1]["payload"]["payload"]["verification_url"]
    return parse_qs(urlparse(url).query)["token"][0]


def claims(token: str) -> dict[str, Any]:
    return jwt.decode(token, options={"verify_signature": False})


# ---------- регистрация ----------


async def test_register_creates_user_role_and_events_atomically(
    client: AsyncClient, engine: AsyncEngine
) -> None:
    user_id = await register(client)

    async with engine.connect() as conn:
        user = (await conn.execute(select(db.users))).mappings().one()
        roles = (await conn.execute(select(db.user_roles.c.role))).scalars().all()
    assert user["id"] == user_id
    assert user["email"] == "user@example.com"
    assert user["password_hash"].startswith("$argon2id$")
    assert PASSWORD not in user["password_hash"]
    assert roles == [Role.USER]

    events = await outbox_events(engine)
    assert [e["topic"] for e in events] == ["user.created", "user.verification-requested"]
    assert events[0]["payload"]["payload"]["user_id"] == str(user_id)
    assert events[1]["payload"]["payload"]["verification_url"].startswith(
        "https://shop.test/verify-email?token="
    )


async def test_duplicate_email_in_any_case_conflicts(client: AsyncClient) -> None:
    await register(client)
    response = await client.post(
        "/api/v1/auth/register", json={"email": "USER@example.COM", "password": PASSWORD}
    )
    assert response.status_code == 409


@pytest.mark.parametrize("password", ["short", "password123"])
async def test_weak_password_rejected(client: AsyncClient, password: str) -> None:
    response = await client.post(
        "/api/v1/auth/register", json={"email": EMAIL, "password": password}
    )
    assert response.status_code == 422


# ---------- вход и токены ----------


async def test_login_returns_verifiable_access_token(client: AsyncClient) -> None:
    user_id = await register(client)
    response = await login(client)
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 900

    jwks = (await client.get("/api/v1/auth/.well-known/jwks.json")).json()
    key = jwt.PyJWK.from_dict(jwks["keys"][0]).key
    token_claims = jwt.decode(
        body["access_token"],
        key,
        algorithms=["RS256"],
        audience="orders-platform",
        issuer="auth-service",
    )
    assert token_claims["sub"] == str(user_id)
    assert token_claims["roles"] == ["ROLE_USER"]
    assert token_claims["email_verified"] is False
    assert token_claims["exp"] - token_claims["iat"] == 900


async def test_unknown_email_and_wrong_password_look_the_same(client: AsyncClient) -> None:
    await register(client)
    wrong_password = await login(client, password="wrong password value")
    unknown_email = await login(client, email="nobody@example.com")
    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json() == unknown_email.json()


async def test_sixth_failed_login_is_throttled(client: AsyncClient) -> None:
    await register(client)
    for _ in range(5):
        assert (await login(client, password="wrong password value")).status_code == 401
    throttled = await login(client)  # даже с верным паролем
    assert throttled.status_code == 429
    assert int(throttled.headers["Retry-After"]) > 0


async def test_successful_login_resets_failure_counter(client: AsyncClient) -> None:
    await register(client)
    for _ in range(4):
        await login(client, password="wrong password value")
    assert (await login(client)).status_code == 200
    for _ in range(4):
        await login(client, password="wrong password value")
    assert (await login(client)).status_code == 200


async def test_refresh_rotates_tokens(client: AsyncClient) -> None:
    await register(client)
    first = (await login(client)).json()

    response = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]}
    )
    assert response.status_code == 200
    second = response.json()
    assert second["refresh_token"] != first["refresh_token"]
    assert claims(second["access_token"])["jti"] != claims(first["access_token"])["jti"]


async def test_refresh_reuse_revokes_whole_family(client: AsyncClient) -> None:
    await register(client)
    first = (await login(client)).json()
    second = (
        await client.post("/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]})
    ).json()

    reuse = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]}
    )
    assert reuse.status_code == 401
    after = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": second["refresh_token"]}
    )
    assert after.status_code == 401  # семейство отозвано


async def test_expired_refresh_rejected(client: AsyncClient, engine: AsyncEngine) -> None:
    await register(client)
    tokens = (await login(client)).json()
    async with engine.begin() as conn:
        await conn.execute(
            update(db.refresh_tokens).values(expires_at=text("now() - interval '1 second'"))
        )
    response = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert response.status_code == 401


async def test_unknown_refresh_rejected(client: AsyncClient) -> None:
    response = await client.post("/api/v1/auth/refresh", json={"refresh_token": "nope"})
    assert response.status_code == 401


async def test_logout_revokes_family(client: AsyncClient) -> None:
    await register(client)
    tokens = (await login(client)).json()
    assert (
        await client.post("/api/v1/auth/logout", json={"refresh_token": tokens["refresh_token"]})
    ).status_code == 204
    response = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert response.status_code == 401


# ---------- подтверждение email ----------


async def test_verify_email_once(client: AsyncClient, engine: AsyncEngine) -> None:
    await register(client)
    token = await verification_token(engine)

    first = await client.post("/api/v1/auth/verify-email", json={"token": token})
    second = await client.post("/api/v1/auth/verify-email", json={"token": token})
    assert first.status_code == 204
    assert second.status_code == 400

    access = (await login(client)).json()["access_token"]
    assert claims(access)["email_verified"] is True


async def test_verify_email_with_bad_token(client: AsyncClient) -> None:
    response = await client.post("/api/v1/auth/verify-email", json={"token": "bogus"})
    assert response.status_code == 400


async def test_resend_verification_never_reveals_email(
    client: AsyncClient, engine: AsyncEngine
) -> None:
    await register(client)
    old_token = await verification_token(engine)

    known = await client.post("/api/v1/auth/resend-verification", json={"email": EMAIL})
    unknown = await client.post(
        "/api/v1/auth/resend-verification", json={"email": "nobody@example.com"}
    )
    assert known.status_code == unknown.status_code == 202
    assert known.json() == unknown.json()

    new_token = await verification_token(engine)
    assert new_token != old_token
    assert (
        await client.post("/api/v1/auth/verify-email", json={"token": old_token})
    ).status_code == 400
    assert (
        await client.post("/api/v1/auth/verify-email", json={"token": new_token})
    ).status_code == 204


# ---------- смена пароля ----------


async def test_change_password_revokes_refresh_tokens(client: AsyncClient) -> None:
    await register(client)
    tokens = (await login(client)).json()
    auth = {"Authorization": f"Bearer {tokens['access_token']}"}
    new_password = "another strong passphrase"

    response = await client.post(
        "/api/v1/auth/password",
        json={"old_password": PASSWORD, "new_password": new_password},
        headers=auth,
    )
    assert response.status_code == 204
    assert (
        await client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    ).status_code == 401
    assert (await login(client)).status_code == 401
    assert (await login(client, password=new_password)).status_code == 200


async def test_change_password_requires_token_and_old_password(client: AsyncClient) -> None:
    await register(client)
    tokens = (await login(client)).json()
    body = {"old_password": "wrong password value", "new_password": "another strong passphrase"}
    assert (await client.post("/api/v1/auth/password", json=body)).status_code == 401
    response = await client.post(
        "/api/v1/auth/password",
        json=body,
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    assert response.status_code == 401


# ---------- проекция ролей ----------


async def test_roles_changed_event_updates_next_token(
    client: AsyncClient, engine: AsyncEngine
) -> None:
    user_id = await register(client)
    event = UserRolesChanged(
        producer="user-service",
        correlation_id=user_id,
        payload=UserRolesChangedPayload(
            user_id=user_id, roles=[Role.USER, Role.MANAGER], changed_by=uuid7()
        ),
    )
    session_factory = client.app.state.auth_service._session_factory  # type: ignore[attr-defined]
    for _ in range(2):  # повтор события не меняет результат
        async with session_factory() as session, session.begin():
            await apply_roles_changed(event, session)

    access = (await login(client)).json()["access_token"]
    assert claims(access)["roles"] == ["ROLE_MANAGER", "ROLE_USER"]


# ---------- секреты не утекают ----------


async def test_no_secrets_in_logs_or_responses(
    client: AsyncClient, engine: AsyncEngine, capsys: pytest.CaptureFixture[str]
) -> None:
    await register(client)
    await login(client, password="wrong password value")
    tokens = (await login(client)).json()
    await client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})

    output = capsys.readouterr().out
    for secret in (PASSWORD, "wrong password value", tokens["refresh_token"]):
        assert secret not in output

    async with engine.connect() as conn:
        stored = (await conn.execute(select(db.refresh_tokens.c.token_hash))).scalars().all()
    assert tokens["refresh_token"] not in stored
