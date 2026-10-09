from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from redis.asyncio import Redis

from platform_lib.auth import JwksKeyProvider, JwtVerifier
from platform_lib.checks import mongo_check, redis_check
from platform_lib.health import HealthRegistry, health_router
from platform_lib.logging import configure_logging
from platform_lib.ratelimit import BucketConfig, TokenBucket
from src import db
from src.api.routes import router
from src.config import Settings, get_settings
from src.domain.templates import DEFAULT_TEMPLATES
from src.repositories.templates import TemplateRepository
from src.services.admin import AdminService
from src.services.email import EmailSender, SmtpEmailSender
from src.services.notifications import NotificationService


def build_service(
    settings: Settings, database: Any, redis: Redis, sender: EmailSender | None = None
) -> NotificationService:
    return NotificationService(
        database,
        sender
        or SmtpEmailSender(
            settings.smtp_host,
            settings.smtp_port,
            settings.smtp_from,
            timeout_seconds=settings.smtp_timeout_seconds,
        ),
        TokenBucket(redis),
        user_bucket=BucketConfig(
            settings.user_bucket_capacity, settings.user_bucket_refill_seconds
        ),
        verification_bucket=BucketConfig(
            settings.verification_bucket_capacity, settings.verification_bucket_refill_seconds
        ),
        max_attempts=settings.max_send_attempts,
    )


async def prepare_database(database: Any) -> None:
    await db.ensure_indexes(database)
    await TemplateRepository(database).seed(DEFAULT_TEMPLATES)


def create_app(settings: Settings | None = None, *, verifier: JwtVerifier | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.service_name, settings.log_level)

    client = db.make_client(settings.mongo_url)
    database = client[settings.mongo_db]
    redis = Redis.from_url(settings.redis_url)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        await prepare_database(database)
        yield
        await redis.aclose()
        client.close()

    app = FastAPI(title=settings.service_name, version="0.1.0", lifespan=lifespan)
    app.state.jwt_verifier = verifier or JwtVerifier(JwksKeyProvider(settings.auth_jwks_url))
    app.state.database = database
    app.state.admin = AdminService(database)

    health = HealthRegistry()
    health.register("mongo", mongo_check(client))
    health.register("redis", redis_check(redis))
    app.include_router(health_router(health))
    app.include_router(router)
    return app
