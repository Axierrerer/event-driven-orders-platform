from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from platform_lib.auth import JwksKeyProvider, JwtVerifier
from platform_lib.checks import postgres_check
from platform_lib.health import HealthRegistry, health_router
from platform_lib.logging import configure_logging
from platform_lib.observability import setup_observability
from platform_lib.outbox import PgOutbox
from platform_lib.telemetry import configure_tracing
from src import db
from src.api.errors import install_error_handlers
from src.api.routes import router
from src.config import Settings, get_settings
from src.services.users import UserService


def create_app(settings: Settings | None = None, *, verifier: JwtVerifier | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.service_name, settings.log_level)
    # До создания клиентов: инструментация оборачивает только новые httpx/gRPC-клиенты
    configure_tracing(settings.service_name, settings.otel_exporter_otlp_endpoint)

    engine = db.make_engine(settings.database_url)
    session_factory = db.make_session_factory(engine)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield
        await engine.dispose()

    app = FastAPI(title=settings.service_name, version="0.1.0", lifespan=lifespan)
    app.state.jwt_verifier = verifier or JwtVerifier(JwksKeyProvider(settings.auth_jwks_url))
    app.state.user_service = UserService(
        session_factory,
        PgOutbox(db.outbox),
        bootstrap_admin_email=settings.bootstrap_admin_email,
    )

    setup_observability(app, settings, engine=engine)
    health = HealthRegistry()
    health.register("postgres", postgres_check(engine))
    app.include_router(health_router(health))
    app.include_router(router)
    install_error_handlers(app)
    return app
