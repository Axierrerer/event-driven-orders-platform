from collections.abc import AsyncIterator
from datetime import timedelta

import httpx
import pytest

from events import Role, uuid7
from platform_lib.testing import TokenFactory

from ..conftest import HIDDEN, PUBLISHED, Catalog, Env, make_env

pytestmark = pytest.mark.integration


@pytest.mark.parametrize(
    ("path", "host"),
    [
        ("/api/v1/auth/login", "auth-service"),
        ("/api/v1/users/me", "user-service"),
        ("/api/v1/products?q=чайник", "product-service"),
        ("/api/v1/categories", "product-service"),
        ("/api/v1/inventory/stock/1", "inventory-service"),
        ("/api/v1/orders", "order-service"),
        ("/api/v1/notifications", "notification-service"),
    ],
)
async def test_routes_reach_their_service(env: Env, path: str, host: str) -> None:
    response = await env.client.get(path)
    assert response.status_code == 200
    assert response.json()["service"] == host
    assert response.headers["X-Gateway-Instance"]
    assert response.headers["ETag"] == '"7"'
    assert response.headers.get("connection") != "close"  # hop-by-hop от сервиса не пересылается


async def test_query_and_body_are_forwarded(env: Env) -> None:
    response = await env.client.post(
        "/api/v1/orders?dry=1", json={"items": []}, headers={"Idempotency-Key": "key-12345678"}
    )
    assert response.json()["query"] == "dry=1"
    sent = env.upstreams.requests[-1]
    assert sent.method == "POST"
    assert sent.content == b'{"items":[]}'
    assert sent.headers["Idempotency-Key"] == "key-12345678"


async def test_unknown_route_404(env: Env) -> None:
    response = await env.client.get("/api/v1/unknown")
    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"


async def test_bad_token_rejected_without_upstream_call(env: Env) -> None:
    for header in ("Bearer forged.token.value", "Basic abc"):
        response = await env.client.get("/api/v1/users/me", headers={"Authorization": header})
        assert response.status_code == 401
        assert response.json()["title"] == "Unauthorized"
    expired = env.tokens.token(uuid7(), ttl=timedelta(seconds=-5))
    response = await env.client.get(
        "/api/v1/users/me", headers={"Authorization": f"Bearer {expired}"}
    )
    assert response.status_code == 401
    assert env.upstreams.requests == []


async def test_valid_token_and_request_id_forwarded(env: Env) -> None:
    headers = env.tokens.headers(uuid7()) | {
        "X-User-Id": "spoofed",
        "X-Forwarded-For": "6.6.6.6",
        "X-Request-ID": "req-from-nginx",
    }
    response = await env.client.get("/api/v1/users/me", headers=headers)
    sent = env.upstreams.requests[-1]
    assert sent.headers["Authorization"].startswith("Bearer ")
    assert "x-user-id" not in sent.headers
    assert sent.headers["X-Forwarded-For"] == "203.0.113.9"
    assert sent.headers["X-Request-ID"] == "req-from-nginx"
    assert response.headers["X-Request-ID"] == "req-from-nginx"


async def test_request_id_generated_when_missing(env: Env) -> None:
    response = await env.client.get("/api/v1/orders")
    assert len(response.headers["X-Request-ID"]) == 32
    assert env.upstreams.requests[-1].headers["X-Request-ID"] == response.headers["X-Request-ID"]


# ---------- rate limit ----------


@pytest.fixture
async def strict_env(
    redis_url: str, tokens: TokenFactory, grpc_catalog: tuple[Catalog, int]
) -> AsyncIterator[Env]:
    async for value in make_env(
        redis_url,
        tokens,
        grpc_catalog,
        anonymous_rate_capacity=3,
        anonymous_rate_refill_seconds=60,
        user_rate_capacity=3,
        user_rate_refill_seconds=60,
        login_rate_capacity=2,
        login_rate_refill_seconds=60,
    ):
        yield value


