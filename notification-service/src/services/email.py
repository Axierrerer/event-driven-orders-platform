from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import Protocol

import aiosmtplib


@dataclass(frozen=True, slots=True)
class OutgoingEmail:
    to: str
    subject: str
    html: str
    text: str


class EmailSender(Protocol):
    async def send(self, email: OutgoingEmail) -> None:
        """Отправить письмо; ошибка доставки — исключение."""
        ...


class SmtpEmailSender:
    def __init__(self, host: str, port: int, sender: str, *, timeout_seconds: float) -> None:
        self._host = host
        self._port = port
        self._sender = sender
        self._timeout = timeout_seconds

    async def send(self, email: OutgoingEmail) -> None:
        message = EmailMessage()
        message["From"] = self._sender
        message["To"] = email.to
        message["Subject"] = email.subject
        message.set_content(email.text)
        message.add_alternative(email.html, subtype="html")
        await aiosmtplib.send(message, hostname=self._host, port=self._port, timeout=self._timeout)


@dataclass
class FakeEmailSender:
    """Для тестов: запоминает письма, может имитировать недоступный SMTP."""

    sent: list[OutgoingEmail] = field(default_factory=list)
    fail: bool = False

    async def send(self, email: OutgoingEmail) -> None:
        if self.fail:
            raise ConnectionError("smtp unavailable")
        self.sent.append(email)
