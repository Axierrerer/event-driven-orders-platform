"""Помощники для тестов сервисов: выпуск JWT, совместимых с auth-service."""

import time
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
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


@contextmanager
def mongo_replica_set() -> Iterator[str]:
    """MongoDB 7 с replica set из одного узла в testcontainers (нужно для транзакций).

    testcontainers — dev-зависимость, поэтому импорт внутри функции.
    """
    from pymongo import MongoClient
    from testcontainers.core.container import DockerContainer

    container = (
        DockerContainer("mongo:7")
        .with_command("--replSet rs0 --bind_ip_all")
        .with_exposed_ports(27017)
    )
    with container:
        host = container.get_container_host_ip()
        port = container.get_exposed_port(27017)
        url = f"mongodb://{host}:{port}/?directConnection=true"
        client: MongoClient[dict[str, object]] = MongoClient(url, serverSelectionTimeoutMS=1000)
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
                raise TimeoutError("MongoDB did not become primary")
            time.sleep(0.3)
        client.close()
        yield url
