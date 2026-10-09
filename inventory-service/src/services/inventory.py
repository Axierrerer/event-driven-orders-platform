"""Сценарии склада. Обработчики событий вызываются в транзакции consumer’а."""

import asyncio
from collections.abc import Callable, Iterable
from datetime import UTC, datetime, timedelta
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from events import (
    InventoryReleased,
    InventoryReleasedPayload,
    InventoryReservationFailed,
    InventoryReservationFailedPayload,
    InventoryReserved,
    InventoryReservedPayload,
    MissingItem,
    OrderCreated,
    OrderStatus,
    OrderStatusChanged,
    ProductChanged,
    ReleaseReason,
    ReservationFailureReason,
    ReservedItem,
    uuid7,
)
from platform_lib.locks import LockNotAcquiredError, RedisLock
from platform_lib.logging import get_logger
from platform_lib.outbox import PgOutbox
from src.domain.errors import InvalidAdjustmentError, StockNotFoundError
from src.domain.models import (
    MovementReason,
    ReservationStatus,
    StockLevel,
    find_shortages,
    merge_quantities,
)
from src.repositories.stock import Reservation, StockRepository
from src.services.metrics import RESERVATIONS, RESERVATIONS_RELEASED

log = get_logger(__name__)

SERVICE_NAME = "inventory-service"
EXPIRY_BATCH = 100


