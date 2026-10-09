"""Служебные команды auth-service.

    python -m src.cli create-user --email admin@example.com --verified

Пароль читается из переменной окружения NEW_USER_PASSWORD (не из аргументов —
аргументы видны в списке процессов и истории shell).
"""

import argparse
import asyncio
import os
import sys

from src.domain.errors import EmailAlreadyRegisteredError, WeakPasswordError
from src.main import create_app
from src.services.auth import AuthService


async def create_user(email: str, verified: bool) -> int:
    password = os.environ.get("NEW_USER_PASSWORD")
    if not password:
        print("NEW_USER_PASSWORD is not set", file=sys.stderr)
        return 2
    app = create_app()
    service: AuthService = app.state.auth_service
    try:
        user_id = await service.create_user(email, password, verified=verified)
    except EmailAlreadyRegisteredError:
        print(f"user already exists: {email}")
        return 0
    except WeakPasswordError as exc:
        print(f"weak password: {exc}", file=sys.stderr)
        return 2
    print(f"user created: {user_id}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="auth-service cli")
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create-user", help="создать пользователя (идемпотентно)")
    create.add_argument("--email", required=True)
    create.add_argument("--verified", action="store_true", help="email сразу подтверждён")
    args = parser.parse_args(argv)
    return asyncio.run(create_user(args.email, args.verified))


if __name__ == "__main__":
    sys.exit(main())
