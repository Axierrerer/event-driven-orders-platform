"""Тестовые двойники для consumer и outbox."""

import asyncio
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from platform_lib.outbox import OutboxRecord


@dataclass
class FakeMessage:
    topic_name: str
    payload: bytes | None = b"{}"
    message_key: bytes | None = b"key"
    message_headers: list[tuple[str, bytes]] | None = None
    partition_no: int = 0
    offset_no: int = 0

    def topic(self) -> str | None:
        return self.topic_name

    def key(self) -> bytes | None:
        return self.message_key

    def value(self) -> bytes | None:
        return self.payload

    def headers(self) -> Any:
        return self.message_headers

    def partition(self) -> int | None:
        return self.partition_no

    def offset(self) -> int | None:
        return self.offset_no


@dataclass
class FakeTx:
    marks: set[tuple[UUID, str]] = field(default_factory=set)
    effects: list[Any] = field(default_factory=list)


class FakeInbox:
    """Транзакционная семантика: изменения применяются, только если блок завершился без ошибки."""

    def __init__(self) -> None:
        self.processed: set[tuple[UUID, str]] = set()
        self.effects: list[Any] = []

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[FakeTx]:
        tx = FakeTx()
        yield tx
        self.processed |= tx.marks
        self.effects.extend(tx.effects)

    async def mark_processed(self, tx: FakeTx, event_id: UUID, consumer_group: str) -> bool:
        if (event_id, consumer_group) in self.processed:
            return False
        tx.marks.add((event_id, consumer_group))
        return True


class FakeDeadLetters:
    def __init__(self) -> None:
        self.sent: list[tuple[str | None, str]] = []

    async def send(self, message: Any, error: str) -> None:
        self.sent.append((message.topic(), error))


class FakePublisher:
    """Публикатор: запоминает опубликованное; может падать на выбранных записях."""

    def __init__(self, *, fail_ids: set[UUID] | None = None, delay: float = 0.0) -> None:
        self.published: list[OutboxRecord] = []
        self.fail_ids = fail_ids or set()
        self.delay = delay
        self.calls = 0

    async def publish(self, records: Sequence[OutboxRecord]) -> list[str | None]:
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        results: list[str | None] = []
        for record in records:
            if record.id in self.fail_ids:
                results.append("broker unavailable")
            else:
                self.published.append(record)
                results.append(None)
        return results


async def no_sleep(_seconds: float) -> None:
    return None
