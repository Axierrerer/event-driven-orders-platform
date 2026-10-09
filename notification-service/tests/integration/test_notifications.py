import asyncio

import pytest
from httpx import AsyncClient

from events import OrderStatus, Role, uuid7
from platform_lib.testing import TokenFactory
from src.services.rate_limit import BucketConfig, TokenBucket

from ..conftest import (
    World,
    order_created,
    status_changed,
    user_created,
    verification,
)

pytestmark = pytest.mark.integration


async def test_paid_status_sends_one_email(world: World) -> None:
    user = uuid7()
    await world.deliver(user_created(user, "anna@example.com"))
    event = status_changed(user, OrderStatus.PAID)

    await world.deliver(event)
    await world.service.dispatch_once()

    [email] = world.sender.sent
    assert email.to == "anna@example.com"
    assert "оплачен" in email.subject
    assert str(event.payload.order_id) in email.text
    [entry] = await world.journal()
    assert entry["template"] == "order_status_PAID"
    assert entry["status"] == "SENT"
    assert "context" not in entry  # содержимое письма не хранится после отправки


async def test_redelivered_event_sends_nothing_new(world: World) -> None:
    user = uuid7()
    await world.deliver(user_created(user))
    event = status_changed(user, OrderStatus.SHIPPED)

    await world.deliver(event)
    await world.service.dispatch_once()
    await world.deliver(event)
    await world.service.dispatch_once()

    assert len(world.sender.sent) == 1
    assert len(await world.journal()) == 1


async def test_compensation_repeat_of_cancel_is_not_emailed(world: World) -> None:
    user = uuid7()
    await world.deliver(user_created(user))
    await world.deliver(status_changed(user, OrderStatus.CANCELLED, old=OrderStatus.CANCELLED))
    assert await world.journal() == []


async def test_eleventh_email_is_throttled_and_sent_later(world: World) -> None:
    alice, bob = uuid7(), uuid7()
    await world.deliver(user_created(alice, "alice@example.com"))
    await world.deliver(user_created(bob, "bob@example.com"))
    for _ in range(11):
        await world.deliver(order_created(alice))
    await world.deliver(order_created(bob))

    await world.service.dispatch_once()

    to_alice = [e for e in world.sender.sent if e.to == "alice@example.com"]
    assert len(to_alice) == 10
    assert [e.to for e in world.sender.sent].count("bob@example.com") == 1
    [throttled] = await world.journal(status="THROTTLED")
    assert throttled["next_attempt_at"] > throttled["created_at"]

    # окно прошло — отложенное письмо уходит, а не теряется
    await world.redis.delete(f"bucket:user:{alice}")
    world.clock.advance(minutes=2)
    await world.service.dispatch_once()
    assert [e.to for e in world.sender.sent].count("alice@example.com") == 11
    assert await world.journal(status="THROTTLED") == []


async def test_token_bucket_is_atomic_under_concurrency(world: World) -> None:
    bucket = TokenBucket(world.redis)
    config = BucketConfig(capacity=10, refill_seconds=60)
    decisions = await asyncio.gather(*(bucket.take("race", config) for _ in range(100)))
    assert sum(d.allowed for d in decisions) == 10
    assert all(d.retry_after_seconds > 0 for d in decisions if not d.allowed)


async def test_verification_emails_have_their_own_bucket(world: World) -> None:
    user = uuid7()
    for i in range(4):
        await world.deliver(verification(user, f"https://shop.test/verify-email?token=t{i}"))
    await world.service.dispatch_once()
    assert len(world.sender.sent) == 3  # 3 в час
    assert len(await world.journal(status="THROTTLED")) == 1


async def test_smtp_failures_are_retried_then_failed(world: World) -> None:
    user = uuid7()
    await world.deliver(user_created(user))
    await world.deliver(status_changed(user, OrderStatus.COMPLETED))
    world.sender.fail = True

    for _ in range(5):
        await world.service.dispatch_once()
        world.clock.advance(minutes=5)

    [entry] = await world.journal()
    assert entry["status"] == "FAILED"
    assert entry["attempts"] == 5
    assert "ConnectionError" in entry["last_error"]


async def test_smtp_recovers_before_retries_run_out(world: World) -> None:
    user = uuid7()
    await world.deliver(user_created(user))
    await world.deliver(status_changed(user, OrderStatus.COMPLETED))
    world.sender.fail = True
    await world.service.dispatch_once()
    [entry] = await world.journal()
    assert entry["status"] == "RETRY"

    world.sender.fail = False
    await world.service.dispatch_once()  # ещё рано: backoff 5 с
    assert world.sender.sent == []
    world.clock.advance(seconds=6)
    await world.service.dispatch_once()
    assert len(world.sender.sent) == 1


async def test_notification_waits_for_contact(world: World) -> None:
    user = uuid7()
    await world.deliver(order_created(user))  # user.created ещё не пришло
    await world.service.dispatch_once()
    assert world.sender.sent == []
    [entry] = await world.journal()
    assert entry["status"] == "PENDING_CONTACT"

    await world.deliver(user_created(user, "late@example.com"))
    await world.service.dispatch_once()
    assert [e.to for e in world.sender.sent] == ["late@example.com"]


async def test_verification_link_is_sent_and_not_kept(world: World) -> None:
    user = uuid7()
    await world.deliver(verification(user, "https://shop.test/verify-email?token=secret-token"))
    await world.service.dispatch_once()
    [email] = world.sender.sent
    assert "secret-token" in email.html
    [entry] = await world.journal()
    assert "context" not in entry


# ---------- служебный REST ----------


async def test_admin_api(api: AsyncClient, tokens: TokenFactory) -> None:
    admin = tokens.headers(uuid7(), [Role.ADMIN])
    assert (await api.get("/api/v1/notifications", headers=tokens.headers())).status_code == 403
    assert (await api.get("/api/v1/notifications", headers=admin)).json() == []

    keys = (await api.get("/api/v1/notifications/templates", headers=admin)).json()
    assert "order_status_PAID" in keys
    paid = (
        await api.get("/api/v1/notifications/templates/order_status_PAID", headers=admin)
    ).json()
    assert paid["subject"].startswith("Заказ")

    body = {"subject": "Оплачено: {{ order_id }}", "body_html": "<p>ok</p>", "body_text": "ok"}
    saved = await api.put(
        "/api/v1/notifications/templates/order_status_PAID", json=body, headers=admin
    )
    assert saved.status_code == 200
    broken = await api.put(
        "/api/v1/notifications/templates/order_status_PAID",
        json={**body, "subject": "{{ order_id"},
        headers=admin,
    )
    assert broken.status_code == 422
    missing = await api.get("/api/v1/notifications/templates/nope", headers=admin)
    assert missing.status_code == 404
