"""Фоновый процесс: профили по user.created и публикация outbox.

Запуск: python -m src.worker
"""

import asyncio

from platform_lib.logging import configure_logging
from platform_lib.outbox import PgOutbox
from platform_lib.worker import run_pg_worker
from src import db
from src.config import get_settings
from src.services.users import UserService


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.service_name, settings.log_level)
    engine = db.make_engine(settings.database_url)
    session_factory = db.make_session_factory(engine)
    service = UserService(
        session_factory, PgOutbox(db.outbox), bootstrap_admin_email=settings.bootstrap_admin_email
    )
    await run_pg_worker(
        settings,
        engine=engine,
        session_factory=session_factory,
        outbox=db.outbox,
        processed_events=db.processed_events,
        handlers={"user.created": service.on_user_created},
    )


if __name__ == "__main__":
    asyncio.run(main())
