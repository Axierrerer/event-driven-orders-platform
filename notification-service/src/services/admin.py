from typing import Any
from uuid import UUID

from src.domain.models import EmailTemplate, Notification, NotificationStatus
from src.domain.templates import validate
from src.repositories.journal import JournalRepository
from src.repositories.templates import TemplateRepository


class AdminService:
    """Служебные операции администратора: журнал уведомлений и шаблоны писем."""

    def __init__(self, db: Any) -> None:
        self._journal = JournalRepository(db)
        self._templates = TemplateRepository(db)

    async def list_notifications(
        self, *, user_id: UUID | None, status: NotificationStatus | None, limit: int, offset: int
    ) -> list[Notification]:
        return await self._journal.list_notifications(
            user_id=user_id, status=status, limit=limit, offset=offset
        )

    async def template_keys(self) -> list[str]:
        return await self._templates.keys()

    async def get_template(self, key: str) -> EmailTemplate | None:
        return await self._templates.get(key)

    async def save_template(self, template: EmailTemplate) -> None:
        validate(template)  # TemplateRenderError при синтаксической ошибке
        await self._templates.save(template)
