from fastapi import FastAPI

from platform_lib.health import HealthRegistry, health_router
from src.config import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    health = HealthRegistry()
    app = FastAPI(title=settings.service_name, version="0.1.0")
    app.include_router(health_router(health))
    return app


app = create_app()
