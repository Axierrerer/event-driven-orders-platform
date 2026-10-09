from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta

from fastapi import FastAPI
from pwdlib import PasswordHash
from redis.asyncio import Redis

from platform_lib.auth import JwtVerifier, StaticKeyProvider
from platform_lib.checks import postgres_check, redis_check
from platform_lib.health import HealthRegistry, health_router
from platform_lib.logging import configure_logging
from platform_lib.outbox import PgOutbox
from src import db
from src.api.errors import install_error_handlers
from src.api.routes import router
from src.config import Settings, get_settings
from src.services.auth import AuthConfig, AuthService
from src.services.jwt_issuer import JwtIssuer, load_private_key
from src.services.login_limiter import LoginAttemptLimiter


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.service_name, settings.log_level)

    engine = db.make_engine(settings.database_url)
    session_factory = db.make_session_factory(engine)
    redis = Redis.from_url(settings.redis_url)

    private_key = load_private_key(
        settings.jwt_private_key_path, generate_if_missing=settings.is_local
    )
    issuer = JwtIssuer(private_key, settings.jwt_key_id, settings.access_token_ttl_seconds)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield
        await redis.aclose()
        await engine.dispose()

    app = FastAPI(title=settings.service_name, version="0.1.0", lifespan=lifespan)
    app.state.jwt_issuer = issuer
    app.state.jwt_verifier = JwtVerifier(StaticKeyProvider({issuer.key_id: issuer.public_key}))
    app.state.auth_service = AuthService(
        session_factory,
        PgOutbox(db.outbox),
        PasswordHash.recommended(),
        issuer,
        LoginAttemptLimiter(
            redis,
            max_failures=settings.login_max_failures,
            window_seconds=settings.login_failure_window_seconds,
        ),
        AuthConfig(
            refresh_token_ttl=timedelta(days=settings.refresh_token_ttl_days),
            email_verification_ttl=timedelta(hours=settings.email_verification_ttl_hours),
            app_base_url=settings.app_base_url,
        ),
    )

    health = HealthRegistry()
    health.register("postgres", postgres_check(engine))
    health.register("redis", redis_check(redis))
    app.include_router(health_router(health))
    app.include_router(router)
    install_error_handlers(app)
    return app
