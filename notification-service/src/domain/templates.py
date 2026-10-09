"""Шаблоны писем по умолчанию и их рендеринг.

Шаблоны редактирует администратор, поэтому рендеринг идёт в песочнице Jinja2,
а HTML-версия — с автоэкранированием (данные пользователя не превращаются в разметку).
"""

from typing import Any

from jinja2 import StrictUndefined, TemplateError
from jinja2.sandbox import SandboxedEnvironment

from src.domain.models import EmailTemplate

_html = SandboxedEnvironment(autoescape=True, undefined=StrictUndefined)
_text = SandboxedEnvironment(autoescape=False, undefined=StrictUndefined)


class TemplateRenderError(Exception):
    pass


def render(template: EmailTemplate, context: dict[str, Any]) -> tuple[str, str, str]:
    """(subject, html, text)."""
    try:
        subject = _text.from_string(template.subject).render(context).strip()
        html = _html.from_string(template.body_html).render(context)
        text = _text.from_string(template.body_text).render(context)
    except TemplateError as exc:
        raise TemplateRenderError(str(exc)) from exc
    return subject, html, text


def validate(template: EmailTemplate) -> None:
    """Проверка синтаксиса при сохранении шаблона администратором."""
    try:
        for source in (template.subject, template.body_html, template.body_text):
            _html.parse(source)
    except TemplateError as exc:
        raise TemplateRenderError(str(exc)) from exc


def _order_status(status: str, title: str, text: str) -> EmailTemplate:
    return EmailTemplate(
        key=f"order_status_{status}",
        subject=f"Заказ {{{{ order_id }}}}: {title}",
        body_html=(
            f"<p>{text}</p>"
            "<p>Номер заказа: <b>{{ order_id }}</b></p>"
            "{% if reason %}<p>Причина: {{ reason }}</p>{% endif %}"
        ),
        body_text=(
            f"{text}\nНомер заказа: {{{{ order_id }}}}\n"
            "{% if reason %}Причина: {{ reason }}\n{% endif %}"
        ),
    )


DEFAULT_TEMPLATES: list[EmailTemplate] = [
    EmailTemplate(
        key="email_verification",
        subject="Подтвердите email",
        body_html=(
            "<p>Чтобы подтвердить адрес, перейдите по ссылке:</p>"
            '<p><a href="{{ verification_url }}">Подтвердить email</a></p>'
            "<p>Ссылка действует до {{ expires_at }}.</p>"
        ),
        body_text=(
            "Чтобы подтвердить адрес, перейдите по ссылке:\n{{ verification_url }}\n"
            "Ссылка действует до {{ expires_at }}.\n"
        ),
    ),
    EmailTemplate(
        key="order_created",
        subject="Заказ {{ order_id }} оформлен",
        body_html=(
            "<p>Спасибо за заказ!</p>"
            "<p>Номер: <b>{{ order_id }}</b><br>"
            "Товаров: {{ items_count }}<br>"
            "Сумма: {{ total_amount }} {{ currency }}</p>"
        ),
        body_text=(
            "Спасибо за заказ!\nНомер: {{ order_id }}\nТоваров: {{ items_count }}\n"
            "Сумма: {{ total_amount }} {{ currency }}\n"
        ),
    ),
    _order_status("RESERVED", "товар зарезервирован", "Товары зарезервированы, можно оплачивать."),
    _order_status("PAID", "оплачен", "Оплата получена, готовим заказ к отправке."),
    _order_status("SHIPPED", "отправлен", "Заказ передан в доставку."),
    _order_status("COMPLETED", "выполнен", "Заказ выполнен. Спасибо за покупку!"),
    _order_status("CANCELLED", "отменён", "Заказ отменён."),
]
