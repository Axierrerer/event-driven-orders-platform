from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from events import Role, UserCreated, UserRolesChanged, UserRolesChangedPayload
from platform_lib.auth import Principal
from platform_lib.logging import get_logger
from platform_lib.outbox import PgOutbox
from src.domain.errors import (
    AccessDeniedError,
    LastAdminError,
    SelfModificationError,
    UserNotFoundError,
)
from src.domain.profile import STAFF_ROLES, Profile, anonymized_email
from src.repositories.users import UserRepository

log = get_logger(__name__)

SERVICE_NAME = "user-service"


class UserService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        outbox: PgOutbox,
        *,
        bootstrap_admin_email: str | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._session_factory = session_factory
        self._outbox = outbox
        self._bootstrap_admin_email = (bootstrap_admin_email or "").strip().lower() or None
        self._now = clock

    # ---------- события ----------

    async def on_user_created(self, event: UserCreated, session: AsyncSession) -> None:
        """Профиль появляется по событию auth-service. Вызывается в транзакции consumer’а."""
        users = UserRepository(session)
        payload = event.payload
        if await users.exists(payload.user_id):
            return
        await users.create(payload.user_id, payload.email)
        roles = {Role.USER}
        if self._bootstrap_admin_email and payload.email.lower() == self._bootstrap_admin_email:
            roles.add(Role.ADMIN)
            await self._publish_roles(session, payload.user_id, roles, changed_by=payload.user_id)
            log.info("bootstrap_admin_granted", user_id=str(payload.user_id))
        await users.replace_roles(payload.user_id, roles, granted_by=None)

    # ---------- профиль ----------

    async def get_me(self, principal: Principal) -> Profile:
        return await self.get(principal, principal.user_id)

    async def get(self, principal: Principal, user_id: UUID) -> Profile:
        if user_id != principal.user_id and not principal.has_any(STAFF_ROLES):
            raise AccessDeniedError
        async with self._session_factory() as session:
            profile = await UserRepository(session).get(user_id)
        if profile is None:
            raise UserNotFoundError
        return profile

    async def list_users(
        self, *, email_contains: str | None, limit: int, offset: int
    ) -> list[Profile]:
        async with self._session_factory() as session:
            return await UserRepository(session).list_profiles(
                email_contains=email_contains, limit=limit, offset=offset
            )

    async def update_me(self, principal: Principal, changes: dict[str, Any]) -> Profile:
        async with self._session_factory() as session, session.begin():
            users = UserRepository(session)
            if await users.get(principal.user_id, for_update=True) is None:
                raise UserNotFoundError
            if changes:
                await users.update_profile(principal.user_id, changes)
            profile = await users.get(principal.user_id)
        if profile is None:  # профиль удалён параллельным запросом
            raise UserNotFoundError
        return profile

    # ---------- администрирование ----------

    async def set_roles(self, admin: Principal, user_id: UUID, roles: Iterable[Role]) -> Profile:
        new_roles = set(roles)
        async with self._session_factory() as session, session.begin():
            users = UserRepository(session)
            admins = await users.lock_admins()
            if await users.get(user_id, for_update=True) is None:
                raise UserNotFoundError
            losing_admin = user_id in admins and Role.ADMIN not in new_roles
            if losing_admin and user_id == admin.user_id:
                raise SelfModificationError
            if losing_admin and len(admins) <= 1:
                raise LastAdminError
            await users.replace_roles(user_id, new_roles, granted_by=admin.user_id)
            await self._publish_roles(session, user_id, new_roles, changed_by=admin.user_id)
            profile = await users.get(user_id)
        log.info("roles_changed", user_id=str(user_id), roles=sorted(new_roles))
        if profile is None:  # профиль удалён параллельным запросом
            raise UserNotFoundError
        return profile

    async def delete(self, admin: Principal, user_id: UUID) -> None:
        async with self._session_factory() as session, session.begin():
            users = UserRepository(session)
            admins = await users.lock_admins()
            if await users.get(user_id, for_update=True) is None:
                raise UserNotFoundError
            if user_id == admin.user_id:
                raise SelfModificationError
            if user_id in admins and len(admins) <= 1:
                raise LastAdminError
            await users.soft_delete(
                user_id, anonymized_email=anonymized_email(user_id), at=self._now()
            )
            await self._publish_roles(session, user_id, set(), changed_by=admin.user_id)
        log.info("user_deleted", user_id=str(user_id))

    async def _publish_roles(
        self, session: AsyncSession, user_id: UUID, roles: set[Role], changed_by: UUID
    ) -> None:
        await self._outbox.add(
            session,
            UserRolesChanged(
                producer=SERVICE_NAME,
                correlation_id=user_id,
                payload=UserRolesChangedPayload(
                    user_id=user_id, roles=sorted(roles), changed_by=changed_by
                ),
            ),
        )
