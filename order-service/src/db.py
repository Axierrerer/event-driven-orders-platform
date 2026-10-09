from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    PrimaryKeyConstraint,
    Table,
    Text,
    Uuid,
    func,
)

from platform_lib.db import make_engine, make_session_factory
from platform_lib.outbox import outbox_table, processed_events_table

metadata = MetaData()

MONEY = Numeric(12, 2)

orders = Table(
    "orders",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("user_id", Uuid, nullable=False),
    Column("status", Text, nullable=False),
    Column("total_amount", MONEY, nullable=False),
    Column("currency", Text, nullable=False),
    Column("cancel_reason", Text),
    # Срок резерва из inventory.reserved: оплата после него запрещена
    Column("reserved_until", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint("total_amount >= 0", name="ck_orders_total_non_negative"),
    Index("ix_orders_user_created", "user_id", "created_at"),
    Index("ix_orders_status", "status"),
)

order_items = Table(
    "order_items",
    metadata,
    Column("order_id", Uuid, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False),
    Column("product_id", Uuid, nullable=False),
    Column("product_name", Text, nullable=False),
    Column("unit_price", MONEY, nullable=False),
    Column("quantity", Integer, nullable=False),
    PrimaryKeyConstraint("order_id", "product_id"),
    CheckConstraint("quantity > 0", name="ck_order_items_quantity_positive"),
    CheckConstraint("unit_price >= 0", name="ck_order_items_price_non_negative"),
)

order_status_history = Table(
    "order_status_history",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("order_id", Uuid, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False),
    Column("from_status", Text),
    Column("to_status", Text, nullable=False),
    Column("reason", Text),
    Column("actor", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Index("ix_order_status_history_order", "order_id", "created_at"),
)

idempotency_keys = Table(
    "idempotency_keys",
    metadata,
    Column("user_id", Uuid, nullable=False),
    Column("key", Text, nullable=False),
    Column("request_hash", Text, nullable=False),
    Column("order_id", Uuid, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    PrimaryKeyConstraint("user_id", "key"),
    Index("ix_idempotency_keys_created", "created_at"),
)

payments = Table(
    "payments",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("order_id", Uuid, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False),
    Column("kind", Text, nullable=False),  # CHARGE / REFUND
    Column("amount", MONEY, nullable=False),
    Column("status", Text, nullable=False),  # SUCCEEDED / DECLINED
    Column("provider_ref", Text),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Index("ix_payments_order", "order_id"),
)

outbox = outbox_table(metadata)
processed_events = processed_events_table(metadata)

__all__ = ["make_engine", "make_session_factory", "metadata"]