async def test_rate_limit_per_user_and_ip(strict_env: Env) -> None:
    client = strict_env.client
    statuses = [(await client.get("/api/v1/products")).status_code for _ in range(4)]
    assert statuses == [200, 200, 200, 429]
    limited = await client.get("/api/v1/products")
    assert int(limited.headers["Retry-After"]) >= 1
    assert limited.headers["RateLimit-Limit"] == "3"
    assert limited.headers["RateLimit-Remaining"] == "0"

    alice = strict_env.tokens.headers(uuid7())
    bob = strict_env.tokens.headers(uuid7())
    assert [(await client.get("/api/v1/orders", headers=alice)).status_code for _ in range(4)] == [
        200,
        200,
        200,
        429,
    ]
    assert (await client.get("/api/v1/orders", headers=bob)).status_code == 200


async def test_login_has_its_own_strict_limit(strict_env: Env) -> None:
    statuses = [
        (await strict_env.client.post("/api/v1/auth/login", json={})).status_code for _ in range(3)
    ]
    assert statuses == [200, 200, 429]


# ---------- gRPC карточка товара ----------


async def test_product_card_served_via_grpc(env: Env) -> None:
    response = await env.client.get(f"/api/v1/products/{PUBLISHED}")
    assert response.status_code == 200
    assert response.headers["X-Served-Via"] == "grpc"
    assert response.headers["ETag"] == '"3"'
    body = response.json()
    assert body["price"] == "1490.00"
    assert body["attributes"] == {"volume_l": 1}
    assert env.upstreams.requests == []  # REST не вызывался


async def test_hidden_or_missing_product_is_404_for_customers(env: Env) -> None:
    assert (await env.client.get(f"/api/v1/products/{HIDDEN}")).status_code == 404
    assert (await env.client.get(f"/api/v1/products/{uuid7()}")).status_code == 404


async def test_staff_product_request_goes_to_rest(env: Env) -> None:
    admin = env.tokens.headers(uuid7(), [Role.ADMIN])
    response = await env.client.get(f"/api/v1/products/{HIDDEN}", headers=admin)
    assert response.json()["service"] == "product-service"
    assert env.catalog.calls == 0


async def test_grpc_outage_falls_back_to_rest(
    redis_url: str, tokens: TokenFactory, grpc_catalog: tuple[Catalog, int]
) -> None:
    async for env in make_env(redis_url, tokens, (grpc_catalog[0], 1)):  # порт 1 — недоступен
        response = await env.client.get(f"/api/v1/products/{PUBLISHED}")
        assert response.status_code == 200
        assert response.json()["service"] == "product-service"


# ---------- ошибки и ограничения ----------


async def test_upstream_errors_are_problem_json(env: Env) -> None:
    env.upstreams.fail["order-service"] = httpx.ConnectError
    env.upstreams.fail["user-service"] = httpx.ReadTimeout
    down = await env.client.get("/api/v1/orders")
    slow = await env.client.get("/api/v1/users/me")
    assert (down.status_code, slow.status_code) == (502, 504)
    assert down.headers["content-type"] == "application/problem+json"
    assert "Traceback" not in down.text


async def test_body_size_limit(env: Env) -> None:
    response = await env.client.post("/api/v1/orders", content=b"x" * 1_048_577)
    assert response.status_code == 413
    assert env.upstreams.requests == []


# ---------- документация ----------


async def test_docs_aggregate_all_services(env: Env) -> None:
    spec = (await env.client.get("/openapi.json")).json()
    assert set(spec["paths"]) == {
        "/api/v1/auth",
        "/api/v1/user",
        "/api/v1/product",
        "/api/v1/inventory",
        "/api/v1/order",
        "/api/v1/notification",
    }
    docs = await env.client.get("/docs")
    assert docs.status_code == 200
    assert "/openapi.json" in docs.text
