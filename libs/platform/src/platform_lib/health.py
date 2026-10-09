import asyncio
from collections.abc import Awaitable, Callable

from fastapi import APIRouter
from fastapi.responses import JSONResponse

HealthCheck = Callable[[], Awaitable[None]]


class HealthRegistry:
    """Набор проверок готовности; проверка считается упавшей при исключении или таймауте."""

    def __init__(self, timeout_seconds: float = 2.0) -> None:
        self._checks: dict[str, HealthCheck] = {}
        self._timeout = timeout_seconds

    def register(self, name: str, check: HealthCheck) -> None:
        self._checks[name] = check

    async def run(self) -> dict[str, str]:
        async def run_one(name: str, check: HealthCheck) -> tuple[str, str]:
            try:
                await asyncio.wait_for(check(), self._timeout)
            except Exception:
                return name, "fail"
            return name, "ok"

        results = await asyncio.gather(*(run_one(n, c) for n, c in self._checks.items()))
        return dict(results)


def health_router(registry: HealthRegistry) -> APIRouter:
    router = APIRouter(prefix="/health", tags=["health"])

    @router.get("/live")
    async def live() -> dict[str, str]:
        return {"status": "ok"}

    @router.get("/ready")
    async def ready() -> JSONResponse:
        checks = await registry.run()
        is_ready = all(status == "ok" for status in checks.values())
        return JSONResponse(
            {"status": "ok" if is_ready else "fail", "checks": checks},
            status_code=200 if is_ready else 503,
        )

    return router
