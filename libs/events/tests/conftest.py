from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from events import (
    AuthProvider,
    BaseEvent,
    InventoryReleased,
    InventoryReleasedPayload,
    InventoryReservationFailed,
    InventoryReservationFailedPayload,
    InventoryReserved,
    InventoryReservedPayload,
    MissingItem,
    OrderCreated,
    OrderCreatedPayload,
    OrderItem,
    OrderStatus,
    OrderStatusChanged,
    OrderStatusChangedPayload,
    ProductChanged,
    ProductChangedPayload,
    ReleaseReason,
    ReservationFailureReason,
    ReservedItem,
    Role,
    UserCreated,
    UserCreatedPayload,
    UserRolesChanged,
    UserRolesChangedPayload,
    UserVerificationRequested,
    UserVerificationRequestedPayload,
)

USER_ID = UUID("0192f0a0-0000-7000-8000-000000000001")
ADMIN_ID = UUID("0192f0a0-0000-7000-8000-000000000002")
PRODUCT_ID = UUID("0192f0a0-0000-7000-8000-000000000003")
ORDER_ID = UUID("0192f0a0-0000-7000-8000-000000000004")
RESERVATION_ID = UUID("0192f0a0-0000-7000-8000-000000000005")
NOW = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)


def sample_events() -> list[BaseEvent]:
    """По одному корректному событию каждого типа."""
    common = {"producer": "test", "correlation_id": ORDER_ID, "occurred_at": NOW}
    return [
        UserCreated(
            **common,
            payload=UserCreatedPayload(
                user_id=USER_ID,
                email="user@example.com",
                created_at=NOW,
                auth_provider=AuthProvider.PASSWORD,
            ),
        ),
        UserVerificationRequested(
            **common,
            payload=UserVerificationRequestedPayload(
                user_id=USER_ID,
                email="user@example.com",
                verification_url="https://shop.example.com/verify?token=abc",
                expires_at=NOW + timedelta(hours=24),
            ),
        ),
        UserRolesChanged(
            **common,
            payload=UserRolesChangedPayload(
                user_id=USER_ID, roles=[Role.USER, Role.MANAGER], changed_by=ADMIN_ID
            ),
        ),
        ProductChanged(
            **common,
            payload=ProductChangedPayload(
                product_id=PRODUCT_ID,
                sku="SKU-1",
                name="Кружка",
                price=Decimal("10.10"),
                currency="RUB",
                is_published=True,
                is_deleted=False,
            ),
        ),
        OrderCreated(
            **common,
            payload=OrderCreatedPayload(
                order_id=ORDER_ID,
                user_id=USER_ID,
                items=[OrderItem(product_id=PRODUCT_ID, quantity=3, unit_price=Decimal("0.10"))],
                total_amount=Decimal("0.30"),
                currency="RUB",
            ),
        ),
        InventoryReserved(
            **common,
            payload=InventoryReservedPayload(
                order_id=ORDER_ID,
                reservation_id=RESERVATION_ID,
                items=[ReservedItem(product_id=PRODUCT_ID, quantity=3)],
                expires_at=NOW + timedelta(minutes=15),
            ),
        ),
        InventoryReservationFailed(
            **common,
            payload=InventoryReservationFailedPayload(
                order_id=ORDER_ID,
                reason=ReservationFailureReason.OUT_OF_STOCK,
                missing=[MissingItem(product_id=PRODUCT_ID, requested=3, available=1)],
            ),
        ),
        InventoryReleased(
            **common,
            payload=InventoryReleasedPayload(
                order_id=ORDER_ID,
                reservation_id=RESERVATION_ID,
                reason=ReleaseReason.EXPIRED,
            ),
        ),
        OrderStatusChanged(
            **common,
            payload=OrderStatusChangedPayload(
                order_id=ORDER_ID,
                user_id=USER_ID,
                old_status=OrderStatus.NEW,
                new_status=OrderStatus.RESERVED,
                changed_at=NOW,
            ),
        ),
    ]
