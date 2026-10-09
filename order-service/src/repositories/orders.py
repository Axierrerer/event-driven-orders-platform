from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from events import OrderStatus, uuid7
from src.db import idempotency_keys, order_items, order_status_history, orders, payments
from src.domain.models import Order, OrderLine, StatusChange


class OrderRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def insert(self, order: Order) -> None:
        await self._session.execute(
            insert(orders).values(
                id=order.id,
                user_id=order.user_id,
                status=str(order.status),
                total_amount=order.total_amount,
                currency=order.currency,
                created_at=order.created_at,
                updated_at=order.updated_at,
            )
        )
        await self._session.execute(
            insert(order_items),
            [
                {
                    "order_id": order.id,
                    "product_id": line.product_id,
                    "product_name": line.product_name,
                    "unit_price": line.unit_price,
                    "quantity": line.quantity,
                }
                for line in order.lines
            ],
        )

    async def get(
        self, order_id: UUID, *, for_update: bool = False, with_history: bool = False
    ) -> Order | None:
        query = select(orders).where(orders.c.id == order_id)
        if for_update:
            query = query.with_for_update()
        row = (await self._session.execute(query)).mappings().first()
        if row is None:
            return None
        lines = await self._lines([order_id])
        history = await self._history(order_id) if with_history else ()
        return self._order(row, lines.get(order_id, ()), history)

    async def list_orders(
        self,
        *,
        user_id: UUID | None,
        status: OrderStatus | None,
        limit: int,
        offset: int,
    ) -> list[Order]:
        query = select(orders)
        if user_id is not None:
            query = query.where(orders.c.user_id == user_id)
        if status is not None:
            query = query.where(orders.c.status == str(status))
        query = query.order_by(orders.c.created_at.desc(), orders.c.id.desc())
        rows = (await self._session.execute(query.limit(limit).offset(offset))).mappings().all()
        lines = await self._lines([row["id"] for row in rows])
        return [self._order(row, lines.get(row["id"], ()), ()) for row in rows]

    async def set_status(
        self,
        order_id: UUID,
        *,
        from_status: OrderStatus | None,
        to_status: OrderStatus,
        reason: str | None,
        actor: str,
        at: datetime,
    ) -> None:
        values: dict[str, Any] = {"status": str(to_status), "updated_at": at}
        if to_status is OrderStatus.CANCELLED:
            values["cancel_reason"] = reason
        await self._session.execute(update(orders).where(orders.c.id == order_id).values(**values))
        await self.add_history(
            order_id,
            from_status=from_status,
            to_status=to_status,
            reason=reason,
            actor=actor,
            at=at,
        )

    async def set_reserved_until(self, order_id: UUID, until: datetime) -> None:
        await self._session.execute(
            update(orders).where(orders.c.id == order_id).values(reserved_until=until)
        )

    async def add_history(
        self,
        order_id: UUID,
        *,
        from_status: OrderStatus | None,
        to_status: OrderStatus,
        reason: str | None,
        actor: str,
        at: datetime,
    ) -> None:
        await self._session.execute(
            insert(order_status_history).values(
                id=uuid7(),
                order_id=order_id,
                from_status=str(from_status) if from_status else None,
                to_status=str(to_status),
                reason=reason,
                actor=actor,
                created_at=at,
            )
        )

    # ---------- идемпотентность ----------

    async def find_idempotency_key(self, user_id: UUID, key: str) -> tuple[str, UUID] | None:
        row = (
            await self._session.execute(
                select(idempotency_keys.c.request_hash, idempotency_keys.c.order_id).where(
                    idempotency_keys.c.user_id == user_id, idempotency_keys.c.key == key
                )
            )
        ).first()
        return (row.request_hash, row.order_id) if row else None

    async def save_idempotency_key(
        self, user_id: UUID, key: str, request_hash: str, order_id: UUID, *, at: datetime
    ) -> None:
        await self._session.execute(
            insert(idempotency_keys).values(
                user_id=user_id,
                key=key,
                request_hash=request_hash,
                order_id=order_id,
                created_at=at,
            )
        )

    async def delete_idempotency_keys_before(self, moment: datetime) -> int:
        result = await self._session.execute(
            delete(idempotency_keys).where(idempotency_keys.c.created_at < moment)
        )
        return int(getattr(result, "rowcount", 0) or 0)

    # ---------- платежи ----------

    async def add_payment(
        self,
        order_id: UUID,
        *,
        kind: str,
        amount: Decimal,
        status: str,
        provider_ref: str | None,
    ) -> None:
        await self._session.execute(
            insert(payments).values(
                id=uuid7(),
                order_id=order_id,
                kind=kind,
                amount=amount,
                status=status,
                provider_ref=provider_ref,
            )
        )

    async def successful_charge_ref(self, order_id: UUID) -> str | None:
        ref = await self._session.scalar(
            select(payments.c.provider_ref)
            .where(
                payments.c.order_id == order_id,
                payments.c.kind == "CHARGE",
                payments.c.status == "SUCCEEDED",
            )
            .order_by(payments.c.created_at.desc())
            .limit(1)
        )
        return str(ref) if ref else None

    async def count_in_status_before(self, status: OrderStatus, moment: datetime) -> int:
        return int(
            await self._session.scalar(
                select(func.count())
                .select_from(orders)
                .where(orders.c.status == str(status), orders.c.created_at < moment)
            )
            or 0
        )

    async def count(self) -> int:
        return int(await self._session.scalar(select(func.count()).select_from(orders)) or 0)

    # ---------- чтение ----------

    async def _lines(self, order_ids: list[UUID]) -> dict[UUID, tuple[OrderLine, ...]]:
        if not order_ids:
            return {}
        rows = await self._session.execute(
            select(order_items).where(order_items.c.order_id.in_(order_ids))
        )
        result: dict[UUID, list[OrderLine]] = {}
        for row in rows.mappings():
            result.setdefault(row["order_id"], []).append(
                OrderLine(
                    product_id=row["product_id"],
                    product_name=row["product_name"],
                    unit_price=row["unit_price"],
                    quantity=row["quantity"],
                )
            )
        return {order_id: tuple(lines) for order_id, lines in result.items()}

    async def _history(self, order_id: UUID) -> tuple[StatusChange, ...]:
        rows = await self._session.execute(
            select(order_status_history)
            .where(order_status_history.c.order_id == order_id)
            .order_by(order_status_history.c.created_at, order_status_history.c.id)
        )
        return tuple(
            StatusChange(
                from_status=OrderStatus(r["from_status"]) if r["from_status"] else None,
                to_status=OrderStatus(r["to_status"]),
                reason=r["reason"],
                actor=r["actor"],
                created_at=r["created_at"],
            )
            for r in rows.mappings()
        )

    @staticmethod
    def _order(row: Any, lines: tuple[OrderLine, ...], history: tuple[StatusChange, ...]) -> Order:
        return Order(
            id=row["id"],
            user_id=row["user_id"],
            status=OrderStatus(row["status"]),
            total_amount=row["total_amount"],
            currency=row["currency"],
            lines=lines,
            cancel_reason=row["cancel_reason"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            reserved_until=row["reserved_until"],
            history=history,
        )
