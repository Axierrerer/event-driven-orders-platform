"""Помощники для тестов сервисов: выпуск JWT, совместимых с auth-service."""

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

from events import Role, uuid7
from platform_lib.auth import ALGORITHM, AUDIENCE, ISSUER, JwtVerifier, StaticKeyProvider


class TokenFactory:
    """Подписывает access-токены тестовым ключом; `verifier` проверяет их в приложении."""

    KEY_ID = "test-key"

    def __init__(self) -> None:
        self._key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.verifier = JwtVerifier(StaticKeyProvider({self.KEY_ID: self._key.public_key()}))

    def token(
        self,
        user_id: UUID | None = None,
        roles: Iterable[Role] = (Role.USER,),
        *,
        email_verified: bool = True,
        ttl: timedelta = timedelta(minutes=15),
    ) -> str:
        now = datetime.now(UTC)
        claims = {
            "sub": str(user_id or uuid7()),
            "roles": sorted(str(r) for r in roles),
            "email_verified": email_verified,
            "iat": now,
            "exp": now + ttl,
            "iss": ISSUER,
            "aud": AUDIENCE,
            "jti": str(uuid7()),
        }
        return jwt.encode(claims, self._key, algorithm=ALGORITHM, headers={"kid": self.KEY_ID})

    def headers(
        self,
        user_id: UUID | None = None,
        roles: Iterable[Role] = (Role.USER,),
        *,
        email_verified: bool = True,
    ) -> dict[str, str]:
        token = self.token(user_id, roles, email_verified=email_verified)
        return {"Authorization": f"Bearer {token}"}
