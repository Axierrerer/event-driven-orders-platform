import json
import logging

import pytest
import structlog

from platform_lib.logging import (
    REDACTED,
    bind_context,
    clear_context,
    configure_logging,
    get_logger,
)

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _reset_logging() -> None:
    structlog.reset_defaults()
    clear_context()


def _last_json_line(output: str) -> dict[str, object]:
    lines = [line for line in output.strip().splitlines() if line.startswith("{")]
    return json.loads(lines[-1])


def test_logs_are_json_with_service_and_level(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("order-service", "INFO")
    get_logger("test").info("order_created", order_id="o-1")

    record = _last_json_line(capsys.readouterr().out)
    assert record["event"] == "order_created"
    assert record["service"] == "order-service"
    assert record["level"] == "info"
    assert record["order_id"] == "o-1"
    assert str(record["timestamp"]).endswith("Z")


def test_sensitive_fields_are_redacted(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("auth-service")
    get_logger().info(
        "login",
        email="user@example.com",
        password="hunter2",
        refresh_token="rt-secret-value",
        request={"headers": {"Authorization": "Bearer abc"}, "path": "/login"},
        items=[{"api_secret": "x", "name": "ok"}],
    )

    output = capsys.readouterr().out
    record = _last_json_line(output)
    assert record["email"] == "user@example.com"
    assert record["password"] == REDACTED
    assert record["refresh_token"] == REDACTED
    assert record["request"] == {"headers": {"Authorization": REDACTED}, "path": "/login"}
    assert record["items"] == [{"api_secret": REDACTED, "name": "ok"}]
    for secret in ("hunter2", "rt-secret-value", "Bearer abc"):
        assert secret not in output


def test_stdlib_logging_goes_through_same_pipeline(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("api-gateway")
    logging.getLogger("uvicorn.error").warning("server started")

    record = _last_json_line(capsys.readouterr().out)
    assert record["event"] == "server started"
    assert record["service"] == "api-gateway"
    assert record["level"] == "warning"


def test_bound_context_added_to_every_record(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("order-service")
    bind_context(request_id="req-42")
    get_logger().info("step")

    assert _last_json_line(capsys.readouterr().out)["request_id"] == "req-42"


def test_level_filters_debug(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("order-service", "INFO")
    get_logger().debug("noise")
    assert "noise" not in capsys.readouterr().out
