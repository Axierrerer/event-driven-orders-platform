"""HTTP-слой gateway: единая точка входа для /api/v1/*, документация, ошибки RFC 9457."""

import math
import socket
import uuid
from typing import Any
from uuid import UUID

import grpc
from fastapi import APIRouter, Request, Response
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse, JSONResponse

from events import Role
from platform_lib.auth import Principal
from platform_lib.logging import bind_context, clear_context
from src.domain.routing import (
    downstream_response_headers,
    product_id_from_path,
    resolve_upstream,
    upstream_request_headers,
)
from src.services.gateway import (
    Gateway,
    UnauthorizedError,
    UpstreamTimeoutError,
    UpstreamUnavailableError,
)

router = APIRouter()
INSTANCE = socket.gethostname()
METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"]


def problem(status: int, title: str, detail: str | None = None, **headers: str) -> JSONResponse:
    body: dict[str, Any] = {"type": "about:blank", "title": title, "status": status}
    if detail:
        body["detail"] = detail
    return JSONResponse(body, status, media_type="application/problem+json", headers=headers)


def gateway_of(request: Request) -> Gateway:
    gateway: Gateway = request.app.state.gateway
    return gateway


async def request_context(request: Request, call_next: Any) -> Response:
    """Middleware: X-Request-ID (из Nginx или новый) и X-Gateway-Instance в каждом ответе."""
    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
    request.state.request_id = request_id
    clear_context()
    bind_context(request_id=request_id)
    response: Response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Gateway-Instance"] = INSTANCE
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@router.get("/openapi.json", include_in_schema=False)
async def openapi(request: Request) -> JSONResponse:
    return JSONResponse(await gateway_of(request).openapi())


@router.get("/docs", include_in_schema=False)
async def docs() -> HTMLResponse:
    return get_swagger_ui_html(openapi_url="/openapi.json", title="Orders Platform API")


async def product_card_via_grpc(
    gateway: Gateway,
    product_id: UUID,
    principal: Principal | None,
    rate_headers: dict[str, str],
) -> Response | None:
    """Карточка товара для покупателя через gRPC; None — gRPC недоступен, идём по REST."""
    try:
        card = await gateway.product_card(product_id, principal)
    except grpc.aio.AioRpcError:
        return None
    if card is None:
        return problem(404, "Not Found", "product not found", **rate_headers)
    response = JSONResponse(card, headers=rate_headers)
    response.headers["ETag"] = f'"{card["version"]}"'
    response.headers["X-Served-Via"] = "grpc"
    return response


@router.api_route("/api/v1/{rest:path}", methods=METHODS, include_in_schema=False)
async def proxy(request: Request, rest: str) -> Response:
    gateway = gateway_of(request)
    path = request.url.path
    service = resolve_upstream(path)
    if service is None:
        return problem(404, "Not Found", "no route for this path")

    try:
        principal = await gateway.authenticate(request.headers.get("authorization"))
    except UnauthorizedError:
        return problem(
            401, "Unauthorized", "invalid or expired token", **{"WWW-Authenticate": "Bearer"}
        )

    client_ip = request.client.host if request.client else "unknown"
    decision, limit = await gateway.check_rate_limit(principal, client_ip, request.method, path)
    rate_headers = {
        "RateLimit-Limit": str(limit.capacity),
        "RateLimit-Remaining": str(decision.remaining),
    }
    if not decision.allowed:
        retry_after = str(max(1, math.ceil(decision.retry_after_seconds)))
        return problem(
            429, "Too Many Requests", None, **rate_headers, **{"Retry-After": retry_after}
        )

    product_id = product_id_from_path(path) if request.method == "GET" else None
    is_staff = principal is not None and principal.has_any({Role.ADMIN, Role.MANAGER})
    if product_id is not None and not is_staff:
        card_response = await product_card_via_grpc(gateway, product_id, principal, rate_headers)
        if card_response is not None:
            return card_response

    declared = request.headers.get("content-length")
    max_body = request.app.state.max_body_bytes
    if declared and declared.isdigit() and int(declared) > max_body:
        return problem(413, "Payload Too Large")
    body = await request.body()
    if len(body) > max_body:
        return problem(413, "Payload Too Large")

    headers = upstream_request_headers(
        request.headers.items(),
        client_ip=client_ip,
        request_id=request.state.request_id,
        forwarded_proto=request.url.scheme,
    )
    try:
        upstream = await gateway.forward(
            service,
            method=request.method,
            path=path,
            query=request.url.query,
            headers=headers,
            body=body,
        )
    except UpstreamTimeoutError:
        return problem(504, "Gateway Timeout", f"{service} did not respond in time")
    except UpstreamUnavailableError:
        return problem(502, "Bad Gateway", f"{service} is unavailable")

    proxied = Response(content=upstream.body, status_code=upstream.status_code)
    for name, value in downstream_response_headers(upstream.headers):
        proxied.headers.append(name, value)
    for name, value in rate_headers.items():
        proxied.headers[name] = value
    return proxied
