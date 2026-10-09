from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from events import Role
from src.db import user_roles, users


@dataclass(frozen=True, slots=True)
class UserRecord:
    id: UUID
    email: str
    password_hash: str | None
    email_verified_at: datetime | None
    is_active: bool

    @property
    def email_verified(self) -> bool:
        return self.email_verified_at is not None


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_email(self, email: str) -> UserRecord | None:
        row = (await self._session.execute(select(users).where(users.c.email == email))).first()
        return self._to_record(row) if row else None

    async def get_by_id(self, user_id: UUID) -> UserRecord | None:
        row = (await self._session.execute(select(users).where(users.c.id == user_id))).first()
        return self._to_record(row) if row else None

    async def email_exists(self, email: str) -> bool:
        found = await self._session.scalar(select(users.c.id).where(users.c.email == email))
        return found is not None

    async def create(
        self,
        user_id: UUID,
        email: str,
        password_hash: str,
        *,
        email_verified_at: datetime | None = None,
    ) -> None:
        await self._session.execute(
            insert(users).values(
                id=user_id,
                email=email,
                password_hash=password_hash,
                email_verified_at=email_verified_at,
            )
        )

    async def mark_email_verified(self, user_id: UUID, at: datetime) -> None:
        await self._session.execute(
            update(users)
            .where(users.c.id == user_id, users.c.email_verified_at.is_(None))
            .values(email_verified_at=at, updated_at=func.now())
        )

    async def set_password_hash(self, user_id: UUID, password_hash: str) -> None:
        await self._session.execute(
            update(users)
            .where(users.c.id == user_id)
            .values(password_hash=password_hash, updated_at=func.now())
        )

    async def get_roles(self, user_id: UUID) -> set[Role]:
        rows = await self._session.scalars(
            select(user_roles.c.role).where(user_roles.c.user_id == user_id)
        )
        return {Role(role) for role in rows}

    async def replace_roles(self, user_id: UUID, roles: Iterable[Role]) -> None:
        await self._session.execute(delete(user_roles).where(user_roles.c.user_id == user_id))
        values = [{"user_id": user_id, "role": str(role)} for role in set(roles)]
        if values:
            await self._session.execute(insert(user_roles), values)

    @staticmethod
    def _to_record(row: object) -> UserRecord:
        mapping = row._mapping  # type: ignore[attr-defined]
        return UserRecord(
            id=mapping["id"],
            email=mapping["email"],
            password_hash=mapping["password_hash"],
            email_verified_at=mapping["email_verified_at"],
            is_active=mapping["is_active"],
        )
