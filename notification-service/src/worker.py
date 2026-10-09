"""Фоновый процесс: события пользователей и заказов → журнал, диспетчер отправки писем.

Запуск: python -m src.worker
"""

import asyncio

from redis.asyncio import Redis

from platform_lib.logging import configure_logging
from platform_lib.worker import run_mongo_worker
from src import db
from src.config import get_settings
from src.main import build_service, prepare_database


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.service_name, settings.log_level)
    client = db.make_client(settings.mongo_url)
    database = client[settings.mongo_db]
    redis = Redis.from_url(settings.redis_url)
    await prepare_database(database)
    service = build_service(settings, database, redis)

    async def dispatcher(stop: asyncio.Event) -> None:
        await service.run_dispatcher(stop, interval_seconds=settings.dispatch_interval_seconds)

    try:
        await run_mongo_worker(
            settings,
            client=client,
            database=database,
            handlers={
                "user.created": service.on_user_created,
                "user.verification-requested": service.on_verification_requested,
                "order.created": service.on_order_created,
                "order.status-changed": service.on_order_status_changed,
            },
            extra_tasks=[dispatcher],
        )
    finally:
        await redis.aclose()


if __name__ == "__main__":
    asyncio.run(main())
