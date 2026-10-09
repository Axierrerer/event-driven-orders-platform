from functools import lru_cache
from pathlib import Path

from src.domain.errors import WeakPasswordError

MIN_PASSWORD_LENGTH = 10
MAX_PASSWORD_LENGTH = 128
_COMMON_PASSWORDS_FILE = Path(__file__).with_name("common_passwords.txt")


@lru_cache
def _common_passwords() -> frozenset[str]:
    lines = _COMMON_PASSWORDS_FILE.read_text().splitlines()
    return frozenset(
        line.strip().lower() for line in lines if line.strip() and not line.startswith("#")
    )


def validate_password(password: str, *, email: str | None = None) -> None:
    """Проверка стойкости пароля. Бросает WeakPasswordError с понятной причиной."""
    if len(password) < MIN_PASSWORD_LENGTH:
        raise WeakPasswordError(f"пароль короче {MIN_PASSWORD_LENGTH} символов")
    if len(password) > MAX_PASSWORD_LENGTH:
        raise WeakPasswordError(f"пароль длиннее {MAX_PASSWORD_LENGTH} символов")
    if password.lower() in _common_passwords():
        raise WeakPasswordError("пароль входит в список часто используемых")
    if email and password.lower() == email.lower():
        raise WeakPasswordError("пароль совпадает с email")
    if len(set(password)) < 4:
        raise WeakPasswordError("пароль состоит из слишком малого набора символов")


def normalize_email(email: str) -> str:
    return email.strip().lower()
