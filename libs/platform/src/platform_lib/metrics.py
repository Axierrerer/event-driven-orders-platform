"""Метрики Prometheus: HTTP, Kafka, outbox. Бизнес-метрики объявляют сами сервисы."""

import time
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter, Request, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
    start_http_server,
)

HTTP_REQUESTS = Counter("http_requests_total", "HTTP requests", ["method", "route", "status"])
HTTP_DURATION = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration",
    ["method", "route"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.15, 0.25, 0.5, 1, 2.5, 5),
)
EVENTS_PROCESSED = Counter(
    "events_processed_total", "Kafka events handled by consumers", ["topic", "result"]
)
DLQ_MESSAGES = Counter("dlq_messages_total", "Messages sent to dead-letter topics", ["topic"])
CONSUMER_LAG = Gauge(
    "kafka_consumer_lag", "Messages behind the end of the partition", ["topic", "partition"]
)
OUTBOX_PENDING = Gauge("outbox_pending", "Unpublished outbox records")
OUTBOX_OLDEST_AGE = Gauge("outbox_oldest_age_seconds", "Age of the oldest unpublished record")
OUTBOX_PUBLISHED = Counter("outbox_published_total", "Outbox records published to Kafka")

_SKIP_PATHS = ("/metrics", "/health/live", "/health/ready")


async def metrics_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    if request.url.path in _SKIP_PATHS:
        return await call_next(request)
    started = time.perf_counter()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        return response
    finally:
        route = request.scope.get("route")
        template = getattr(route, "path", None) or "unmatched"  # шаблон, а не сырой путь
        HTTP_REQUESTS.labels(request.method, template, str(status)).inc()
        HTTP_DURATION.labels(request.method, template).observe(time.perf_counter() - started)


def metrics_router() -> APIRouter:
    router = APIRouter()

    @router.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return router


def start_metrics_server(port: int) -> Any:
    """HTTP-сервер /metrics для фоновых процессов (worker без FastAPI)."""
    return start_http_server(port)
