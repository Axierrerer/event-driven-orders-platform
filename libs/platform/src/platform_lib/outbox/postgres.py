"""Transactional outbox на PostgreSQL.

Сервис пишет событие через `PgOutbox.add` в той же сессии (транзакции), что и
изменение данных. `PgOutboxRelay` в фоне публикует накопленные записи в Kafka.
"""

import asyncio
import zlib
from collections.abc import Mapping
from datetime import UTC, datetime

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Identity,
    Index,
    Integer,
    MetaData,
    PrimaryKeyConstraint,
    Table,
    Text,
    Uuid,
    func,
    insert,
    select,
    text,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from events import BaseEvent
from platform_lib.logging import get_logger
from platform_lib.outbox.publisher import EventPublisher
from platform_lib.outbox.records import OutboxRecord, record_from_event

log = get_logger(__name__)


def outbox_table(metadata: MetaData) -> Table:
    return Table(
        "outbox",
        metadata,
        Column("id", Uuid, primary_key=True),
        # Порядок вставки: события одной транзакции получают одинаковый created_at
        Column("seq", BigInteger, Identity(always=True), nullable=False, unique=True),
        Column("topic", Text, nullable=False),
        Column("key", Text, nullable=False),
        Column("event_type", Text, nullable=False),
        Column("payload", JSONB, nullable=False),
        Column("headers", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
        Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
        Column("published_at", DateTime(timezone=True)),
        Column("attempts", Integer, nullable=False, server_default=text("0")),
        Column("last_error", Text),
        Index(
            "ix_outbox_unpublished",
            "seq",
            postgresql_where=text("published_at IS NULL"),
        ),
    )


def processed_events_table(metadata: MetaData) -> Table:
    return Table(
        "processed_events",
        metadata,
        Column("event_id", Uuid, nullable=False),
        Column("consumer_group", Text, nullable=False),
        Column("processed_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
        PrimaryKeyConstraint("event_id", "consumer_group"),
    )


class PgOutbox:
    def __init__(self, table: Table) -> None:
        self._table = table

    async def add(
        self,
        session: AsyncSession,
        event: BaseEvent,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        """Записать событие в outbox. Коммит — вместе с бизнес-транзакцией вызывающего."""
        record = record_from_event(event, headers)
        await session.execute(
            insert(self._table).values(
                id=record.id,
                topic=record.topic,
                key=record.key,
                event_type=record.event_type,
                payload=record.payload,
                headers=record.headers,
            )
        )


class PgOutboxRelay:
    """Публикует неотправленные записи outbox по порядку создания.

    Одновременно работает только один relay на таблицу (pg_try_advisory_xact_lock):
    так сохраняется порядок событий одного ключа при нескольких репликах сервиса.
    Если сервис упадёт между отправкой и отметкой `published_at`, событие уйдёт повторно —
    дубль гасит идемпотентный consumer.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        table: Table,
        publisher: EventPublisher,
        *,
        batch_size: int = 100,
        poll_interval_seconds: float = 0.5,
    ) -> None:
        self._session_factory = session_factory
        self._table = table
        self._publisher = publisher
        self._batch_size = batch_size
        self._poll_interval = poll_interval_seconds
        self._lock_key = zlib.crc32(f"outbox-relay:{table.name}".encode())

    async def run_once(self) -> int:
        """Один проход. Возвращает число опубликованных записей."""
        t = self._table
        async with self._session_factory() as session, session.begin():
            locked = await session.scalar(select(func.pg_try_advisory_xact_lock(self._lock_key)))
            if not locked:
                return 0

            rows = (
                await session.execute(
                    select(t)
                    .where(t.c.published_at.is_(None))
                    .order_by(t.c.seq)
                    .limit(self._batch_size)
                    .with_for_update(skip_locked=True)
                )
            ).mappings()
            records = [
                OutboxRecord(
                    id=row["id"],
                    topic=row["topic"],
                    key=row["key"],
                    event_type=row["event_type"],
                    payload=row["payload"],
                    headers=row["headers"],
                )
                for row in rows
            ]
            if not records:
                return 0

            results = await self._publisher.publish(records)

            published = [r.id for r, error in zip(records, results, strict=True) if error is None]
            if published:
                await session.execute(
                    update(t).where(t.c.id.in_(published)).values(published_at=datetime.now(UTC))
                )
            for record, error in zip(records, results, strict=True):
                if error is not None:
                    log.warning("outbox_publish_failed", event_id=str(record.id), error=error)
                    await session.execute(
                        update(t)
                        .where(t.c.id == record.id)
                        .values(attempts=t.c.attempts + 1, last_error=error[:2000])
                    )
            return len(published)

    async def pending_count(self) -> int:
        t = self._table
        async with self._session_factory() as session:
            count = await session.scalar(
                select(func.count()).select_from(t).where(t.c.published_at.is_(None))
            )
        return int(count or 0)

    async def run_forever(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                published = await self.run_once()
            except Exception:
                log.exception("outbox_relay_iteration_failed")
                published = 0
            if published == 0:
                try:
                    await asyncio.wait_for(stop.wait(), timeout=self._poll_interval)
                except TimeoutError:
                    pass
