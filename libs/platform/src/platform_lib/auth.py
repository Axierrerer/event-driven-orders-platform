"""Проверка JWT access-токенов (RS256) и зависимости FastAPI для авторизации.

Ключи берутся у auth-service по JWKS и кэшируются; при неизвестном `kid`
кэш принудительно обновляется (ротация ключей без простоя).
"""

import asyncio
import json
import time
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import Annotated, Any, Protocol
from uuid import UUID

import httpx
import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from events import Role

ISSUER = "auth-service"
AUDIENCE = "orders-platform"
ALGORITHM = "RS256"


@dataclass(frozen=True, slots=True)
class Principal:
    """Аутентифицированный пользователь из access-токена."""

    user_id: UUID
    roles: frozenset[Role]
    email_verified: bool
    token_id: str

    def has_any(self, roles: Iterable[Role]) -> bool:
        return bool(self.roles.intersection(roles))


class InvalidTokenError(Exception):
    pass


class KeyProvider(Protocol):
    async def get_key(self, kid: str) -> Any:
        """Публичный ключ по kid; None — ключ неизвестен."""
        ...


class StaticKeyProvider:
    """Ключи, известные заранее (auth-service проверяет свои же токены)."""

    def __init__(self, keys: dict[str, Any]) -> None:
        self._keys = keys

    async def get_key(self, kid: str) -> Any:
        return self._keys.get(kid)


class JwksKeyProvider:
    def __init__(
        self,
        jwks_url: str,
        *,
        cache_seconds: float = 600,
        min_refresh_interval_seconds: float = 10,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._url = jwks_url
        self._cache_seconds = cache_seconds
        self._min_refresh = min_refresh_interval_seconds
        self._client = client or httpx.AsyncClient(timeout=3.0)
        self._keys: dict[str, Any] = {}
        self._fetched_at = 0.0
        self._lock = asyncio.Lock()

    async def _refresh(self, *, force: bool) -> None:
        async with self._lock:
            age = time.monotonic() - self._fetched_at
            if (not force and age < self._cache_seconds) or (force and age < self._min_refresh):
                return
            response = await self._client.get(self._url)
            response.raise_for_status()
            self._keys = {
                jwk["kid"]: jwt.PyJWK.from_dict(jwk).key for jwk in response.json()["keys"]
            }
            self._fetched_at = time.monotonic()

    async def get_key(self, kid: str) -> Any:
        await self._refresh(force=False)
        if kid not in self._keys:
            await self._refresh(force=True)
        return self._keys.get(kid)


class JwtVerifier:
    def __init__(
        self, keys: KeyProvider, *, issuer: str = ISSUER, audience: str = AUDIENCE
    ) -> None:
        self._keys = keys
        self._issuer = issuer
        self._audience = audience

    async def verify(self, token: str) -> Principal:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise InvalidTokenError("malformed token") from exc
        if header.get("alg") != ALGORITHM or "kid" not in header:
            raise InvalidTokenError("unexpected token header")
        key = await self._keys.get_key(str(header["kid"]))
        if key is None:
            raise InvalidTokenError("unknown signing key")
        try:
            claims = jwt.decode(
                token,
                key,
                algorithms=[ALGORITHM],
                audience=self._audience,
                issuer=self._issuer,
                options={"require": ["exp", "iat", "sub", "jti"]},
            )
            return Principal(
                user_id=UUID(claims["sub"]),
                roles=frozenset(Role(r) for r in claims.get("roles", [])),
                email_verified=bool(claims.get("email_verified", False)),
                token_id=str(claims["jti"]),
            )
        except (jwt.PyJWTError, ValueError, KeyError) as exc:
            raise InvalidTokenError(str(exc)) from exc


def public_jwk(kid: str, public_key: Any) -> dict[str, Any]:
    """Публичный ключ в формате JWK (для /.well-known/jwks.json)."""
    jwk: dict[str, Any] = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(public_key))
    return {**jwk, "kid": kid, "use": "sig", "alg": ALGORITHM}


# ---------------- FastAPI ----------------

_bearer = HTTPBearer(auto_error=False)


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status.HTTP_401_UNAUTHORIZED, detail=detail, headers={"WWW-Authenticate": "Bearer"}
    )


def verifier_from_app(request: Request) -> JwtVerifier:
    verifier: JwtVerifier = request.app.state.jwt_verifier
    return verifier


async def current_principal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    verifier: Annotated[JwtVerifier, Depends(verifier_from_app)],
) -> Principal:
    """Требует валидный access-токен. Верификатор лежит в app.state.jwt_verifier."""
    if credentials is None:
        raise _unauthorized("missing bearer token")
    try:
        return await verifier.verify(credentials.credentials)
    except InvalidTokenError as exc:
        raise _unauthorized("invalid token") from exc


CurrentPrincipal = Annotated[Principal, Depends(current_principal)]


async def optional_principal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    verifier: Annotated[JwtVerifier, Depends(verifier_from_app)],
) -> Principal | None:
    """Для публичных эндпоинтов: без токена — аноним, с невалидным токеном — 401."""
    if credentials is None:
        return None
    try:
        return await verifier.verify(credentials.credentials)
    except InvalidTokenError as exc:
        raise _unauthorized("invalid token") from exc


OptionalPrincipal = Annotated[Principal | None, Depends(optional_principal)]


def require_roles(*roles: Role) -> Callable[[Principal], Awaitable[Principal]]:
    """Зависимость: пользователь должен иметь хотя бы одну из ролей."""

    async def dependency(principal: CurrentPrincipal) -> Principal:
        if not principal.has_any(roles):
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="insufficient role")
        return principal

    return dependency
