import hashlib
import secrets


def generate_opaque_token() -> str:
    """Случайный непрозрачный токен (256 бит), безопасный для URL."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """В БД хранится только SHA-256: утечка таблицы не даёт рабочих токенов."""
    return hashlib.sha256(token.encode()).hexdigest()
