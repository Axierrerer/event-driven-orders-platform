from uuid import UUID

import pytest

from src.domain.openapi import merge_openapi
from src.domain.routing import (
    downstream_response_headers,
    product_id_from_path,
    resolve_upstream,
    upstream_request_headers,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("path", "service"),
    [
        ("/api/v1/auth/login", "auth"),
        ("/api/v1/users/me", "user"),
        ("/api/v1/users", "user"),
        ("/api/v1/products", "product"),
        ("/api/v1/categories/1", "product"),
        ("/api/v1/inventory/stock/x", "inventory"),
        ("/api/v1/orders/1/pay", "order"),
        ("/api/v1/notifications/templates", "notification"),
        ("/api/v1/usersx", None),
        ("/api/v2/orders", None),
    ],
)
def test_resolve_upstream(path: str, service: str | None) -> None:
    assert resolve_upstream(path) == service


def test_product_id_from_path() -> None:
    pid = "01a11f66-e72b-7620-8bb6-007ad63c9837"
    assert product_id_from_path(f"/api/v1/products/{pid}") == UUID(pid)
    assert product_id_from_path(f"/api/v1/products/{pid}/publish") is None
    assert product_id_from_path("/api/v1/products") is None


def test_client_cannot_spoof_platform_headers() -> None:
    headers = upstream_request_headers(
        [
            ("Authorization", "Bearer t"),
            ("X-User-Id", "admin"),
            ("X-Forwarded-For", "1.2.3.4"),
            ("X-Request-ID", "client-chosen"),
            ("Connection", "keep-alive"),
            ("Host", "evil"),
            ("Content-Type", "application/json"),
        ],
        client_ip="10.0.0.7",
        request_id="req-1",
        forwarded_proto="https",
    )
    assert headers == {
        "Authorization": "Bearer t",
        "Content-Type": "application/json",
        "X-Request-ID": "req-1",
        "X-Forwarded-For": "10.0.0.7",
        "X-Forwarded-Proto": "https",
    }


def test_response_headers_drop_hop_by_hop_and_encoding() -> None:
    assert downstream_response_headers(
        [
            ("Content-Type", "application/json"),
            ("Content-Encoding", "gzip"),
            ("Content-Length", "10"),
            ("Transfer-Encoding", "chunked"),
            ("ETag", '"2"'),
            ("Server", "uvicorn"),
        ]
    ) == [("Content-Type", "application/json"), ("ETag", '"2"')]


def test_merge_openapi_renames_conflicting_schemas() -> None:
    def spec(path: str, schema: dict[str, object]) -> dict[str, object]:
        return {
            "paths": {
                path: {"get": {"responses": {"200": {"$ref": "#/components/schemas/Item"}}}},
                "/health/live": {"get": {}},
            },
            "components": {"schemas": {"Item": schema, "Shared": {"type": "string"}}},
            "tags": [{"name": path.split("/")[3]}],
        }

    merged = merge_openapi(
        {
            "order": spec("/api/v1/orders", {"type": "object", "title": "Order"}),
            "product": spec("/api/v1/products", {"type": "object", "title": "Product"}),
        },
        title="T",
        version="1",
    )
    assert set(merged["paths"]) == {"/api/v1/orders", "/api/v1/products"}
    schemas = merged["components"]["schemas"]
    assert schemas["Item"]["title"] == "Order"
    assert schemas["product_Item"]["title"] == "Product"
    assert set(schemas) == {"Item", "product_Item", "Shared"}
    ref = merged["paths"]["/api/v1/products"]["get"]["responses"]["200"]["$ref"]
    assert ref == "#/components/schemas/product_Item"
    assert [t["name"] for t in merged["tags"]] == ["orders", "products"]
