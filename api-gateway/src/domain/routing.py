"""Маршрутизация и фильтрация заголовков — чистые функции."""

import re
from collections.abc import Iterable, Mapping
from uuid import UUID

# Префикс пути → имя upstream-сервиса. Порядок: более длинные префиксы первыми.
ROUTES: tuple[tuple[str, str], ...] = (
    ("/api/v1/auth", "auth"),
    ("/api/v1/users", "user"),
    ("/api/v1/products", "product"),
    ("/api/v1/categories", "product"),
    ("/api/v1/inventory", "inventory"),
    ("/api/v1/orders", "order"),
    ("/api/v1/notifications", "notification"),
)

_PRODUCT_BY_ID = re.compile(r"^/api/v1/products/([0-9a-fA-F-]{36})$")

# RFC 9110: hop-by-hop заголовки не пересылаются
HOP_BY_HOP = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "proxy-connection",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
    }
)
# Заголовки, которые клиент не должен подделать: их выставляет только платформа
CLIENT_FORBIDDEN_PREFIXES = ("x-user-", "x-forwarded-", "x-real-ip", "x-gateway-")


def resolve_upstream(path: str) -> str | None:
    for prefix, service in ROUTES:
        if path == prefix or path.startswith(prefix + "/"):
            return service
    return None


def product_id_from_path(path: str) -> UUID | None:
    """id товара для GET /api/v1/products/{id}, иначе None."""
    match = _PRODUCT_BY_ID.match(path)
    if match is None:
        return None
    try:
        return UUID(match.group(1))
    except ValueError:
        return None


def upstream_request_headers(
    headers: Iterable[tuple[str, str]],
    *,
    client_ip: str,
    request_id: str,
    forwarded_proto: str,
) -> dict[str, str]:
    result: dict[str, str] = {}
    for name, value in headers:
        lower = name.lower()
        if lower in HOP_BY_HOP or lower in {"host", "content-length"}:
            continue
        if lower.startswith(CLIENT_FORBIDDEN_PREFIXES) or lower == "x-request-id":
            continue
        result[name] = value
    result["X-Request-ID"] = request_id
    result["X-Forwarded-For"] = client_ip
    result["X-Forwarded-Proto"] = forwarded_proto
    return result


def downstream_response_headers(
    headers: Mapping[str, str] | Iterable[tuple[str, str]],
) -> list[tuple[str, str]]:
    items = headers.items() if isinstance(headers, Mapping) else headers
    # content-encoding/length убираются: тело уже распаковано и будет пересчитано
    skip = HOP_BY_HOP | {"content-length", "content-encoding", "server", "date"}
    return [(name, value) for name, value in items if name.lower() not in skip]