class InventoryService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        outbox: PgOutbox,
        *,
        reservation_ttl: timedelta,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._session_factory = session_factory
        self._outbox = outbox
        self._ttl = reservation_ttl
        self._now = clock

    # ---------- события ----------

    async def on_product_changed(self, event: ProductChanged, session: AsyncSession) -> None:
        """Новый товар каталога получает строку остатка с нулём."""
        await StockRepository(session).ensure_exists(event.payload.product_id)

    async def on_order_created(self, event: OrderCreated, session: AsyncSession) -> None:
        """Резерв всего заказа целиком: либо все позиции, либо ни одной."""
        order = event.payload
        repo = StockRepository(session)
        if await repo.reservation_exists(order.order_id):
            log.info("reservation_already_exists", order_id=str(order.order_id))
            return

        requested = merge_quantities((item.product_id, item.quantity) for item in order.items)
        levels = await repo.lock_many(requested)
        unknown, shortages = find_shortages(requested, levels)

        if unknown or shortages:
            reason = (
                ReservationFailureReason.UNKNOWN_PRODUCT
                if unknown
                else ReservationFailureReason.OUT_OF_STOCK
            )
            missing = [
                MissingItem(product_id=pid, requested=requested[pid], available=0)
                for pid in unknown
            ]
            missing += [
                MissingItem(product_id=s.product_id, requested=s.requested, available=s.available)
                for s in shortages
            ]
            await self._outbox.add(
                session,
                InventoryReservationFailed(
                    producer=SERVICE_NAME,
                    correlation_id=event.correlation_id,
                    payload=InventoryReservationFailedPayload(
                        order_id=order.order_id, reason=reason, missing=missing
                    ),
                ),
            )
            RESERVATIONS.labels(str(reason).lower()).inc()
            log.info("reservation_failed", order_id=str(order.order_id), reason=str(reason))
            return

        reservation_id = uuid7()
        expires_at = self._now() + self._ttl
        for product_id, quantity in requested.items():
            await repo.change(
                product_id,
                delta_on_hand=0,
                delta_reserved=quantity,
                reason=MovementReason.RESERVE,
                ref_id=reservation_id,
            )
        await repo.create_reservation(reservation_id, order.order_id, requested, expires_at)
        await self._outbox.add(
            session,
            InventoryReserved(
                producer=SERVICE_NAME,
                correlation_id=event.correlation_id,
                payload=InventoryReservedPayload(
                    order_id=order.order_id,
                    reservation_id=reservation_id,
                    items=[ReservedItem(product_id=p, quantity=q) for p, q in requested.items()],
                    expires_at=expires_at,
                ),
            ),
        )
        RESERVATIONS.labels("reserved").inc()
        log.info("reservation_created", order_id=str(order.order_id))

    async def on_order_status_changed(
        self, event: OrderStatusChanged, session: AsyncSession
    ) -> None:
        payload = event.payload
        if payload.new_status not in {OrderStatus.CANCELLED, OrderStatus.PAID, OrderStatus.SHIPPED}:
            return
        repo = StockRepository(session)
        reservation = await repo.get_reservation_for_update(payload.order_id)
        if reservation is None:
            return  # резерв не создавался (например, отказ по наличию)

        if payload.new_status is OrderStatus.CANCELLED:
            if reservation.status in {ReservationStatus.ACTIVE, ReservationStatus.CONFIRMED}:
                await self._release(session, reservation, ReleaseReason.ORDER_CANCELLED, event)
        elif payload.new_status is OrderStatus.PAID:
            if reservation.status is ReservationStatus.ACTIVE:
                await repo.set_status(reservation.id, ReservationStatus.CONFIRMED)
            elif reservation.status is ReservationStatus.RELEASED:
                log.warning("paid_order_without_reservation", order_id=str(payload.order_id))
        elif reservation.status in {ReservationStatus.ACTIVE, ReservationStatus.CONFIRMED}:
            for product_id, quantity in reservation.items.items():
                await repo.change(
                    product_id,
                    delta_on_hand=-quantity,
                    delta_reserved=-quantity,
                    reason=MovementReason.SHIP,
                    ref_id=reservation.id,
                )
            await repo.set_status(reservation.id, ReservationStatus.COMMITTED)

    async def _release(
        self,
        session: AsyncSession,
        reservation: Reservation,
        reason: ReleaseReason,
        cause: OrderStatusChanged | None,
    ) -> None:
        repo = StockRepository(session)
        for product_id, quantity in reservation.items.items():
            await repo.change(
                product_id,
                delta_on_hand=0,
                delta_reserved=-quantity,
                reason=MovementReason.RELEASE,
                ref_id=reservation.id,
            )
        await repo.set_status(reservation.id, ReservationStatus.RELEASED)
        await self._outbox.add(
            session,
            InventoryReleased(
                producer=SERVICE_NAME,
                correlation_id=cause.correlation_id if cause else reservation.order_id,
                payload=InventoryReleasedPayload(
                    order_id=reservation.order_id, reservation_id=reservation.id, reason=reason
                ),
            ),
        )
        RESERVATIONS_RELEASED.labels(str(reason).lower()).inc()
        log.info("reservation_released", order_id=str(reservation.order_id), reason=str(reason))

    # ---------- истечение резервов ----------

    async def expire_reservations(self) -> int:
        """Освобождает просроченные ACTIVE-резервы. Возвращает их количество."""
        async with self._session_factory() as session, session.begin():
            expired = await StockRepository(session).lock_expired(self._now(), EXPIRY_BATCH)
            for reservation in expired:
                await self._release(session, reservation, ReleaseReason.EXPIRED, None)
        return len(expired)

    async def run_expiry_loop(
        self, stop: asyncio.Event, redis: Redis, *, interval_seconds: float
    ) -> None:
        """Задача выполняется одной репликой за раз: блокировка в Redis."""
        while not stop.is_set():
            try:
                async with RedisLock(redis, "inventory:expire-job", ttl_ms=60_000):
                    while await self.expire_reservations() == EXPIRY_BATCH:
                        pass
            except LockNotAcquiredError:
                pass
            except Exception:
                log.exception("reservation_expiry_failed")
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval_seconds)
            except TimeoutError:
                pass

    # ---------- чтение и ручные операции ----------

    async def check_availability(
        self, items: Iterable[tuple[UUID, int]]
    ) -> tuple[bool, dict[UUID, tuple[int, int]]]:
        """Без блокировок и изменений: (всё ли есть, {product_id: (запрошено, доступно)})."""
        requested = merge_quantities(items)
        async with self._session_factory() as session:
            levels = await StockRepository(session).get_many(requested)
        result = {
            pid: (qty, max(levels[pid].available, 0) if pid in levels else 0)
            for pid, qty in requested.items()
        }
        return all(available >= qty for qty, available in result.values()), result

    async def get_stock(self, product_id: UUID) -> StockLevel:
        async with self._session_factory() as session:
            level = await StockRepository(session).get(product_id)
        if level is None:
            raise StockNotFoundError
        return level

    async def adjust(
        self, product_id: UUID, delta: int, *, comment: str, actor: UUID
    ) -> StockLevel:
        async with self._session_factory() as session, session.begin():
            repo = StockRepository(session)
            levels = await repo.lock_many([product_id])
            level = levels.get(product_id)
            if level is None:
                raise StockNotFoundError
            if level.on_hand + delta < level.reserved:
                raise InvalidAdjustmentError
            await repo.change(
                product_id,
                delta_on_hand=delta,
                delta_reserved=0,
                reason=MovementReason.ADJUST,
                ref_id=actor,
                comment=comment,
            )
            updated = await repo.get(product_id)
        log.info("stock_adjusted", product_id=str(product_id), delta=delta)
        if updated is None:
            raise StockNotFoundError
        return updated
