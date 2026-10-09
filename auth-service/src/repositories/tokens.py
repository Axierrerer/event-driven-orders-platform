from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.db import email_verification_tokens, refresh_tokens


@dataclass(frozen=True, slots=True)
class RefreshTokenRecord:
    id: UUID
    user_id: UUID
    family_id: UUID
    expires_at: datetime
    used_at: datetime | None
    revoked_at: datetime | None


@dataclass(frozen=True, slots=True)
class VerificationTokenRecord:
    id: UUID
    user_id: UUID
    expires_at: datetime
    used_at: datetime | None


class RefreshTokenRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self, token_id: UUID, user_id: UUID, family_id: UUID, token_hash: str, expires_at: datetime
    ) -> None:
        await self._session.execute(
            insert(refresh_tokens).values(
                id=token_id,
                user_id=user_id,
                family_id=family_id,
                token_hash=token_hash,
                expires_at=expires_at,
            )
        )

    async def get_for_update(self, token_hash: str) -> RefreshTokenRecord | None:
        t = refresh_tokens
        row = (
            await self._session.execute(
                select(t).where(t.c.token_hash == token_hash).with_for_update()
            )
        ).first()
        if row is None:
            return None
        m = row._mapping
        return RefreshTokenRecord(
            id=m["id"],
            user_id=m["user_id"],
            family_id=m["family_id"],
            expires_at=m["expires_at"],
            used_at=m["used_at"],
            revoked_at=m["revoked_at"],
        )

    async def mark_used(self, token_id: UUID, at: datetime) -> None:
        await self._session.execute(
            update(refresh_tokens).where(refresh_tokens.c.id == token_id).values(used_at=at)
        )

    async def revoke_family(self, family_id: UUID, at: datetime) -> None:
        t = refresh_tokens
        await self._session.execute(
            update(t)
            .where(t.c.family_id == family_id, t.c.revoked_at.is_(None))
            .values(revoked_at=at)
        )

    async def revoke_all_for_user(self, user_id: UUID, at: datetime) -> None:
        t = refresh_tokens
        await self._session.execute(
            update(t).where(t.c.user_id == user_id, t.c.revoked_at.is_(None)).values(revoked_at=at)
        )


class VerificationTokenRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self, token_id: UUID, user_id: UUID, token_hash: str, expires_at: datetime
    ) -> None:
        await self._session.execute(
            insert(email_verification_tokens).values(
                id=token_id, user_id=user_id, token_hash=token_hash, expires_at=expires_at
            )
        )

    async def get_for_update(self, token_hash: str) -> VerificationTokenRecord | None:
        t = email_verification_tokens
        row = (
            await self._session.execute(
                select(t).where(t.c.token_hash == token_hash).with_for_update()
            )
        ).first()
        if row is None:
            return None
        m = row._mapping
        return VerificationTokenRecord(
            id=m["id"], user_id=m["user_id"], expires_at=m["expires_at"], used_at=m["used_at"]
        )

    async def mark_used(self, token_id: UUID, at: datetime) -> None:
        t = email_verification_tokens
        await self._session.execute(update(t).where(t.c.id == token_id).values(used_at=at))

    async def invalidate_for_user(self, user_id: UUID, at: datetime) -> None:
        t = email_verification_tokens
        await self._session.execute(
            update(t).where(t.c.user_id == user_id, t.c.used_at.is_(None)).values(used_at=at)
        )
