from typing import Any
from uuid import UUID


class ContactRepository:
    """Проекция email пользователей из user.created."""

    def __init__(self, db: Any) -> None:
        self._col = db.user_contacts

    async def upsert(self, user_id: UUID, email: str, *, session: Any) -> None:
        await self._col.update_one(
            {"_id": str(user_id)}, {"$set": {"email": email}}, upsert=True, session=session
        )

    async def email_of(self, user_id: UUID, *, session: Any = None) -> str | None:
        doc = await self._col.find_one({"_id": str(user_id)}, session=session)
        return str(doc["email"]) if doc else None
