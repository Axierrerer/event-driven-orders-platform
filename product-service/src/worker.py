"""Фоновый процесс: публикация outbox (product.changed). Событий не потребляет.

Запуск: python -m src.worker
"""

import asyncio

from platform_lib.logging import configure_logging
from platform_lib.worker import run_mongo_worker
from src import db
from src.config import get_settings


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.service_name, settings.log_level)
    client = db.make_client(settings.mongo_url)
    await run_mongo_worker(settings, client=client, database=client[settings.mongo_db], handlers={})


if __name__ == "__main__":
    asyncio.run(main())
