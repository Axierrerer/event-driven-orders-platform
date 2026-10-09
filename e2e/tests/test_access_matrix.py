"""Матрица доступа: каждый закрытый эндпоинт через публичный API.

Без токена → 401; роль ниже требуемой → 403; чужой ресурс покупателя → 404.
"""

import uuid
from typing import Any

import pytest

from .conftest import API, Platform, User

pytestmark = pytest.mark.e2e

ANY_ID = "01a00000-0000-7000-8000-000000000000"

# (метод, путь, тело, минимальная роль: user | staff | admin)
ENDPOINTS: list[tuple[str, str, dict[str, Any] | None, str]] = [
    ("POST", "/auth/password", {"old_password": "x", "new_password": "y" * 12}, "user"),
    ("GET", "/users/me", None, "user"),
    ("PATCH", "/users/me", {"full_name": "X"}, "user"),
    ("GET", "/users", None, "staff"),
    ("PUT", f"/users/{ANY_ID}/roles", {"roles": ["ROLE_USER"]}, "admin"),
    ("DELETE", f"/users/{ANY_ID}", None, "admin"),
    ("POST", "/products", {"sku": "ACL-1", "name": "x", "price": "1.00"}, "admin"),
    ("PUT", f"/products/{ANY_ID}", {"sku": "ACL-1", "name": "x", "price": "1.00"}, "admin"),
    ("PATCH", f"/products/{ANY_ID}", {"name": "x"}, "admin"),
    ("DELETE", f"/products/{ANY_ID}", None, "admin"),
    ("POST", f"/products/{ANY_ID}/publish", None, "staff"),
    ("POST", f"/products/{ANY_ID}/unpublish", None, "staff"),
    ("POST", "/categories", {"name": "acl"}, "admin"),
    ("PATCH", f"/categories/{ANY_ID}", {"name": "acl"}, "admin"),
    ("DELETE", f"/categories/{ANY_ID}", None, "admin"),
    ("GET", f"/inventory/stock/{ANY_ID}", None, "staff"),
    ("POST", f"/inventory/stock/{ANY_ID}/adjust", {"delta": 1, "reason": "acl"}, "staff"),
    ("GET", "/orders", None, "user"),
    ("POST", f"/orders/{ANY_ID}/ship", None, "staff"),
    ("POST", f"/orders/{ANY_ID}/complete", None, "staff"),
    ("GET", "/notifications", None, "admin"),
    ("GET", "/notifications/templates", None, "admin"),
    (
        "PUT",
        "/notifications/templates/x",
        {"subject": "s", "body_html": "h", "body_text": "t"},
        "admin",
    ),
]

RANK = {"user": 0, "staff": 1, "admin": 2}


def call(platform: Platform, method: str, path: str, body: Any, user: User | None) -> int:
    headers = {"Idempotency-Key": f"acl-{uuid.uuid4()}"}
    if user is not None:
        headers |= user.headers
    response = platform.http.request(method, f"{API}{path}", json=body, headers=headers)
    return response.status_code


@pytest.mark.parametrize(("method", "path", "body", "role"), ENDPOINTS, ids=lambda v: str(v))
def test_endpoint_requires_token(
    platform: Platform, method: str, path: str, body: Any, role: str
) -> None:
    assert call(platform, method, path, body, None) == 401


@pytest.mark.parametrize(
    ("method", "path", "body", "role"),
    [e for e in ENDPOINTS if RANK[e[3]] >= RANK["staff"]],
    ids=lambda v: str(v),
)
def test_customer_is_forbidden(
    platform: Platform, buyer: User, method: str, path: str, body: Any, role: str
) -> None:
    assert call(platform, method, path, body, buyer) == 403


@pytest.mark.parametrize(
    ("method", "path", "body", "role"),
    [e for e in ENDPOINTS if e[3] == "admin"],
    ids=lambda v: str(v),
)
def test_manager_cannot_do_admin_actions(
    platform: Platform, manager: User, method: str, path: str, body: Any, role: str
) -> None:
    assert call(platform, method, path, body, manager) == 403


def test_foreign_resources_are_invisible(platform: Platform, admin: User, buyer: User) -> None:
    product = platform.product_with_stock(admin, stock=1)
    order_id = platform.place_order(buyer, [(product, 1)]).json()["id"]
    stranger = platform.register_verified()

    for method, path in [
        ("GET", f"/orders/{order_id}"),
        ("POST", f"/orders/{order_id}/pay"),
        ("POST", f"/orders/{order_id}/cancel"),
    ]:
        assert call(platform, method, path, None, stranger) == 404, path
    profile_id = platform.http.get(f"{API}/users/me", headers=buyer.headers).json()["id"]
    assert call(platform, "GET", f"/users/{profile_id}", None, stranger) == 403


def test_responses_do_not_leak_server_details(platform: Platform) -> None:
    response = platform.http.get(f"{API}/products")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    server = response.headers.get("Server", "")
    assert not any(ch.isdigit() for ch in server), f"server version leaked: {server}"
    broken = platform.http.post(
        f"{API}/orders", content=b"{not json", headers={"Content-Type": "application/json"}
    )
    assert "Traceback" not in broken.text
