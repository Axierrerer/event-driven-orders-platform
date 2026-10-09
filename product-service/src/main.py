from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from redis.asyncio import Redis

from platform_lib.auth import JwksKeyProvider, JwtVerifier
from platform_lib.checks import mongo_check, redis_check
from platform_lib.health import HealthRegistry, health_router
from platform_lib.logging import configure_logging
from platform_lib.observability import setup_observability
from platform_lib.telemetry import configure_tracing
from src import db
from src.api.errors import install_error_handlers
from src.api.routes import categories, products
from src.config import Settings, get_settings
from src.grpc_api.server import start_grpc_server
from src.services.cache import ProductCache
from src.services.catalog import CatalogService


def create_app(
    settings: Settings | None = None,
    *,
    verifier: JwtVerifier | None = None,
    start_grpc: bool = True,
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.service_name, settings.log_level)
    # До создания клиентов: инструментация оборачивает только новые httpx/gRPC-клиенты
    configure_tracing(settings.service_name, settings.otel_exporter_otlp_endpoint)

    client = db.make_client(settings.mongo_url)
    database = client[settings.mongo_db]
    redis = Redis.from_url(settings.redis_url)
    catalog = CatalogService(
        client, database, ProductCache(redis, settings.product_cache_ttl_seconds)
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await db.ensure_indexes(database)
        grpc_server = None
        if start_grpc:
            grpc_server, app.state.grpc_port = await start_grpc_server(catalog, settings.grpc_port)
        yield
        if grpc_server is not None:
            await grpc_server.stop(grace=5)
        await redis.aclose()
        client.close()

    app = FastAPI(title=settings.service_name, version="0.1.0", lifespan=lifespan)
    app.state.jwt_verifier = verifier or JwtVerifier(JwksKeyProvider(settings.auth_jwks_url))
    app.state.catalog = catalog
    app.state.database = database

    setup_observability(app, settings)
    health = HealthRegistry()
    health.register("mongo", mongo_check(client))
    health.register("redis", redis_check(redis))
    app.include_router(health_router(health))
    app.include_router(products)
    app.include_router(categories)
    install_error_handlers(app)
    return app
