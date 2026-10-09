import os
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from events import Role, uuid7
from platform_lib.auth import ALGORITHM, AUDIENCE, ISSUER, public_jwk


def load_private_key(path: Path, *, generate_if_missing: bool) -> rsa.RSAPrivateKey:
    """Загрузить RSA-ключ подписи. В локальном окружении — создать при первом запуске."""
    if not path.exists():
        if not generate_if_missing:
            raise FileNotFoundError(f"JWT private key not found: {path}")
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as file:
            file.write(pem)
    loaded = serialization.load_pem_private_key(path.read_bytes(), password=None)
    if not isinstance(loaded, rsa.RSAPrivateKey):
        raise TypeError("JWT key must be RSA")
    return loaded


class JwtIssuer:
    def __init__(self, private_key: rsa.RSAPrivateKey, key_id: str, ttl_seconds: int) -> None:
        self._key = private_key
        self.key_id = key_id
        self.ttl_seconds = ttl_seconds

    @property
    def public_key(self) -> Any:
        return self._key.public_key()

    def jwks(self) -> dict[str, list[dict[str, Any]]]:
        return {"keys": [public_jwk(self.key_id, self.public_key)]}

    def issue(
        self, user_id: UUID, roles: Iterable[Role], *, email_verified: bool, now: datetime | None
    ) -> str:
        issued_at = now or datetime.now(UTC)
        claims = {
            "sub": str(user_id),
            "roles": sorted(str(role) for role in roles),
            "email_verified": email_verified,
            "iat": issued_at,
            "exp": issued_at + timedelta(seconds=self.ttl_seconds),
            "iss": ISSUER,
            "aud": AUDIENCE,
            "jti": str(uuid7()),
        }
        return jwt.encode(claims, self._key, algorithm=ALGORITHM, headers={"kid": self.key_id})
