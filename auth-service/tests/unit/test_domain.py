from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

from events import Role
from platform_lib.auth import JwtVerifier, StaticKeyProvider
from src.domain.errors import WeakPasswordError
from src.domain.passwords import normalize_email, validate_password
from src.domain.tokens import generate_opaque_token, hash_token
from src.services.jwt_issuer import JwtIssuer, load_private_key

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("password", "reason"),
    [
        ("short1!", "короче"),
        ("x" * 129, "длиннее"),
        ("password123", "часто используемых"),
        ("QWERTYUIOP", "часто используемых"),
        ("aaaaaaaaaaab", "малого набора"),
    ],
)
def test_weak_passwords_rejected(password: str, reason: str) -> None:
    with pytest.raises(WeakPasswordError, match=reason):
        validate_password(password)


def test_password_equal_to_email_rejected() -> None:
    with pytest.raises(WeakPasswordError, match="email"):
        validate_password("User@Example.com", email="user@example.com")


def test_strong_password_accepted() -> None:
    validate_password("correct horse battery staple", email="user@example.com")


def test_email_normalized() -> None:
    assert normalize_email("  User@Example.COM ") == "user@example.com"


def test_opaque_tokens_are_random_and_hash_is_stable() -> None:
    tokens = {generate_opaque_token() for _ in range(100)}
    assert len(tokens) == 100
    token = next(iter(tokens))
    assert len(token) >= 43  # 256 бит в base64url
    assert hash_token(token) == hash_token(token)
    assert hash_token(token) != token


def test_key_generated_once_with_private_permissions(tmp_path: Path) -> None:
    path = tmp_path / "keys" / "jwt.pem"
    first = load_private_key(path, generate_if_missing=True)
    second = load_private_key(path, generate_if_missing=True)
    assert first.private_numbers() == second.private_numbers()
    assert path.stat().st_mode & 0o777 == 0o600


def test_missing_key_outside_local_env_fails(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_private_key(tmp_path / "absent.pem", generate_if_missing=False)


async def test_issued_token_verifies_and_contains_claims(tmp_path: Path) -> None:
    key = load_private_key(tmp_path / "jwt.pem", generate_if_missing=True)
    issuer = JwtIssuer(key, "kid-1", ttl_seconds=900)
    user_id = UUID("0192f0a0-0000-7000-8000-000000000001")
    token = issuer.issue(user_id, {Role.USER}, email_verified=False, now=datetime.now(UTC))

    principal = await JwtVerifier(StaticKeyProvider({"kid-1": issuer.public_key})).verify(token)
    assert principal.user_id == user_id
    assert principal.roles == {Role.USER}
    assert principal.email_verified is False
    assert issuer.jwks()["keys"][0]["kid"] == "kid-1"
