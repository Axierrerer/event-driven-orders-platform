"""Структурные JSON-логи с маскированием чувствительных полей."""

import logging
import sys
from collections.abc import Mapping
from typing import Any

import structlog
from structlog.typing import EventDict, Processor, WrappedLogger

from platform_lib.telemetry import current_trace_ids

SENSITIVE_KEY_PARTS = ("password", "token", "authorization", "secret", "cookie")
REDACTED = "***"


def _is_sensitive(key: str) -> bool:
    lowered = key.lower()
    return any(part in lowered for part in SENSITIVE_KEY_PARTS)


def _redact_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            k: REDACTED if _is_sensitive(str(k)) else _redact_value(v) for k, v in value.items()
        }
    if isinstance(value, list | tuple):
        return [_redact_value(v) for v in value]
    return value


def redact_sensitive(_logger: WrappedLogger, _method: str, event_dict: EventDict) -> EventDict:
    """Заменяет значения полей с паролями, токенами и т. п. на `***` (рекурсивно)."""
    for key in list(event_dict):
        if _is_sensitive(key):
            event_dict[key] = REDACTED
        else:
            event_dict[key] = _redact_value(event_dict[key])
    return event_dict


def add_trace_ids(_logger: WrappedLogger, _method: str, event_dict: EventDict) -> EventDict:
    """trace_id/span_id текущего спана: по ним лог связывается с трейсом в Jaeger."""
    ids = current_trace_ids()
    if ids is not None:
        event_dict.setdefault("trace_id", ids[0])
        event_dict.setdefault("span_id", ids[1])
    return event_dict


def _add_service(service_name: str) -> Processor:
    def processor(_logger: WrappedLogger, _method: str, event_dict: EventDict) -> EventDict:
        event_dict.setdefault("service", service_name)
        return event_dict

    return processor


def configure_logging(service_name: str, level: str = "INFO") -> None:
    """Все логи (structlog и стандартный logging, в т.ч. uvicorn) — JSON в stdout."""
    shared: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _add_service(service_name),
        add_trace_ids,
        redact_sensitive,
    ]
    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(ensure_ascii=False),
        ],
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers = []
        uvicorn_logger.propagate = True


def get_logger(name: str | None = None, **initial: Any) -> Any:
    return structlog.get_logger(name, **initial)


def bind_context(**values: Any) -> None:
    """Добавить поля (request_id, trace_id, ...) во все логи текущей задачи."""
    structlog.contextvars.bind_contextvars(**values)


def clear_context() -> None:
    structlog.contextvars.clear_contextvars()


__all__ = [
    "REDACTED",
    "bind_context",
    "clear_context",
    "configure_logging",
    "get_logger",
    "redact_sensitive",
]
