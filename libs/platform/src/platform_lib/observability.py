"""Подключение трейсов и метрик к сервису одной функцией."""

from typing import Any

from fastapi import FastAPI

from platform_lib.metrics import metrics_middleware, metrics_router
from platform_lib.settings import ServiceSettings
from platform_lib.telemetry import configure_tracing, instrument_fastapi, instrument_sqlalchemy


def setup_observability(app: FastAPI, settings: ServiceSettings, *, engine: Any = None) -> None:
    """Трейсы (OTLP, если задан endpoint), /metrics и HTTP-метрики."""
    configure_tracing(settings.service_name, settings.otel_exporter_otlp_endpoint)
    instrument_fastapi(app)
    if engine is not None:
        instrument_sqlalchemy(engine)
    app.middleware("http")(metrics_middleware)
    app.include_router(metrics_router())
