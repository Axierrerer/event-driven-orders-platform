from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from events import Role
from platform_lib.auth import (
    AUDIENCE,
    ISSUER,
    CurrentPrincipal,
    InvalidTokenError,
    JwksKeyProvider,
    JwtVerifier,
    Principal,
    StaticKeyProvider,
    public_jwk,
    require_roles,
)

pytestmark = pytest.mark.unit

USER_ID = UUID("0192f0a0-0000-7000-8000-000000000001")
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def make_token(
    *,
    key: Any = KEY,
    kid: str = "k1",
    roles: list[str] | None = None,
    expires_in: timedelta = timedelta(minutes=15),
    **overrides: Any,
) -> str:
    now = datetime.now(UTC)
    claims = {
        "sub": str(USER_ID),
        "roles": roles if roles is not None else ["ROLE_USER"],
        "email_verified": True,
        "iat": now,
        "exp": now + expires_in,
        "iss": ISSUER,
        "aud": AUDIENCE,
        "jti": "token-1",
        **overrides,
    }
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": kid})


def verifier() -> JwtVerifier:
    return JwtVerifier(StaticKeyProvider({"k1": KEY.public_key()}))


async def test_valid_token_gives_principal() -> None:
    principal = await verifier().verify(make_token(roles=["ROLE_USER", "ROLE_MANAGER"]))
    assert principal == Principal(
        user_id=USER_ID,
        roles=frozenset({Role.USER, Role.MANAGER}),
        email_verified=True,
        token_id="token-1",
    )


@pytest.mark.parametrize(
    "token",
    [
        make_token(expires_in=timedelta(seconds=-1)),
        make_token(aud="other-audience"),
        make_token(iss="evil-issuer"),
        make_token(kid="unknown"),
        make_token(key=OTHER_KEY),
        make_token(roles=["ROLE_ROOT"]),
        "not-a-jwt",
    ],
    ids=["expired", "audience", "issuer", "unknown-kid", "wrong-key", "bad-role", "garbage"],
)
async def test_invalid_tokens_rejected(token: str) -> None:
    with pytest.raises(InvalidTokenError):
        await verifier().verify(token)


async def test_tampered_payload_rejected() -> None:
    header, _payload, signature = make_token().split(".")
    forged = jwt.encode({"sub": str(USER_ID), "roles": ["ROLE_ADMIN"]}, "x", algorithm="HS256")
    with pytest.raises(InvalidTokenError):
        await verifier().verify(f"{header}.{forged.split('.')[1]}.{signature}")


async def test_hs256_with_public_key_rejected() -> None:
    """Атака подмены алгоритма: HMAC-подпись публичным ключом не принимается."""
    token = jwt.encode(
        {"sub": str(USER_ID), "roles": ["ROLE_ADMIN"]},
        "public-key-as-secret",
        algorithm="HS256",
        headers={"kid": "k1"},
    )
    with pytest.raises(InvalidTokenError):
        await verifier().verify(token)


async def test_jwks_provider_caches_and_refreshes_on_new_kid() -> None:
    jwks = {"keys": [public_jwk("k1", KEY.public_key())]}
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=jwks)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = JwksKeyProvider("http://auth/jwks", client=client, min_refresh_interval_seconds=0)
    v = JwtVerifier(provider)

    await v.verify(make_token())
    await v.verify(make_token())
    assert calls == 1  # ключ из кэша

    jwks["keys"].append(public_jwk("k2", OTHER_KEY.public_key()))  # ротация ключа
    await v.verify(make_token(key=OTHER_KEY, kid="k2"))
    assert calls == 2


def make_app() -> FastAPI:
    app = FastAPI()
    app.state.jwt_verifier = verifier()

    @app.get("/me")
    async def me(principal: CurrentPrincipal) -> dict[str, str]:
        return {"user_id": str(principal.user_id)}

    @app.get("/admin", dependencies=[Depends(require_roles(Role.ADMIN))])
    async def admin() -> dict[str, str]:
        return {"ok": "yes"}

    return app


async def test_fastapi_dependencies() -> None:
    async with AsyncClient(transport=ASGITransport(app=make_app()), base_url="http://t") as c:
        assert (await c.get("/me")).status_code == 401
        assert (await c.get("/me", headers={"Authorization": "Bearer bad"})).status_code == 401
        user = {"Authorization": f"Bearer {make_token()}"}
        assert (await c.get("/me", headers=user)).json() == {"user_id": str(USER_ID)}
        assert (await c.get("/admin", headers=user)).status_code == 403
        admin = {"Authorization": f"Bearer {make_token(roles=['ROLE_ADMIN'])}"}
        assert (await c.get("/admin", headers=admin)).status_code == 200
