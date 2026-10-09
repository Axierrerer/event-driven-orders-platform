"""Уведомления.

Обработчики событий только записывают задание в журнал (в транзакции consumer’а) —
отправкой занимается диспетчер. Поэтому недоступный SMTP не блокирует чтение Kafka.
"""

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from events import (
    BaseEvent,
    OrderCreated,
    OrderStatusChanged,
    UserCreated,
    UserVerificationRequested,
)
from platform_lib.logging import get_logger
from platform_lib.ratelimit import BucketConfig, TokenBucket
from src.domain.models import (
    Bucket,
    Notification,
    NotificationStatus,
    backoff_seconds,
    order_status_template,
)
from src.domain.templates import TemplateRenderError, render
from src.repositories.contacts import ContactRepository
from src.repositories.journal import JournalRepository
from src.repositories.templates import TemplateRepository
from src.services.email import EmailSender, OutgoingEmail

log = get_logger(__name__)

CLAIM_LEASE = timedelta(seconds=60)


class NotificationService:
    def __init__(
        self,
        db: Any,
        sender: EmailSender,
        buckets: TokenBucket,
        *,
        user_bucket: BucketConfig,
        verification_bucket: BucketConfig,
        max_attempts: int = 5,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._journal = JournalRepository(db)
        self._contacts = ContactRepository(db)
        self._templates = TemplateRepository(db)
        self._sender = sender
        self._buckets = buckets
        self._bucket_configs = {Bucket.USER: user_bucket, Bucket.VERIFICATION: verification_bucket}
        self._max_attempts = max_attempts
        self._now = clock

    # ---------- события (в транзакции consumer’а) ----------

    async def on_user_created(self, event: UserCreated, session: Any) -> None:
        payload = event.payload
        await self._contacts.upsert(payload.user_id, payload.email, session=session)
        released = await self._journal.attach_contact(
            payload.user_id, payload.email, self._now(), session=session
        )
        if released:
            log.info("pending_notifications_released", user_id=str(payload.user_id), count=released)

    async def on_verification_requested(
        self, event: UserVerificationRequested, session: Any
    ) -> None:
        payload = event.payload
        await self._enqueue(
            event,
            session,
            user_id=payload.user_id,
            email=payload.email,
            template="email_verification",
            bucket=Bucket.VERIFICATION,
            context={
                "verification_url": payload.verification_url,
                "expires_at": payload.expires_at.strftime("%d.%m.%Y %H:%M UTC"),
            },
        )

    async def on_order_created(self, event: OrderCreated, session: Any) -> None:
        payload = event.payload
        await self._enqueue(
            event,
            session,
            user_id=payload.user_id,
            email=await self._contacts.email_of(payload.user_id, session=session),
            template="order_created",
            bucket=Bucket.USER,
            context={
                "order_id": str(payload.order_id),
                "items_count": sum(item.quantity for item in payload.items),
                "total_amount": f"{payload.total_amount:.2f}",
                "currency": payload.currency,
            },
        )

    async def on_order_status_changed(self, event: OrderStatusChanged, session: Any) -> None:
        payload = event.payload
        if payload.old_status == payload.new_status:
            return  # служебное повторение отмены для склада — письмо уже отправлено
        await self._enqueue(
            event,
            session,
            user_id=payload.user_id,
            email=await self._contacts.email_of(payload.user_id, session=session),
            template=order_status_template(str(payload.new_status)),
            bucket=Bucket.USER,
            context={
                "order_id": str(payload.order_id),
                "new_status": str(payload.new_status),
                "reason": payload.reason,
            },
        )

    async def _enqueue(
        self,
        event: BaseEvent,
        session: Any,
        *,
        user_id: UUID,
        email: str | None,
        template: str,
        bucket: Bucket,
        context: dict[str, Any],
    ) -> None:
        now = self._now()
        notification = Notification(
            id=str(event.event_id),
            user_id=user_id,
            email=email,
            template=template,
            bucket=bucket,
            status=NotificationStatus.PENDING if email else NotificationStatus.PENDING_CONTACT,
            attempts=0,
            next_attempt_at=now,
            created_at=now,
            context=context,
        )
        if await self._journal.add(notification, session=session):
            log.info(
                "notification_enqueued",
                notification_id=notification.id,
                template=template,
                status=str(notification.status),
            )

    # ---------- отправка ----------

    async def dispatch_once(self, limit: int = 100) -> int:
        """Обработать готовые уведомления. Возвращает число обработанных."""
        processed = 0
        while processed < limit:
            notification = await self._journal.claim_due(self._now(), CLAIM_LEASE)
            if notification is None:
                break
            await self._deliver(notification)
            processed += 1
        return processed

    async def _deliver(self, notification: Notification) -> None:
        now = self._now()
        bucket_key = f"{notification.bucket}:{notification.user_id}"
        decision = await self._buckets.take(bucket_key, self._bucket_configs[notification.bucket])
        if not decision.allowed:
            await self._journal.postpone(
                notification.id,
                NotificationStatus.THROTTLED,
                now + timedelta(seconds=max(decision.retry_after_seconds, 1)),
            )
            log.info("notification_throttled", notification_id=notification.id)
            return

        template = await self._templates.get(notification.template)
        if template is None or notification.email is None or notification.context is None:
            await self._journal.mark_failed(
                notification.id,
                f"template {notification.template!r} is missing",
                notification.attempts,
            )
            log.error("notification_template_missing", template=notification.template)
            return
        try:
            subject, html, text = render(template, notification.context)
        except TemplateRenderError as exc:
            await self._journal.mark_failed(
                notification.id, f"render: {exc}", notification.attempts
            )
            return

        attempts = notification.attempts + 1
        try:
            await self._sender.send(OutgoingEmail(notification.email, subject, html, text))
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            if attempts >= self._max_attempts:
                await self._journal.mark_failed(notification.id, error, attempts)
                log.error("notification_failed", notification_id=notification.id, attempts=attempts)
            else:
                await self._journal.postpone(
                    notification.id,
                    NotificationStatus.RETRY,
                    now + timedelta(seconds=backoff_seconds(attempts)),
                    error=error,
                    attempts=attempts,
                )
                log.warning(
                    "notification_retry", notification_id=notification.id, attempts=attempts
                )
            return

        await self._journal.mark_sent(notification.id, now)
        log.info(
            "notification_sent", notification_id=notification.id, template=notification.template
        )

    async def run_dispatcher(self, stop: asyncio.Event, *, interval_seconds: float) -> None:
        while not stop.is_set():
            try:
                await self.dispatch_once()
            except Exception:
                log.exception("notification_dispatch_failed")
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval_seconds)
            except TimeoutError:
                pass
