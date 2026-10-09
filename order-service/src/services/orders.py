"""Сценарии заказа и обработчики саги. Каждая смена статуса — запись в истории и
order.status-changed в outbox в одной транзакции."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from events import (
    InventoryReleased,
    InventoryReservationFailed,
    InventoryReserved,
    OrderCreated,
    OrderCreatedPayload,
    OrderItem,
    OrderStatus,
    OrderStatusChanged,
    OrderStatusChangedPayload,
    ReleaseReason,
    Role,
    uuid7,
)
from platform_lib.auth import Principal
from platform_lib.logging import get_logger
from platform_lib.outbox import PgOutbox
from src.domain.errors import (
    DependencyUnavailableError,
    EmailNotVerifiedError,
    ForbiddenActionError,
    IdempotencyConflictError,
    InvalidOrderError,
    OrderNotFoundError,
    OutOfStockError,
    PaymentDeclinedError,
)
from src.domain.models import (
    MAX_ITEMS,
    MAX_QUANTITY,
    Order,
    OrderLine,
    merge_items,
    order_total,
    request_fingerprint,
)
from src.domain.status import Action, InvalidTransitionError, next_status
from src.repositories.orders import OrderRepository
from src.services.ports import CatalogPort, InventoryPort, PaymentGateway

log = get_logger(__name__)

SERVICE_NAME = "order-service"
SAGA_ACTOR = "saga"
STAFF = frozenset({Role.MANAGER, Role.ADMIN})


@dataclass(frozen=True, slots=True)
class CreateResult:
    order: Order
    created: bool  # False — повтор запроса с тем же Idempotency-Key


class OrderService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        outbox: PgOutbox,
        catalog: CatalogPort,
        inventory: InventoryPort,
        payments: PaymentGateway,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._session_factory = session_factory
        self._outbox = outbox
        self._catalog = catalog
        self._inventory = inventory
        self._payments = payments
        self._now = clock

    # ---------- оформление ----------

    async def create(
        self, principal: Principal, items: list[tuple[UUID, int]], idempotency_key: str
    ) -> CreateResult:
        if not principal.email_verified:
            raise EmailNotVerifiedError
        requested = merge_items(items)
        if not 1 <= len(requested) <= MAX_ITEMS:
            raise InvalidOrderError(f"order must contain 1..{MAX_ITEMS} distinct products")
        if any(not 1 <= qty <= MAX_QUANTITY for qty in requested.values()):
            raise InvalidOrderError(f"quantity must be 1..{MAX_QUANTITY}")
        fingerprint = request_fingerprint(requested)

        existing = await self._replay(principal.user_id, idempotency_key, fingerprint)
        if existing is not None:
            return CreateResult(existing, created=False)

        lines, currency = await self._price(requested)
        await self._check_stock(requested)

        now = self._now()
        order = Order(
            id=uuid7(),
            user_id=principal.user_id,
            status=OrderStatus.NEW,
            total_amount=order_total(lines),
            currency=currency,
            lines=tuple(lines),
            cancel_reason=None,
            created_at=now,
            updated_at=now,
        )
        try:
            async with self._session_factory() as session, session.begin():
                repo = OrderRepository(session)
                await repo.insert(order)
                await repo.add_history(
                    order.id,
                    from_status=None,
                    to_status=OrderStatus.NEW,
                    reason=None,
                    actor=str(principal.user_id),
                    at=now,
                )
                await repo.save_idempotency_key(
                    principal.user_id, idempotency_key, fingerprint, order.id, at=now
                )
                await self._outbox.add(session, self._created_event(order))
        except IntegrityError:
            # Параллельный запрос с тем же ключом успел первым
            existing = await self._replay(principal.user_id, idempotency_key, fingerprint)
            if existing is None:
                raise
            return CreateResult(existing, created=False)

        log.info("order_created", order_id=str(order.id), total=str(order.total_amount))
        async with self._session_factory() as session:
            saved = await OrderRepository(session).get(order.id, with_history=True)
        return CreateResult(saved or order, created=True)

    async def _replay(self, user_id: UUID, key: str, fingerprint: str) -> Order | None:
        async with self._session_factory() as session:
            repo = OrderRepository(session)
            found = await repo.find_idempotency_key(user_id, key)
            if found is None:
                return None
            stored_hash, order_id = found
            if stored_hash != fingerprint:
                raise IdempotencyConflictError
            return await repo.get(order_id)

    async def _price(self, requested: dict[UUID, int]) -> tuple[list[OrderLine], str]:
        try:
            products = await self._catalog.get_products(requested)
        except Exception as exc:
            log.warning("catalog_unavailable", error=str(exc))
            raise DependencyUnavailableError from exc
        unavailable = [
            pid for pid in requested if pid not in products or not products[pid].is_published
        ]
        if unavailable:
            raise InvalidOrderError("products are unknown or not for sale", unavailable)
        currencies = {products[pid].currency for pid in requested}
        if len(currencies) != 1:
            raise InvalidOrderError("products have different currencies")
        lines = [
            OrderLine(
                product_id=pid,
                product_name=products[pid].name,
                unit_price=products[pid].price,
                quantity=qty,
            )
            for pid, qty in requested.items()
        ]
        return lines, currencies.pop()

    async def _check_stock(self, requested: dict[UUID, int]) -> None:
        """Быстрый отказ. Если склад недоступен — заказ всё равно создаётся, резерв решит сага."""
        try:
            availability = await self._inventory.check(requested)
        except Exception as exc:
            log.warning("inventory_check_skipped", error=str(exc))
            return
        if not availability.available:
            raise OutOfStockError([item for item in availability.items if item[2] < item[1]])

    @staticmethod
    def _created_event(order: Order) -> OrderCreated:
        return OrderCreated(
            producer=SERVICE_NAME,
            correlation_id=order.id,
            payload=OrderCreatedPayload(
                order_id=order.id,
                user_id=order.user_id,
                items=[
                    OrderItem(
                        product_id=line.product_id,
                        quantity=line.quantity,
                        unit_price=line.unit_price,
                    )
                    for line in order.lines
                ],
                total_amount=order.total_amount,
                currency=order.currency,
            ),
        )

    # ---------- чтение ----------

    async def get(self, principal: Principal, order_id: UUID) -> Order:
        async with self._session_factory() as session:
            order = await OrderRepository(session).get(order_id, with_history=True)
        if order is None or not self._can_see(principal, order):
            raise OrderNotFoundError  # чужой заказ для покупателя «не существует»
        return order

    async def list_orders(
        self,
        principal: Principal,
        *,
        status: OrderStatus | None,
        user_id: UUID | None,
        limit: int,
        offset: int,
    ) -> list[Order]:
        if not principal.has_any(STAFF):
            user_id = principal.user_id
        async with self._session_factory() as session:
            return await OrderRepository(session).list_orders(
                user_id=user_id, status=status, limit=limit, offset=offset
            )

    @staticmethod
    def _can_see(principal: Principal, order: Order) -> bool:
        return order.user_id == principal.user_id or principal.has_any(STAFF)

    # ---------- действия пользователя ----------

    async def pay(self, principal: Principal, order_id: UUID) -> Order:
        declined = False
        async with self._session_factory() as session, session.begin():
            repo = OrderRepository(session)
            order = await self._load_for_update(repo, principal, order_id)
            if order.user_id != principal.user_id:
                raise ForbiddenActionError
            next_status(order.status, Action.PAY)  # 409, если статус не RESERVED
            if order.reserved_until is not None and order.reserved_until <= self._now():
                raise InvalidTransitionError(order.status, Action.PAY)  # резерв уже истёк

            result = await self._payments.charge(order.id, order.total_amount, order.currency)
            await repo.add_payment(
                order.id,
                kind="CHARGE",
                amount=order.total_amount,
                status="SUCCEEDED" if result.success else "DECLINED",
                provider_ref=result.provider_ref or None,
            )
            if result.success:
                await self._change(
                    session, order, Action.PAY, actor=str(principal.user_id), reason=None
                )
            else:
                declined = True  # фиксируем попытку, статус не меняем

        if declined:
            raise PaymentDeclinedError
        return await self.get(principal, order_id)

    async def cancel(self, principal: Principal, order_id: UUID, reason: str | None) -> Order:
        async with self._session_factory() as session, session.begin():
            repo = OrderRepository(session)
            order = await self._load_for_update(repo, principal, order_id)
            is_staff = principal.has_any(STAFF)
            next_status(order.status, Action.CANCEL)
            if order.status is OrderStatus.PAID:
                if not is_staff:
                    raise ForbiddenActionError
                charge_ref = await repo.successful_charge_ref(order.id)
                if charge_ref is not None:
                    refund = await self._payments.refund(
                        charge_ref, order.total_amount, order.currency
                    )
                    await repo.add_payment(
                        order.id,
                        kind="REFUND",
                        amount=order.total_amount,
                        status="SUCCEEDED" if refund.success else "DECLINED",
                        provider_ref=refund.provider_ref,
                    )
                    if not refund.success:
                        raise PaymentDeclinedError
            default_reason = "CANCELLED_BY_STAFF" if is_staff else "CANCELLED_BY_CUSTOMER"
            await self._change(
                session,
                order,
                Action.CANCEL,
                actor=str(principal.user_id),
                reason=reason or default_reason,
            )
        return await self.get(principal, order_id)

    async def ship(self, principal: Principal, order_id: UUID) -> Order:
        return await self._staff_action(principal, order_id, Action.SHIP)

    async def complete(self, principal: Principal, order_id: UUID) -> Order:
        return await self._staff_action(principal, order_id, Action.COMPLETE)

    async def _staff_action(self, principal: Principal, order_id: UUID, action: Action) -> Order:
        if not principal.has_any(STAFF):
            raise ForbiddenActionError
        async with self._session_factory() as session, session.begin():
            order = await self._load_for_update(OrderRepository(session), principal, order_id)
            await self._change(session, order, action, actor=str(principal.user_id), reason=None)
        return await self.get(principal, order_id)

    async def _load_for_update(
        self, repo: OrderRepository, principal: Principal, order_id: UUID
    ) -> Order:
        order = await repo.get(order_id, for_update=True)
        if order is None or not self._can_see(principal, order):
            raise OrderNotFoundError
        return order

    # ---------- сага ----------

    async def on_inventory_reserved(self, event: InventoryReserved, session: AsyncSession) -> None:
        repo = OrderRepository(session)
        order = await repo.get(event.payload.order_id, for_update=True)
        if order is None:
            log.warning("reserved_for_unknown_order", order_id=str(event.payload.order_id))
            return
        if order.status is OrderStatus.NEW:
            await repo.set_reserved_until(order.id, event.payload.expires_at)
            await self._change(session, order, Action.RESERVE, actor=SAGA_ACTOR, reason=None)
        elif order.status is OrderStatus.CANCELLED:
            # Гонка: заказ отменили раньше, чем пришёл резерв. Повторяем отмену,
            # чтобы склад освободил товар.
            await self._publish(
                session,
                order,
                OrderStatus.CANCELLED,
                OrderStatus.CANCELLED,
                reason="RESERVED_AFTER_CANCEL",
            )
            log.info("compensation_release_requested", order_id=str(order.id))

    async def on_reservation_failed(
        self, event: InventoryReservationFailed, session: AsyncSession
    ) -> None:
        repo = OrderRepository(session)
        order = await repo.get(event.payload.order_id, for_update=True)
        if order is not None and order.status is OrderStatus.NEW:
            await self._change(
                session,
                order,
                Action.RESERVATION_FAILED,
                actor=SAGA_ACTOR,
                reason=str(event.payload.reason),
            )

    async def on_inventory_released(self, event: InventoryReleased, session: AsyncSession) -> None:
        if event.payload.reason is not ReleaseReason.EXPIRED:
            return  # освобождение по нашей же отмене — только аудит
        repo = OrderRepository(session)
        order = await repo.get(event.payload.order_id, for_update=True)
        if order is not None and order.status is OrderStatus.RESERVED:
            await self._change(
                session,
                order,
                Action.RESERVATION_EXPIRED,
                actor=SAGA_ACTOR,
                reason="RESERVATION_EXPIRED",
            )

    # ---------- служебное ----------

    async def _change(
        self,
        session: AsyncSession,
        order: Order,
        action: Action,
        *,
        actor: str,
        reason: str | None,
    ) -> None:
        new_status = next_status(order.status, action)
        await OrderRepository(session).set_status(
            order.id,
            from_status=order.status,
            to_status=new_status,
            reason=reason,
            actor=actor,
            at=self._now(),
        )
        await self._publish(session, order, order.status, new_status, reason=reason)
        log.info(
            "order_status_changed",
            order_id=str(order.id),
            old=str(order.status),
            new=str(new_status),
        )

    async def _publish(
        self,
        session: AsyncSession,
        order: Order,
        old: OrderStatus,
        new: OrderStatus,
        *,
        reason: str | None,
    ) -> None:
        await self._outbox.add(
            session,
            OrderStatusChanged(
                producer=SERVICE_NAME,
                correlation_id=order.id,
                payload=OrderStatusChangedPayload(
                    order_id=order.id,
                    user_id=order.user_id,
                    old_status=old,
                    new_status=new,
                    reason=reason,
                    changed_at=self._now(),
                ),
            ),
        )

    async def cleanup_idempotency_keys(self, ttl: timedelta) -> int:
        async with self._session_factory() as session, session.begin():
            return await OrderRepository(session).delete_idempotency_keys_before(self._now() - ttl)
