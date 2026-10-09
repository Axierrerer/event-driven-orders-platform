from typing import Any

from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import ASCENDING, DESCENDING, TEXT

from platform_lib.outbox import ensure_outbox_indexes


def make_client(mongo_url: str) -> Any:
    # tz_aware: даты из MongoDB возвращаются с UTC, а не naive
    return AsyncIOMotorClient(mongo_url, tz_aware=True, uuidRepresentation="standard")


async def ensure_indexes(db: Any) -> None:
    """Идемпотентно создаёт индексы (вызывается при старте)."""
    await db.products.create_index([("sku", ASCENDING)], unique=True, name="ux_products_sku")
    await db.products.create_index(
        [("name", TEXT), ("description", TEXT)],
        weights={"name": 10, "description": 1},
        default_language="russian",
        name="tx_products_search",
    )
    await db.products.create_index(
        [
            ("is_deleted", ASCENDING),
            ("is_published", ASCENDING),
            ("category_id", ASCENDING),
            ("price", ASCENDING),
        ],
        name="ix_products_filter",
    )
    await db.products.create_index([("created_at", DESCENDING)], name="ix_products_created")
    await db.categories.create_index([("name", ASCENDING)], unique=True, name="ux_categories_name")
    await ensure_outbox_indexes(db.outbox)
