"""Логика gateway: аутентификация, rate limit, маршрутизация в сервисы."""

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import grpc
import httpx
from orders_proto.catalog.v1 import product_pb2, product_pb2_grpc

from events import Role
from platform_lib.auth import InvalidTokenError, JwtVerifier, Principal
from platform_lib.logging import get_logger
from platform_lib.ratelimit import BucketConfig, Decision, TokenBucket
from src.domain.openapi import merge_openapi

log = get_logger(__name__)

STAFF = frozenset({Role.ADMIN, Role.MANAGER})


class UnauthorizedError(Exception):
    pass


class UpstreamUnavailableError(Exception):
    pass


class UpstreamTimeoutError(Exception):
    pass


@dataclass(frozen=True)
class RateLimits:
    user: BucketConfig
    anonymous: BucketConfig
    login: BucketConfig


@dataclass(frozen=True)
class UpstreamResponse:
    status_code: int
    headers: list[tuple[str, str]]
    body: bytes


class Gateway:
    def __init__(
        self,
        *,
        upstreams: dict[str, str],
        http: httpx.AsyncClient,
        verifier: JwtVerifier,
        buckets: TokenBucket,
        limits: RateLimits,
        product_channel: grpc.aio.Channel,
        grpc_timeout_seconds: float,
        openapi_cache_seconds: float,
    ) -> None:
        self._upstreams = upstreams
        self._http = http
        self._verifier = verifier
        self._buckets = buckets
        self._limits = limits
        self._products = product_pb2_grpc.ProductServiceStub(product_channel)  # type: ignore[no-untyped-call]
        self._grpc_timeout = grpc_timeout_seconds
        self._openapi_cache_seconds = openapi_cache_seconds
        self._openapi: tuple[float, dict[str, Any]] | None = None
        self._openapi_lock = asyncio.Lock()

    # ---------- аутентификация и лимиты ----------

    async def authenticate(self, authorization: str | None) -> Principal | None:
        """Без заголовка — аноним; с невалидным токеном — UnauthorizedError."""
        if not authorization:
            return None
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise UnauthorizedError
        try:
            return await self._verifier.verify(token)
        except InvalidTokenError as exc:
            raise UnauthorizedError from exc

    async def check_rate_limit(
        self, principal: Principal | None, client_ip: str, method: str, path: str
    ) -> tuple[Decision, BucketConfig]:
        if method == "POST" and path == "/api/v1/auth/login":
            key, config = f"login:{client_ip}", self._limits.login
        elif principal is not None:
            key, config = f"user:{principal.user_id}", self._limits.user
        else:
            key, config = f"ip:{client_ip}", self._limits.anonymous
        try:
            return await self._buckets.take(f"gw:{key}", config), config
        except Exception as exc:  # Redis недоступен — не роняем весь трафик
            log.warning("rate_limit_unavailable", error=str(exc))
            return Decision(allowed=True, retry_after_seconds=0, remaining=config.capacity), config

    # ---------- проксирование ----------

    async def forward(
        self,
        service: str,
        *,
        method: str,
        path: str,
        query: str,
        headers: dict[str, str],
        body: bytes,
    ) -> UpstreamResponse:
        url = f"{self._upstreams[service]}{path}"
        if query:
            url = f"{url}?{query}"
        try:
            response = await self._http.request(method, url, headers=headers, content=body)
        except httpx.TimeoutException as exc:
            log.warning("upstream_timeout", service=service, path=path)
            raise UpstreamTimeoutError(service) from exc
        except httpx.TransportError as exc:
            log.warning("upstream_unavailable", service=service, error=str(exc))
            raise UpstreamUnavailableError(service) from exc
        return UpstreamResponse(
            response.status_code, list(response.headers.items()), response.content
        )

    # ---------- карточка товара через gRPC ----------

    async def product_card(
        self, product_id: UUID, principal: Principal | None
    ) -> dict[str, Any] | None:
        """Карточка для покупателя через gRPC. None — товара нет (или он скрыт).

        Персонал (видит неопубликованное) обслуживается REST-маршрутом.
        Ошибки связи пробрасываются: вызывающий откатится на REST.
        """
        try:
            product = await self._products.GetProduct(
                product_pb2.GetProductRequest(product_id=str(product_id)),
                timeout=self._grpc_timeout,
            )
        except grpc.aio.AioRpcError as exc:
            if exc.code() == grpc.StatusCode.NOT_FOUND:
                return None
            raise
        if not product.is_published and not (principal and principal.has_any(STAFF)):
            return None
        return {
            "id": product.id,
            "sku": product.sku,
            "name": product.name,
            "description": product.description,
            "category_id": product.category_id or None,
            "price": product.price,
            "currency": product.currency,
            "attributes": json.loads(product.attributes_json or "{}"),
            "images": list(product.images),
            "is_published": product.is_published,
            "version": product.version,
            "created_at": product.created_at,
            "updated_at": product.updated_at,
        }

    # ---------- документация ----------

    async def openapi(self) -> dict[str, Any]:
        async with self._openapi_lock:
            now = time.monotonic()
            if self._openapi and now - self._openapi[0] < self._openapi_cache_seconds:
                return self._openapi[1]
            specs: dict[str, dict[str, Any]] = {}
            for service, base_url in self._upstreams.items():
                try:
                    response = await self._http.get(f"{base_url}/openapi.json")
                    response.raise_for_status()
                    specs[service] = response.json()
                except httpx.HTTPError as exc:
                    log.warning("openapi_unavailable", service=service, error=str(exc))
            merged = merge_openapi(specs, title="Orders Platform API", version="0.1.0")
            if specs:
                self._openapi = (now, merged)
            return merged
