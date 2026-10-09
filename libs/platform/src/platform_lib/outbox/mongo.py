"""Transactional outbox на MongoDB (нужен replica set для транзакций)."""

import asyncio
import time
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from pymongo import ASCENDING, ReturnDocument
from pymongo.errors import DuplicateKeyError

from events import BaseEvent
from platform_lib.logging import get_logger
from platform_lib.metrics import OUTBOX_OLDEST_AGE, OUTBOX_PENDING, OUTBOX_PUBLISHED
from platform_lib.outbox.publisher import EventPublisher
from platform_lib.outbox.records import OutboxRecord, record_from_event

log = get_logger(__name__)


async def ensure_outbox_indexes(outbox: Any) -> None:
    await outbox.create_index(
        [("published_at", ASCENDING), ("created_at", ASCENDING), ("_id", ASCENDING)],
        name="ix_outbox_unpublished",
    )


class MongoOutbox:
    def __init__(self, collection: Any) -> None:
        self._collection = collection

    async def add(
        self,
        event: BaseEvent,
        *,
        session: Any,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        """Записать событие в outbox в транзакции `session` вызывающего."""
        record = record_from_event(event, headers)
        await self._collection.insert_one(
            {
                "_id": str(record.id),
                "topic": record.topic,
                "key": record.key,
                "event_type": record.event_type,
                "payload": record.payload,
                "headers": record.headers,
                "created_at": datetime.now(UTC),
                "published_at": None,
                "attempts": 0,
                "last_error": None,
            },
            session=session,
        )


class MongoOutboxRelay:
    """Публикует записи outbox. Работает один relay — по аренде (lease) в коллекции leases."""

    def __init__(
        self,
        outbox: Any,
        leases: Any,
        publisher: EventPublisher,
        *,
        owner_id: str,
        lease_name: str = "outbox-relay",
        lease_seconds: float = 15.0,
        batch_size: int = 100,
        poll_interval_seconds: float = 0.5,
    ) -> None:
        self._outbox = outbox
        self._leases = leases
        self._publisher = publisher
        self._owner = owner_id
        self._lease_name = lease_name
        self._lease = timedelta(seconds=lease_seconds)
        self._batch_size = batch_size
        self._poll_interval = poll_interval_seconds

    async def _acquire_lease(self) -> bool:
        now = datetime.now(UTC)
        try:
            doc = await self._leases.find_one_and_update(
                {
                    "_id": self._lease_name,
                    "$or": [{"until": {"$lt": now}}, {"owner": self._owner}],
                },
                {"$set": {"owner": self._owner, "until": now + self._lease}},
                upsert=True,
                return_document=ReturnDocument.AFTER,
            )
        except DuplicateKeyError:
            return False  # аренду держит другой relay
        return doc is not None and doc.get("owner") == self._owner

    async def run_once(self) -> int:
        if not await self._acquire_lease():
            return 0
        docs = (
            await self._outbox.find({"published_at": None})
            .sort([("created_at", ASCENDING), ("_id", ASCENDING)])
            .limit(self._batch_size)
            .to_list(self._batch_size)
        )
        if not docs:
            return 0
        records = [
            OutboxRecord(
                id=UUID(doc["_id"]),
                topic=doc["topic"],
                key=doc["key"],
                event_type=doc["event_type"],
                payload=doc["payload"],
                headers=doc.get("headers") or {},
            )
            for doc in docs
        ]
        results = await self._publisher.publish(records)

        published = [str(r.id) for r, error in zip(records, results, strict=True) if error is None]
        if published:
            await self._outbox.update_many(
                {"_id": {"$in": published}}, {"$set": {"published_at": datetime.now(UTC)}}
            )
        for record, error in zip(records, results, strict=True):
            if error is not None:
                log.warning("outbox_publish_failed", event_id=str(record.id), error=error)
                await self._outbox.update_one(
                    {"_id": str(record.id)},
                    {"$inc": {"attempts": 1}, "$set": {"last_error": error[:2000]}},
                )
        return len(published)

    async def report_metrics(self) -> None:
        pending = await self._outbox.count_documents({"published_at": None})
        oldest = await self._outbox.find_one(
            {"published_at": None}, sort=[("created_at", ASCENDING)], projection={"created_at": 1}
        )
        OUTBOX_PENDING.set(pending)
        age = 0.0
        if oldest:
            created = oldest["created_at"]
            if created.tzinfo is None:
                created = created.replace(tzinfo=UTC)
            age = (datetime.now(UTC) - created).total_seconds()
        OUTBOX_OLDEST_AGE.set(age)

    async def run_forever(self, stop: asyncio.Event) -> None:
        reported_at = 0.0
        while not stop.is_set():
            try:
                published = await self.run_once()
                OUTBOX_PUBLISHED.inc(published)
                if time.monotonic() - reported_at > 5.0:
                    await self.report_metrics()
                    reported_at = time.monotonic()
            except Exception:
                log.exception("outbox_relay_iteration_failed")
                published = 0
            if published == 0:
                try:
                    await asyncio.wait_for(stop.wait(), timeout=self._poll_interval)
                except TimeoutError:
                    pass
