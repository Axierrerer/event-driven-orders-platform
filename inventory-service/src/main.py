from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine

from platform_lib.auth import JwksKeyProvider, JwtVerifier
from platform_lib.checks import postgres_check
from platform_lib.health import HealthRegistry, health_router
from platform_lib.logging import configure_logging
from platform_lib.outbox import PgOutbox
from src import db
from src.api.errors import install_error_handlers
from src.api.routes import router
from src.config import Settings, get_settings
from src.grpc_api.server import start_grpc_server
from src.services.inventory import InventoryService


def build_service(settings: Settings, engine: AsyncEngine | None = None) -> InventoryService:
    engine = engine or db.make_engine(settings.database_url)
    return InventoryService(
        db.make_session_factory(engine),
        PgOutbox(db.outbox),
        reservation_ttl=timedelta(seconds=settings.reservation_ttl_seconds),
    )


def create_app(
    settings: Settings | None = None,
    *,
    verifier: JwtVerifier | None = None,
    start_grpc: bool = True,
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.service_name, settings.log_level)

    engine = db.make_engine(settings.database_url)
    inventory = build_service(settings, engine)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        grpc_server = None
        if start_grpc:
            grpc_server, app.state.grpc_port = await start_grpc_server(
                inventory, settings.grpc_port
            )
        yield
        if grpc_server is not None:
            await grpc_server.stop(grace=5)
        await engine.dispose()

    app = FastAPI(title=settings.service_name, version="0.1.0", lifespan=lifespan)
    app.state.jwt_verifier = verifier or JwtVerifier(JwksKeyProvider(settings.auth_jwks_url))
    app.state.inventory = inventory

    health = HealthRegistry()
    health.register("postgres", postgres_check(engine))
    app.include_router(health_router(health))
    app.include_router(router)
    install_error_handlers(app)
    return app
