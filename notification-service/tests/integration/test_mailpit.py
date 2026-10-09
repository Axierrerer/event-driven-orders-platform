"""Письмо доходит до настоящего SMTP-сервера (Mailpit в testcontainers)."""

import time
from collections.abc import Iterator

import httpx
import pytest
from testcontainers.core.container import DockerContainer

from src.services.email import OutgoingEmail, SmtpEmailSender

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def mailpit() -> Iterator[tuple[int, str]]:
    container = DockerContainer("axllent/mailpit:v1.21").with_exposed_ports(1025, 8025)
    with container:
        host = container.get_container_host_ip()
        api = f"http://{host}:{container.get_exposed_port(8025)}"
        deadline = time.monotonic() + 30
        while True:
            try:
                httpx.get(f"{api}/api/v1/messages", timeout=1).raise_for_status()
                break
            except httpx.HTTPError:
                if time.monotonic() > deadline:
                    raise
                time.sleep(0.3)
        yield int(container.get_exposed_port(1025)), api


async def test_email_is_delivered_to_mailpit(mailpit: tuple[int, str]) -> None:
    smtp_port, api = mailpit
    sender = SmtpEmailSender(
        "localhost", smtp_port, "Orders <no-reply@orders.local>", timeout_seconds=5
    )
    await sender.send(
        OutgoingEmail(
            to="buyer@example.com",
            subject="Заказ оформлен",
            html="<p>Спасибо!</p>",
            text="Спасибо!",
        )
    )

    async with httpx.AsyncClient() as client:
        messages = (await client.get(f"{api}/api/v1/messages")).json()["messages"]
    assert messages[0]["Subject"] == "Заказ оформлен"
    assert messages[0]["To"][0]["Address"] == "buyer@example.com"
