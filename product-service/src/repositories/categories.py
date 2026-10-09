from typing import Any
from uuid import UUID

from pymongo import ASCENDING, ReturnDocument

from src.domain.models import Category


def _from_doc(doc: dict[str, Any]) -> Category:
    return Category(
        id=UUID(doc["_id"]),
        name=doc["name"],
        description=doc.get("description", ""),
        created_at=doc["created_at"],
    )


class CategoryRepository:
    def __init__(self, db: Any) -> None:
        self._categories = db.categories

    async def insert(self, category: Category) -> None:
        await self._categories.insert_one(
            {
                "_id": str(category.id),
                "name": category.name,
                "description": category.description,
                "created_at": category.created_at,
            }
        )

    async def get(self, category_id: UUID) -> Category | None:
        doc = await self._categories.find_one({"_id": str(category_id)})
        return _from_doc(doc) if doc else None

    async def list_all(self) -> list[Category]:
        docs = await self._categories.find().sort([("name", ASCENDING)]).to_list(None)
        return [_from_doc(doc) for doc in docs]

    async def update(self, category_id: UUID, values: dict[str, Any]) -> Category | None:
        doc = await self._categories.find_one_and_update(
            {"_id": str(category_id)}, {"$set": values}, return_document=ReturnDocument.AFTER
        )
        return _from_doc(doc) if doc else None

    async def delete(self, category_id: UUID) -> bool:
        result = await self._categories.delete_one({"_id": str(category_id)})
        return bool(result.deleted_count)
