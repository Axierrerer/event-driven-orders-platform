"""Фоновый процесс: события склада (сага), очистка ключей идемпотентности, outbox.

Запуск: python -m src.worker
"""

import asyncio
from datetime import timedelta

from platform_lib.logging import configure_logging, get_logger
from platform_lib.worker import run_pg_worker
from src import db
from src.config import get_settings
from src.main import build_service

log = get_logger(__name__)


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.service_name, settings.log_level)
    engine = db.make_engine(settings.database_url)
    orders = build_service(settings, engine)
    ttl = timedelta(hours=settings.idempotency_key_ttl_hours)

    async def cleanup(stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                removed = await orders.cleanup_idempotency_keys(ttl)
                if removed:
                    log.info("idempotency_keys_removed", count=removed)
            except Exception:
                log.exception("idempotency_cleanup_failed")
            try:
                await asyncio.wait_for(stop.wait(), timeout=3600)
            except TimeoutError:
                pass

    async def stuck_orders(stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                await orders.report_stuck_orders()
            except Exception:
                log.exception("stuck_orders_report_failed")
            try:
                await asyncio.wait_for(stop.wait(), timeout=30)
            except TimeoutError:
                pass

    await run_pg_worker(
        settings,
        engine=engine,
        session_factory=db.make_session_factory(engine),
        outbox=db.outbox,
        processed_events=db.processed_events,
        handlers={
            "inventory.reserved": orders.on_inventory_reserved,
            "inventory.reservation-failed": orders.on_reservation_failed,
            "inventory.released": orders.on_inventory_released,
        },
        extra_tasks=[cleanup, stuck_orders],
    )


if __name__ == "__main__":
    asyncio.run(main())
