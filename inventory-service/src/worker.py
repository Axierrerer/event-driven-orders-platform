"""Фоновый процесс: события каталога и заказов, истечение резервов, публикация outbox.

Запуск: python -m src.worker
"""

import asyncio

from redis.asyncio import Redis

from platform_lib.logging import configure_logging
from platform_lib.worker import run_pg_worker
from src import db
from src.config import get_settings
from src.main import build_service


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.service_name, settings.log_level)
    engine = db.make_engine(settings.database_url)
    inventory = build_service(settings, engine)
    redis = Redis.from_url(settings.redis_url)

    async def expiry(stop: asyncio.Event) -> None:
        await inventory.run_expiry_loop(
            stop, redis, interval_seconds=settings.expiry_check_interval_seconds
        )

    try:
        await run_pg_worker(
            settings,
            engine=engine,
            session_factory=db.make_session_factory(engine),
            outbox=db.outbox,
            processed_events=db.processed_events,
            handlers={
                "product.changed": inventory.on_product_changed,
                "order.created": inventory.on_order_created,
                "order.status-changed": inventory.on_order_status_changed,
            },
            extra_tasks=[expiry],
        )
    finally:
        await redis.aclose()


if __name__ == "__main__":
    asyncio.run(main())
