from collections.abc import Iterable
from typing import Any

from src.domain.models import EmailTemplate


class TemplateRepository:
    def __init__(self, db: Any) -> None:
        self._col = db.templates

    async def seed(self, templates: Iterable[EmailTemplate]) -> None:
        """Добавляет недостающие шаблоны, не трогая изменённые администратором."""
        for template in templates:
            await self._col.update_one(
                {"_id": template.key},
                {"$setOnInsert": template.model_dump(exclude={"key"})},
                upsert=True,
            )

    async def get(self, key: str) -> EmailTemplate | None:
        doc = await self._col.find_one({"_id": key})
        return EmailTemplate.model_validate({**doc, "key": doc["_id"]}) if doc else None

    async def save(self, template: EmailTemplate) -> None:
        await self._col.replace_one(
            {"_id": template.key}, template.model_dump(exclude={"key"}), upsert=True
        )

    async def keys(self) -> list[str]:
        return sorted(str(doc["_id"]) for doc in await self._col.find({}, {"_id": 1}).to_list(None))
