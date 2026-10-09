from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from events import uuid7
from src.db import reservation_items, reservations, stock, stock_movements
from src.domain.models import MovementReason, ReservationStatus, StockLevel


@dataclass(frozen=True, slots=True)
class Reservation:
    id: UUID
    order_id: UUID
    status: ReservationStatus
    expires_at: datetime
    items: dict[UUID, int]


class StockRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ---------- остатки ----------

    async def ensure_exists(self, product_id: UUID) -> None:
        await self._session.execute(
            pg_insert(stock).values(product_id=product_id).on_conflict_do_nothing()
        )

    async def get(self, product_id: UUID) -> StockLevel | None:
        row = (
            await self._session.execute(select(stock).where(stock.c.product_id == product_id))
        ).first()
        return StockLevel(row.product_id, row.on_hand, row.reserved) if row else None

    async def get_many(self, product_ids: Iterable[UUID]) -> dict[UUID, StockLevel]:
        rows = await self._session.execute(
            select(stock).where(stock.c.product_id.in_(list(product_ids)))
        )
        return {r.product_id: StockLevel(r.product_id, r.on_hand, r.reserved) for r in rows}

    async def lock_many(self, product_ids: Iterable[UUID]) -> dict[UUID, StockLevel]:
        """SELECT ... FOR UPDATE в порядке product_id: одинаковый порядок блокировок
        во всех транзакциях исключает deadlock."""
        ids = sorted(set(product_ids))
        rows = await self._session.execute(
            select(stock)
            .where(stock.c.product_id.in_(ids))
            .order_by(stock.c.product_id)
            .with_for_update()
        )
        return {r.product_id: StockLevel(r.product_id, r.on_hand, r.reserved) for r in rows}

    async def change(
        self,
        product_id: UUID,
        *,
        delta_on_hand: int,
        delta_reserved: int,
        reason: MovementReason,
        ref_id: UUID | None,
        comment: str | None = None,
    ) -> None:
        await self._session.execute(
            update(stock)
            .where(stock.c.product_id == product_id)
            .values(
                on_hand=stock.c.on_hand + delta_on_hand,
                reserved=stock.c.reserved + delta_reserved,
                updated_at=func.now(),
            )
        )
        await self._session.execute(
            insert(stock_movements).values(
                id=uuid7(),
                product_id=product_id,
                delta_on_hand=delta_on_hand,
                delta_reserved=delta_reserved,
                reason=str(reason),
                ref_id=ref_id,
                comment=comment,
            )
        )

    # ---------- резервы ----------

    async def create_reservation(
        self, reservation_id: UUID, order_id: UUID, items: dict[UUID, int], expires_at: datetime
    ) -> None:
        await self._session.execute(
            insert(reservations).values(
                id=reservation_id,
                order_id=order_id,
                status=str(ReservationStatus.ACTIVE),
                expires_at=expires_at,
            )
        )
        await self._session.execute(
            insert(reservation_items),
            [
                {"reservation_id": reservation_id, "product_id": pid, "quantity": qty}
                for pid, qty in items.items()
            ],
        )

    async def reservation_exists(self, order_id: UUID) -> bool:
        found = await self._session.scalar(
            select(reservations.c.id).where(reservations.c.order_id == order_id)
        )
        return found is not None

    async def get_reservation_for_update(self, order_id: UUID) -> Reservation | None:
        row = (
            await self._session.execute(
                select(reservations).where(reservations.c.order_id == order_id).with_for_update()
            )
        ).first()
        return await self._with_items(row) if row else None

    async def lock_expired(self, now: datetime, limit: int) -> list[Reservation]:
        rows = (
            await self._session.execute(
                select(reservations)
                .where(
                    reservations.c.status == str(ReservationStatus.ACTIVE),
                    reservations.c.expires_at <= now,
                )
                .order_by(reservations.c.expires_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        ).all()
        return [await self._with_items(row) for row in rows]

    async def set_status(self, reservation_id: UUID, status: ReservationStatus) -> None:
        await self._session.execute(
            update(reservations)
            .where(reservations.c.id == reservation_id)
            .values(status=str(status), updated_at=func.now())
        )

    async def _with_items(self, row: object) -> Reservation:
        mapping = row._mapping  # type: ignore[attr-defined]
        items = await self._session.execute(
            select(reservation_items.c.product_id, reservation_items.c.quantity).where(
                reservation_items.c.reservation_id == mapping["id"]
            )
        )
        return Reservation(
            id=mapping["id"],
            order_id=mapping["order_id"],
            status=ReservationStatus(mapping["status"]),
            expires_at=mapping["expires_at"],
            items={product_id: quantity for product_id, quantity in items},
        )
