from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    MetaData,
    PrimaryKeyConstraint,
    Table,
    Text,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB

from platform_lib.db import make_engine, make_session_factory
from platform_lib.outbox import outbox_table, processed_events_table

metadata = MetaData()

users = Table(
    "users",
    metadata,
    Column("id", Uuid, primary_key=True),  # совпадает с id в auth-service
    Column("email", Text, nullable=False),
    Column("full_name", Text),
    Column("phone", Text),
    Column("address", JSONB),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("deleted_at", DateTime(timezone=True)),
    Index("ix_users_email", "email"),
)

user_roles = Table(
    "user_roles",
    metadata,
    Column("user_id", Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("role", Text, nullable=False),
    Column("granted_by", Uuid),
    Column("granted_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    PrimaryKeyConstraint("user_id", "role"),
    Index("ix_user_roles_role", "role"),
)

outbox = outbox_table(metadata)
processed_events = processed_events_table(metadata)

__all__ = ["make_engine", "make_session_factory", "metadata"]
