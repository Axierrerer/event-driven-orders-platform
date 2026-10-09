from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from pymongo import DESCENDING, ReturnDocument
from pymongo.errors import DuplicateKeyError

from src.domain.models import DUE_STATUSES, Notification, NotificationStatus


def _to_doc(n: Notification) -> dict[str, Any]:
    doc = n.model_dump(exclude={"id"})
    doc["_id"] = n.id
    doc["user_id"] = str(n.user_id)
    return doc


def _from_doc(doc: dict[str, Any]) -> Notification:
    return Notification.model_validate({**doc, "id": doc["_id"]})


class JournalRepository:
    def __init__(self, db: Any) -> None:
        self._col = db.notifications

    async def add(self, notification: Notification, *, session: Any) -> bool:
        """False — уведомление для этого события уже есть (повторная доставка)."""
        try:
            await self._col.insert_one(_to_doc(notification), session=session)
        except DuplicateKeyError:
            return False
        return True

    async def attach_contact(
        self, user_id: UUID, email: str, now: datetime, *, session: Any
    ) -> int:
        result = await self._col.update_many(
            {"user_id": str(user_id), "status": str(NotificationStatus.PENDING_CONTACT)},
            {
                "$set": {
                    "email": email,
                    "status": str(NotificationStatus.PENDING),
                    "next_attempt_at": now,
                }
            },
            session=session,
        )
        return int(result.modified_count)

    async def claim_due(self, now: datetime, lease: timedelta) -> Notification | None:
        """Захватить одно готовое к отправке уведомление (аренда, чтобы реплики не дублировали)."""
        doc = await self._col.find_one_and_update(
            {
                "status": {"$in": [str(s) for s in DUE_STATUSES]},
                "next_attempt_at": {"$lte": now},
                "$or": [{"locked_until": None}, {"locked_until": {"$lte": now}}],
            },
            {"$set": {"locked_until": now + lease}},
            sort=[("next_attempt_at", 1)],
            return_document=ReturnDocument.AFTER,
        )
        return _from_doc(doc) if doc else None

    async def mark_sent(self, notification_id: str, now: datetime) -> None:
        await self._col.update_one(
            {"_id": notification_id},
            {
                "$set": {
                    "status": str(NotificationStatus.SENT),
                    "sent_at": now,
                    "locked_until": None,
                },
                "$unset": {"context": ""},  # содержимое письма не храним после отправки
            },
        )

    async def postpone(
        self,
        notification_id: str,
        status: NotificationStatus,
        next_attempt_at: datetime,
        *,
        error: str | None = None,
        attempts: int | None = None,
    ) -> None:
        values: dict[str, Any] = {
            "status": str(status),
            "next_attempt_at": next_attempt_at,
            "locked_until": None,
        }
        if error is not None:
            values["last_error"] = error[:500]
        if attempts is not None:
            values["attempts"] = attempts
        await self._col.update_one({"_id": notification_id}, {"$set": values})

    async def mark_failed(self, notification_id: str, error: str, attempts: int) -> None:
        await self._col.update_one(
            {"_id": notification_id},
            {
                "$set": {
                    "status": str(NotificationStatus.FAILED),
                    "last_error": error[:500],
                    "attempts": attempts,
                    "locked_until": None,
                },
                "$unset": {"context": ""},
            },
        )

    async def list_notifications(
        self, *, user_id: UUID | None, status: NotificationStatus | None, limit: int, offset: int
    ) -> list[Notification]:
        query: dict[str, Any] = {}
        if user_id is not None:
            query["user_id"] = str(user_id)
        if status is not None:
            query["status"] = str(status)
        cursor = (
            self._col.find(query, {"context": 0})
            .sort([("created_at", DESCENDING)])
            .skip(offset)
            .limit(limit)
        )
        return [_from_doc(doc) for doc in await cursor.to_list(limit)]

    async def get(self, notification_id: str) -> Notification | None:
        doc = await self._col.find_one({"_id": notification_id})
        return _from_doc(doc) if doc else None
