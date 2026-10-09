import json
from collections.abc import Iterator
from decimal import Decimal

import pytest
import structlog
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from events import OrderCreated, OrderCreatedPayload, OrderItem, uuid7
from platform_lib.consumer import IdempotentConsumer, RetryPolicy
from platform_lib.logging import configure_logging, get_logger
from platform_lib.metrics import EVENTS_PROCESSED, metrics_middleware, metrics_router
from platform_lib.outbox import record_from_event
from platform_lib.telemetry import tracer

from .fakes import FakeDeadLetters, FakeInbox, FakeMessage

pytestmark = pytest.mark.unit

EXPORTER = InMemorySpanExporter()


@pytest.fixture(scope="module", autouse=True)
def tracing() -> Iterator[None]:
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(EXPORTER))
    trace.set_tracer_provider(provider)
    yield


@pytest.fixture(autouse=True)
def clean() -> None:
    EXPORTER.clear()


def make_event() -> OrderCreated:
    order_id = uuid7()
    return OrderCreated(
        producer="order-service",
        correlation_id=order_id,
        payload=OrderCreatedPayload(
            order_id=order_id,
            user_id=uuid7(),
            items=[OrderItem(product_id=uuid7(), quantity=1, unit_price=Decimal("1.00"))],
            total_amount=Decimal("1.00"),
            currency="RUB",
        ),
    )


async def test_trace_continues_from_outbox_to_consumer() -> None:
    event = make_event()
    with tracer().start_as_current_span("POST /api/v1/orders") as business:
        record = record_from_event(event)
    trace_id = business.get_span_context().trace_id
    assert "traceparent" in record.headers

    consumer = IdempotentConsumer(
        group_id="inventory-service",
        inbox=FakeInbox(),
        decoder=lambda _m: event,
        dead_letters=FakeDeadLetters(),
        retry=RetryPolicy(delays_seconds=()),
    )

    @consumer.handler("order.created")
    async def handle(_event: OrderCreated, _tx: object) -> None:
        return None

    before = EVENTS_PROCESSED.labels("order.created", "processed")._value.get()
    headers = [(k, v.encode()) for k, v in record.headers.items()]
    await consumer.process(FakeMessage("order.created", message_headers=headers))

    consume = next(s for s in EXPORTER.get_finished_spans() if s.name == "consume order.created")
    assert consume.context.trace_id == trace_id
    assert consume.parent is not None
    assert consume.parent.span_id == business.get_span_context().span_id
    assert consume.attributes["orders.consumer.result"] == "processed"
    assert EVENTS_PROCESSED.labels("order.created", "processed")._value.get() == before + 1


async def test_http_metrics_use_route_templates() -> None:
    app = FastAPI()
    app.middleware("http")(metrics_middleware)
    app.include_router(metrics_router())

    @app.get("/api/v1/orders/{order_id}")
    async def get_order(order_id: str) -> dict[str, str]:
        return {"id": order_id}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        for _ in range(3):
            await client.get(f"/api/v1/orders/{uuid7()}")
        await client.get("/nowhere")
        exposition = (await client.get("/metrics")).text

    assert 'http_requests_total{method="GET",route="/api/v1/orders/{order_id}",status="200"}' in (
        exposition
    )
    assert 'route="unmatched",status="404"' in exposition
    assert "http_request_duration_seconds_bucket" in exposition
    assert "/api/v1/orders/0" not in exposition  # сырые пути не попадают в метки


def test_logs_carry_trace_ids(capsys: pytest.CaptureFixture[str]) -> None:
    structlog.reset_defaults()
    configure_logging("order-service")
    with tracer().start_as_current_span("work") as span:
        get_logger().info("inside_span")
    record = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert record["trace_id"] == f"{span.get_span_context().trace_id:032x}"
    assert record["span_id"] == f"{span.get_span_context().span_id:016x}"
