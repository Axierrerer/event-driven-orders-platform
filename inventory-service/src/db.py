from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    PrimaryKeyConstraint,
    Table,
    Text,
    Uuid,
    func,
    text,
)

from platform_lib.db import make_engine, make_session_factory
from platform_lib.outbox import outbox_table, processed_events_table

metadata = MetaData()

stock = Table(
    "stock",
    metadata,
    Column("product_id", Uuid, primary_key=True),
    Column("on_hand", Integer, nullable=False, server_default=text("0")),
    Column("reserved", Integer, nullable=False, server_default=text("0")),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint("on_hand >= 0", name="ck_stock_on_hand_non_negative"),
    CheckConstraint("reserved >= 0", name="ck_stock_reserved_non_negative"),
    CheckConstraint("reserved <= on_hand", name="ck_stock_reserved_le_on_hand"),
)

reservations = Table(
    "reservations",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("order_id", Uuid, nullable=False, unique=True),
    Column("status", Text, nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    # Задача истечения ищет ACTIVE-резервы по сроку
    Index(
        "ix_reservations_active_expiry", "expires_at", postgresql_where=text("status = 'ACTIVE'")
    ),
)

reservation_items = Table(
    "reservation_items",
    metadata,
    Column(
        "reservation_id", Uuid, ForeignKey("reservations.id", ondelete="CASCADE"), nullable=False
    ),
    Column("product_id", Uuid, nullable=False),
    Column("quantity", Integer, nullable=False),
    PrimaryKeyConstraint("reservation_id", "product_id"),
    CheckConstraint("quantity > 0", name="ck_reservation_items_quantity_positive"),
)

stock_movements = Table(
    "stock_movements",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("product_id", Uuid, nullable=False),
    Column("delta_on_hand", Integer, nullable=False),
    Column("delta_reserved", Integer, nullable=False),
    Column("reason", Text, nullable=False),
    Column("ref_id", Uuid),  # резерв или сотрудник, выполнивший корректировку
    Column("comment", Text),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Index("ix_stock_movements_product", "product_id", "created_at"),
)

outbox = outbox_table(metadata)
processed_events = processed_events_table(metadata)

__all__ = ["make_engine", "make_session_factory", "metadata"]
