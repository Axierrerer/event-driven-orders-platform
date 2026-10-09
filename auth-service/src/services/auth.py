"""Сценарии аутентификации. Каждый публичный метод — одна транзакция БД."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from pwdlib import PasswordHash
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from events import (
    AuthProvider,
    Role,
    UserCreated,
    UserCreatedPayload,
    UserVerificationRequested,
    UserVerificationRequestedPayload,
    uuid7,
)
from platform_lib.logging import get_logger
from platform_lib.outbox import PgOutbox
from src.domain.errors import (
    EmailAlreadyRegisteredError,
    InvalidCredentialsError,
    InvalidTokenError,
    TooManyAttemptsError,
)
from src.domain.passwords import normalize_email, validate_password
from src.domain.tokens import generate_opaque_token, hash_token
from src.repositories.tokens import RefreshTokenRepository, VerificationTokenRepository
from src.repositories.users import UserRecord, UserRepository
from src.services.jwt_issuer import JwtIssuer
from src.services.login_limiter import LoginAttemptLimiter

log = get_logger(__name__)

SERVICE_NAME = "auth-service"
DEFAULT_ROLES = frozenset({Role.USER})


@dataclass(frozen=True, slots=True)
class TokenPair:
    access_token: str
    refresh_token: str
    expires_in: int
    token_type: str = "bearer"  # noqa: S105 — тип токена по RFC 6750, не секрет


@dataclass(frozen=True)
class AuthConfig:
    refresh_token_ttl: timedelta
    email_verification_ttl: timedelta
    app_base_url: str


class AuthService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        outbox: PgOutbox,
        password_hasher: PasswordHash,
        issuer: JwtIssuer,
        limiter: LoginAttemptLimiter,
        config: AuthConfig,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._session_factory = session_factory
        self._outbox = outbox
        self._hasher = password_hasher
        self._issuer = issuer
        self._limiter = limiter
        self._config = config
        self._now = clock
        # Хеш-заглушка: вход с неизвестным email занимает столько же времени, сколько с известным
        self._dummy_hash = password_hasher.hash(generate_opaque_token())

    # ---------- хеширование паролей (CPU-bound, вне event loop) ----------

    async def _hash(self, password: str) -> str:
        return await asyncio.to_thread(self._hasher.hash, password)

    async def _verify(self, password: str, password_hash: str | None) -> bool:
        return await asyncio.to_thread(
            self._hasher.verify, password, password_hash or self._dummy_hash
        )

    # ---------- регистрация и подтверждение email ----------

    async def register(self, email: str, password: str) -> UUID:
        email = normalize_email(email)
        validate_password(password, email=email)
        password_hash = await self._hash(password)
        user_id = uuid7()
        now = self._now()

        try:
            async with self._session_factory() as session, session.begin():
                users = UserRepository(session)
                if await users.email_exists(email):
                    raise EmailAlreadyRegisteredError(email)
                await users.create(user_id, email, password_hash)
                await users.replace_roles(user_id, DEFAULT_ROLES)
                await self._outbox.add(
                    session,
                    UserCreated(
                        producer=SERVICE_NAME,
                        correlation_id=user_id,
                        payload=UserCreatedPayload(
                            user_id=user_id,
                            email=email,
                            created_at=now,
                            auth_provider=AuthProvider.PASSWORD,
                        ),
                    ),
                )
                await self._request_verification(session, user_id, email, now)
        except IntegrityError as exc:  # параллельная регистрация того же email
            raise EmailAlreadyRegisteredError(email) from exc

        log.info("user_registered", user_id=str(user_id))
        return user_id

    async def _request_verification(
        self, session: AsyncSession, user_id: UUID, email: str, now: datetime
    ) -> None:
        token = generate_opaque_token()
        expires_at = now + self._config.email_verification_ttl
        await VerificationTokenRepository(session).create(
            uuid7(), user_id, hash_token(token), expires_at
        )
        await self._outbox.add(
            session,
            UserVerificationRequested(
                producer=SERVICE_NAME,
                correlation_id=user_id,
                payload=UserVerificationRequestedPayload(
                    user_id=user_id,
                    email=email,
                    verification_url=f"{self._config.app_base_url}/verify-email?token={token}",
                    expires_at=expires_at,
                ),
            ),
        )

    async def verify_email(self, token: str) -> None:
        now = self._now()
        async with self._session_factory() as session, session.begin():
            tokens = VerificationTokenRepository(session)
            record = await tokens.get_for_update(hash_token(token))
            if record is None or record.used_at is not None or record.expires_at <= now:
                raise InvalidTokenError("verification token is invalid")
            await tokens.mark_used(record.id, now)
            await UserRepository(session).mark_email_verified(record.user_id, now)
        log.info("email_verified", user_id=str(record.user_id))

    async def resend_verification(self, email: str) -> None:
        """Всегда «успешно»: ответ не раскрывает, зарегистрирован ли email."""
        email = normalize_email(email)
        now = self._now()
        async with self._session_factory() as session, session.begin():
            user = await UserRepository(session).get_by_email(email)
            if user is None or user.email_verified or not user.is_active:
                return
            await VerificationTokenRepository(session).invalidate_for_user(user.id, now)
            await self._request_verification(session, user.id, user.email, now)

    # ---------- вход, refresh, выход ----------

    async def login(self, email: str, password: str) -> TokenPair:
        email = normalize_email(email)
        retry_after = await self._limiter.retry_after(email)
        if retry_after is not None:
            raise TooManyAttemptsError(retry_after)

        async with self._session_factory() as session, session.begin():
            users = UserRepository(session)
            user = await users.get_by_email(email)
            password_ok = await self._verify(password, user.password_hash if user else None)
            if user is None or not password_ok or not user.is_active:
                await self._limiter.register_failure(email)
                raise InvalidCredentialsError
            pair = await self._issue_pair(session, user, family_id=uuid7())

        await self._limiter.reset(email)
        log.info("user_logged_in", user_id=str(user.id))
        return pair

    async def refresh(self, refresh_token: str) -> TokenPair:
        now = self._now()
        reuse_detected = False
        async with self._session_factory() as session, session.begin():
            tokens = RefreshTokenRepository(session)
            record = await tokens.get_for_update(hash_token(refresh_token))
            if record is None:
                raise InvalidTokenError("unknown refresh token")
            if record.used_at is not None or record.revoked_at is not None:
                # Повторное предъявление: токен, вероятно, украден — отзываем всё семейство.
                await tokens.revoke_family(record.family_id, now)
                reuse_detected = True
            elif record.expires_at <= now:
                raise InvalidTokenError("refresh token expired")
            else:
                user = await UserRepository(session).get_by_id(record.user_id)
                if user is None or not user.is_active:
                    raise InvalidTokenError("user is not active")
                await tokens.mark_used(record.id, now)
                return await self._issue_pair(session, user, family_id=record.family_id)

        if reuse_detected:  # исключение после коммита: отзыв семейства должен сохраниться
            log.warning("refresh_token_reuse_detected", family_id=str(record.family_id))
        raise InvalidTokenError("refresh token reuse")

    async def logout(self, refresh_token: str) -> None:
        now = self._now()
        async with self._session_factory() as session, session.begin():
            tokens = RefreshTokenRepository(session)
            record = await tokens.get_for_update(hash_token(refresh_token))
            if record is not None:
                await tokens.revoke_family(record.family_id, now)

    async def change_password(self, user_id: UUID, old_password: str, new_password: str) -> None:
        async with self._session_factory() as session, session.begin():
            users = UserRepository(session)
            user = await users.get_by_id(user_id)
            if user is None or not await self._verify(old_password, user.password_hash):
                raise InvalidCredentialsError
            validate_password(new_password, email=user.email)
            await users.set_password_hash(user_id, await self._hash(new_password))
            await RefreshTokenRepository(session).revoke_all_for_user(user_id, self._now())
        log.info("password_changed", user_id=str(user_id))

    async def _issue_pair(
        self, session: AsyncSession, user: UserRecord, family_id: UUID
    ) -> TokenPair:
        now = self._now()
        roles = await UserRepository(session).get_roles(user.id) or set(DEFAULT_ROLES)
        refresh_token = generate_opaque_token()
        await RefreshTokenRepository(session).create(
            uuid7(),
            user.id,
            family_id,
            hash_token(refresh_token),
            now + self._config.refresh_token_ttl,
        )
        access_token = self._issuer.issue(
            user.id, roles, email_verified=user.email_verified, now=now
        )
        return TokenPair(access_token, refresh_token, self._issuer.ttl_seconds)

    # ---------- служебное ----------

    async def create_user(self, email: str, password: str, *, verified: bool) -> UUID:
        """Создание пользователя из CLI (например, первого администратора).

        Роли выдаёт user-service (владелец RBAC) по событию user.created.
        """
        email = normalize_email(email)
        validate_password(password, email=email)
        password_hash = await self._hash(password)
        user_id = uuid7()
        now = self._now()
        async with self._session_factory() as session, session.begin():
            users = UserRepository(session)
            if await users.email_exists(email):
                raise EmailAlreadyRegisteredError(email)
            await users.create(
                user_id, email, password_hash, email_verified_at=now if verified else None
            )
            await users.replace_roles(user_id, DEFAULT_ROLES)
            await self._outbox.add(
                session,
                UserCreated(
                    producer=SERVICE_NAME,
                    correlation_id=user_id,
                    payload=UserCreatedPayload(
                        user_id=user_id,
                        email=email,
                        created_at=now,
                        auth_provider=AuthProvider.PASSWORD,
                    ),
                ),
            )
        return user_id
