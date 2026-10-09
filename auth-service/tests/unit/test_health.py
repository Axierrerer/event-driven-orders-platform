import pytest
from httpx import ASGITransport, AsyncClient

from src.main import create_app

pytestmark = pytest.mark.unit


async def test_live_and_ready_respond_ok() -> None:
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        live = await client.get("/health/live")
        ready = await client.get("/health/ready")
    assert live.status_code == 200
    assert live.json() == {"status": "ok"}
    assert ready.status_code == 200


async def test_openapi_has_service_title() -> None:
    app = create_app()
    assert app.title == "auth-service"
