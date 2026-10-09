"""Фоновый процесс: публикация outbox и проекция ролей из user-service.

Запуск: python -m src.worker
"""

import asyncio

from platform_lib.logging import configure_logging
from platform_lib.worker import run_pg_worker
from src import db
from src.config import get_settings
from src.services.roles_projection import apply_roles_changed


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.service_name, settings.log_level)
    engine = db.make_engine(settings.database_url)
    await run_pg_worker(
        settings,
        engine=engine,
        session_factory=db.make_session_factory(engine),
        outbox=db.outbox,
        processed_events=db.processed_events,
        handlers={"user.roles-changed": apply_roles_changed},
    )


if __name__ == "__main__":
    asyncio.run(main())
