from collections.abc import Iterable
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from events import Role
from src.db import user_roles, users
from src.domain.profile import Address, Profile


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def exists(self, user_id: UUID) -> bool:
        return (
            await self._session.scalar(select(users.c.id).where(users.c.id == user_id)) is not None
        )

    async def create(self, user_id: UUID, email: str) -> None:
        await self._session.execute(insert(users).values(id=user_id, email=email))

    async def get(self, user_id: UUID, *, for_update: bool = False) -> Profile | None:
        query = select(users).where(users.c.id == user_id, users.c.deleted_at.is_(None))
        if for_update:
            query = query.with_for_update()
        row = (await self._session.execute(query)).mappings().first()
        if row is None:
            return None
        return self._profile(row, await self.get_roles(user_id))

    async def list_profiles(
        self, *, email_contains: str | None, limit: int, offset: int
    ) -> list[Profile]:
        query = select(users).where(users.c.deleted_at.is_(None))
        if email_contains:
            query = query.where(
                func.lower(users.c.email).contains(email_contains.lower(), autoescape=True)
            )
        query = query.order_by(users.c.created_at, users.c.id).limit(limit).offset(offset)
        rows = (await self._session.execute(query)).mappings().all()
        roles = await self._roles_for([row["id"] for row in rows])
        return [self._profile(row, roles.get(row["id"], set())) for row in rows]

    async def update_profile(self, user_id: UUID, values: dict[str, Any]) -> None:
        if "address" in values and isinstance(values["address"], Address):
            values["address"] = values["address"].model_dump(exclude_none=True)
        await self._session.execute(
            update(users).where(users.c.id == user_id).values(**values, updated_at=func.now())
        )

    async def soft_delete(self, user_id: UUID, *, anonymized_email: str, at: datetime) -> None:
        await self._session.execute(
            update(users)
            .where(users.c.id == user_id)
            .values(
                email=anonymized_email,
                full_name=None,
                phone=None,
                address=None,
                deleted_at=at,
                updated_at=func.now(),
            )
        )
        await self._session.execute(delete(user_roles).where(user_roles.c.user_id == user_id))

    async def get_roles(self, user_id: UUID) -> set[Role]:
        rows = await self._session.scalars(
            select(user_roles.c.role).where(user_roles.c.user_id == user_id)
        )
        return {Role(role) for role in rows}

    async def replace_roles(
        self, user_id: UUID, roles: Iterable[Role], granted_by: UUID | None
    ) -> None:
        await self._session.execute(delete(user_roles).where(user_roles.c.user_id == user_id))
        values = [
            {"user_id": user_id, "role": str(role), "granted_by": granted_by} for role in set(roles)
        ]
        if values:
            await self._session.execute(insert(user_roles), values)

    async def lock_admins(self) -> set[UUID]:
        """Активные администраторы; строки блокируются до конца транзакции,
        чтобы два параллельных запроса не сняли двух последних админов."""
        rows = await self._session.scalars(
            select(user_roles.c.user_id)
            .join(users, users.c.id == user_roles.c.user_id)
            .where(user_roles.c.role == str(Role.ADMIN), users.c.deleted_at.is_(None))
            .with_for_update()
        )
        return set(rows)

    async def _roles_for(self, user_ids: list[UUID]) -> dict[UUID, set[Role]]:
        if not user_ids:
            return {}
        rows = await self._session.execute(
            select(user_roles.c.user_id, user_roles.c.role).where(
                user_roles.c.user_id.in_(user_ids)
            )
        )
        result: dict[UUID, set[Role]] = {}
        for user_id, role in rows:
            result.setdefault(user_id, set()).add(Role(role))
        return result

    @staticmethod
    def _profile(row: Any, roles: set[Role]) -> Profile:
        return Profile(
            id=row["id"],
            email=row["email"],
            full_name=row["full_name"],
            phone=row["phone"],
            address=Address(**row["address"]) if row["address"] else None,
            roles=sorted(roles),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
