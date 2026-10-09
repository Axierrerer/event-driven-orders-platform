from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import grpc
import httpx
from fastapi import FastAPI
from redis.asyncio import Redis

from platform_lib.auth import JwksKeyProvider, JwtVerifier
from platform_lib.checks import redis_check
from platform_lib.health import HealthRegistry, health_router
from platform_lib.logging import configure_logging
from platform_lib.ratelimit import BucketConfig, TokenBucket
from src.api.routes import request_context, router
from src.config import Settings, get_settings
from src.services.gateway import Gateway, RateLimits


def create_app(
    settings: Settings | None = None,
    *,
    verifier: JwtVerifier | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.service_name, settings.log_level)

    redis = Redis.from_url(settings.redis_url)
    http = httpx.AsyncClient(
        timeout=settings.upstream_timeout_seconds,
        limits=httpx.Limits(max_connections=200, max_keepalive_connections=50),
        transport=transport,
        follow_redirects=False,
    )
    product_channel = grpc.aio.insecure_channel(settings.product_grpc_target)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield
        await http.aclose()
        await product_channel.close()
        await redis.aclose()

    # Собственная схема отключена: /docs и /openapi.json собираются из схем сервисов
    app = FastAPI(
        title=settings.service_name,
        version="0.1.0",
        lifespan=lifespan,
        openapi_url=None,
        docs_url=None,
        redoc_url=None,
    )
    app.state.max_body_bytes = settings.max_body_bytes
    app.state.gateway = Gateway(
        upstreams=settings.upstreams(),
        http=http,
        verifier=verifier or JwtVerifier(JwksKeyProvider(settings.auth_jwks_url)),
        buckets=TokenBucket(redis),
        limits=RateLimits(
            user=BucketConfig(settings.user_rate_capacity, settings.user_rate_refill_seconds),
            anonymous=BucketConfig(
                settings.anonymous_rate_capacity, settings.anonymous_rate_refill_seconds
            ),
            login=BucketConfig(settings.login_rate_capacity, settings.login_rate_refill_seconds),
        ),
        product_channel=product_channel,
        grpc_timeout_seconds=settings.grpc_timeout_seconds,
        openapi_cache_seconds=settings.openapi_cache_seconds,
    )

    health = HealthRegistry()
    health.register("redis", redis_check(redis))
    app.include_router(health_router(health))
    app.include_router(router)
    app.middleware("http")(request_context)
    return app
