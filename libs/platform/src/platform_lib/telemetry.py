"""Трассировка OpenTelemetry: SDK, экспорт по OTLP, автоинструментация и перенос
контекста через Kafka (заголовок traceparent)."""

from collections.abc import Iterable
from typing import Any

from opentelemetry import context as otel_context
from opentelemetry import propagate, trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

_configured = False


def configure_tracing(service_name: str, otlp_endpoint: str | None) -> None:
    """Однократная настройка провайдера трейсов и автоинструментации клиентов.

    Без otlp_endpoint трейсы создаются (trace_id попадает в логи), но никуда не экспортируются.
    """
    global _configured
    if _configured:
        return
    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    if otlp_endpoint:
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True))
        )
    trace.set_tracer_provider(provider)
    _instrument_clients()
    _configured = True


def _instrument_clients() -> None:
    from opentelemetry.instrumentation.grpc import (
        GrpcAioInstrumentorClient,
        GrpcAioInstrumentorServer,
    )
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    from opentelemetry.instrumentation.pymongo import PymongoInstrumentor
    from opentelemetry.instrumentation.redis import RedisInstrumentor

    HTTPXClientInstrumentor().instrument()
    GrpcAioInstrumentorClient().instrument()  # type: ignore[no-untyped-call]
    GrpcAioInstrumentorServer().instrument()  # type: ignore[no-untyped-call]
    RedisInstrumentor().instrument()
    PymongoInstrumentor().instrument()


def instrument_fastapi(app: Any) -> None:
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    FastAPIInstrumentor.instrument_app(app, excluded_urls="health/live,health/ready,metrics")


def instrument_sqlalchemy(engine: Any) -> None:
    from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

    SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)


def tracer(name: str = "orders-platform") -> trace.Tracer:
    return trace.get_tracer(name)


def trace_headers() -> dict[str, str]:
    """W3C traceparent текущего контекста — для заголовков события в outbox."""
    carrier: dict[str, str] = {}
    propagate.inject(carrier)
    return carrier


def context_from_headers(headers: Iterable[tuple[str, Any]] | None) -> otel_context.Context:
    carrier: dict[str, str] = {}
    for name, value in headers or []:
        if isinstance(value, bytes):
            value = value.decode("utf-8", "replace")
        carrier[name.lower()] = str(value)
    return propagate.extract(carrier)


def current_trace_ids() -> tuple[str, str] | None:
    span_context = trace.get_current_span().get_span_context()
    if not span_context.is_valid:
        return None
    return f"{span_context.trace_id:032x}", f"{span_context.span_id:016x}"
