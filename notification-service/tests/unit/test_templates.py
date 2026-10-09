import pytest

from src.domain.models import EmailTemplate, backoff_seconds
from src.domain.templates import DEFAULT_TEMPLATES, TemplateRenderError, render, validate

pytestmark = pytest.mark.unit


def template(key: str) -> EmailTemplate:
    return next(t for t in DEFAULT_TEMPLATES if t.key == key)


def test_user_data_is_escaped_in_html() -> None:
    subject, html, text = render(
        template("order_status_CANCELLED"),
        {"order_id": "o-1", "reason": "<script>alert(1)</script>"},
    )
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "<script>alert(1)</script>" in text  # текстовая версия не HTML
    assert subject == "Заказ o-1: отменён"


def test_missing_variable_is_an_error() -> None:
    with pytest.raises(TemplateRenderError):
        render(template("order_created"), {"order_id": "o-1"})


def test_sandbox_blocks_dangerous_attributes() -> None:
    evil = EmailTemplate(
        key="evil",
        subject="x",
        body_html="{{ ''.__class__.__mro__[1].__subclasses__() }}",
        body_text="x",
    )
    with pytest.raises(TemplateRenderError):
        render(evil, {})


def test_invalid_syntax_rejected() -> None:
    with pytest.raises(TemplateRenderError):
        validate(EmailTemplate(key="bad", subject="{{ x", body_html="", body_text=""))


def test_every_order_status_after_new_has_a_template() -> None:
    keys = {t.key for t in DEFAULT_TEMPLATES}
    for status in ("RESERVED", "PAID", "SHIPPED", "COMPLETED", "CANCELLED"):
        assert f"order_status_{status}" in keys
    assert {"email_verification", "order_created"} <= keys


def test_backoff_grows() -> None:
    assert [backoff_seconds(n) for n in range(1, 5)] == [5, 10, 20, 40]
