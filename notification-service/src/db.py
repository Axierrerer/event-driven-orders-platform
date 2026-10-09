from typing import Any

from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import ASCENDING, DESCENDING

from platform_lib.outbox import ensure_outbox_indexes


def make_client(mongo_url: str) -> Any:
    return AsyncIOMotorClient(mongo_url, tz_aware=True, uuidRepresentation="standard")


async def ensure_indexes(db: Any) -> None:
    await db.notifications.create_index(
        [("status", ASCENDING), ("next_attempt_at", ASCENDING)], name="ix_notifications_due"
    )
    await db.notifications.create_index(
        [("user_id", ASCENDING), ("created_at", DESCENDING)], name="ix_notifications_user"
    )
    await ensure_outbox_indexes(db.outbox)
