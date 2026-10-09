from typing import Any

import pytest
from httpx import AsyncClient

from events import uuid7

from ..conftest import CreateProduct

pytestmark = pytest.mark.integration


async def outbox(client: AsyncClient) -> list[dict[str, Any]]:
    db = client.app.state.database  # type: ignore[attr-defined]
    return [doc async for doc in db.outbox.find().sort("created_at", 1)]


# ---------- создание ----------


async def test_create_product_writes_document_and_event(
    client: AsyncClient, create_product: CreateProduct
) -> None:
    product = await create_product(sku="MUG-1", name="Кружка", price="10.10")

    assert product["price"] == "10.10"
    assert product["version"] == 1
    events = await outbox(client)
    assert [e["topic"] for e in events] == ["product.changed"]
    assert events[0]["key"] == product["id"]
    assert events[0]["payload"]["payload"]["price"] == "10.10"


async def test_duplicate_sku_conflicts(
    client: AsyncClient, create_product: CreateProduct, admin: dict[str, str]
) -> None:
    await create_product(sku="MUG-1")
    response = await client.post(
        "/api/v1/products",
        json={"sku": "MUG-1", "name": "Другая кружка", "price": "1.00"},
        headers=admin,
    )
    assert response.status_code == 409
    assert len(await outbox(client)) == 1  # событие второй попытки не записано


@pytest.mark.parametrize(
    "price",
    ["-1.00", "1.001", 10.1, "abc", "12345678901.00"],
    ids=["negative", "three-decimals", "json-float", "not-number", "too-many-digits"],
)
async def test_invalid_price_rejected(
    client: AsyncClient, admin: dict[str, str], price: object
) -> None:
    response = await client.post(
        "/api/v1/products", json={"sku": "X-1", "name": "X", "price": price}, headers=admin
    )
    assert response.status_code == 422


async def test_price_round_trip_without_precision_loss(
    client: AsyncClient, create_product: CreateProduct
) -> None:
    product = await create_product(price="0.10")
    fetched = (await client.get(f"/api/v1/products/{product['id']}")).json()
    assert fetched["price"] == "0.10"


# ---------- доступ ----------


async def test_write_requires_admin(
    client: AsyncClient, user: dict[str, str], manager: dict[str, str]
) -> None:
    body = {"sku": "X-1", "name": "X", "price": "1.00"}
    assert (await client.post("/api/v1/products", json=body)).status_code == 401
    assert (await client.post("/api/v1/products", json=body, headers=user)).status_code == 403
    assert (await client.post("/api/v1/products", json=body, headers=manager)).status_code == 403


async def test_unpublished_product_hidden_from_customers(
    client: AsyncClient,
    create_product: CreateProduct,
    admin: dict[str, str],
    user: dict[str, str],
) -> None:
    hidden = await create_product(name="Секретный чайник", is_published=False)
    url = f"/api/v1/products/{hidden['id']}"

    assert (await client.get(url)).status_code == 404
    assert (await client.get(url, headers=user)).status_code == 404
    assert (await client.get(url, headers=admin)).status_code == 200

    assert (await client.get("/api/v1/products?q=чайник")).json()["total"] == 0
    assert (await client.get("/api/v1/products?q=чайник", headers=admin)).json()["total"] == 1


async def test_manager_publishes_and_unpublishes(
    client: AsyncClient, create_product: CreateProduct, manager: dict[str, str]
) -> None:
    product = await create_product(is_published=False)
    url = f"/api/v1/products/{product['id']}"

    published = await client.post(f"{url}/publish", headers=manager)
    assert published.status_code == 200
    assert published.json()["is_published"] is True
    assert (await client.get(url)).status_code == 200

    await client.post(f"{url}/unpublish", headers=manager)
    assert (await client.get(url)).status_code == 404
    topics = [e["payload"]["payload"]["is_published"] for e in await outbox(client)]
    assert topics == [False, True, False]


async def test_delete_is_soft_and_hides_product(
    client: AsyncClient, create_product: CreateProduct, admin: dict[str, str]
) -> None:
    product = await create_product()
    url = f"/api/v1/products/{product['id']}"
    assert (await client.delete(url, headers=admin)).status_code == 204
    assert (await client.get(url, headers=admin)).status_code == 404
    assert (await client.delete(url, headers=admin)).status_code == 404
    assert (await outbox(client))[-1]["payload"]["payload"]["is_deleted"] is True


# ---------- поиск ----------


async def test_price_filter_is_inclusive(
    client: AsyncClient, create_product: CreateProduct
) -> None:
    for price in ("99.99", "100.00", "150.00", "200.00", "200.01"):
        await create_product(price=price)

    page = (await client.get("/api/v1/products?price_min=100&price_max=200&sort=price")).json()
    assert [p["price"] for p in page["items"]] == ["100.00", "150.00", "200.00"]
    assert page["total"] == 3


async def test_price_min_greater_than_max_rejected(client: AsyncClient) -> None:
    response = await client.get("/api/v1/products?price_min=200&price_max=100")
    assert response.status_code == 422


async def test_text_search_ranks_name_above_description(
    client: AsyncClient, create_product: CreateProduct
) -> None:
    in_description = await create_product(name="Подставка", description="Подходит под любой чайник")
    in_name = await create_product(name="Чайник стеклянный", description="Объём 1.5 л")
    await create_product(name="Тарелка", description="Фарфор")

    page = (await client.get("/api/v1/products?q=чайники")).json()  # морфология: чайники → чайник
    assert [p["id"] for p in page["items"]] == [in_name["id"], in_description["id"]]
    assert page["total"] == 2


async def test_category_filter_and_pagination(
    client: AsyncClient, create_product: CreateProduct, admin: dict[str, str]
) -> None:
    category = (
        await client.post("/api/v1/categories", json={"name": "Посуда"}, headers=admin)
    ).json()
    for i in range(3):
        await create_product(category_id=category["id"], price=f"{10 + i}.00")
    await create_product()  # без категории

    url = f"/api/v1/products?category={category['id']}&sort=price&limit=2"
    first = (await client.get(url)).json()
    second = (await client.get(f"{url}&offset=2")).json()
    assert first["total"] == 3
    assert [p["price"] for p in first["items"]] == ["10.00", "11.00"]
    assert [p["price"] for p in second["items"]] == ["12.00"]


# ---------- версии и кэш ----------


async def test_update_with_stale_if_match_fails(
    client: AsyncClient, create_product: CreateProduct, admin: dict[str, str]
) -> None:
    product = await create_product()
    url = f"/api/v1/products/{product['id']}"
    etag = (await client.get(url)).headers["ETag"]
    assert etag == '"1"'

    ok = await client.patch(url, json={"name": "Новое"}, headers=admin | {"If-Match": etag})
    assert ok.status_code == 200
    assert ok.headers["ETag"] == '"2"'

    stale = await client.patch(url, json={"name": "Ещё"}, headers=admin | {"If-Match": etag})
    assert stale.status_code == 412


async def test_put_replaces_editable_fields(
    client: AsyncClient, create_product: CreateProduct, admin: dict[str, str]
) -> None:
    product = await create_product(description="старое", attributes={"color": "red"})
    response = await client.put(
        f"/api/v1/products/{product['id']}",
        json={"sku": product["sku"], "name": "Новое имя", "price": "5.00"},
        headers=admin,
    )
    body = response.json()
    assert response.status_code == 200
    assert body["description"] == ""
    assert body["attributes"] == {}
    assert body["is_published"] is True  # публикация меняется отдельными эндпоинтами


async def test_patch_rejects_null_for_required_field(
    client: AsyncClient, create_product: CreateProduct, admin: dict[str, str]
) -> None:
    product = await create_product()
    response = await client.patch(
        f"/api/v1/products/{product['id']}", json={"name": None}, headers=admin
    )
    assert response.status_code == 422


async def test_cache_is_invalidated_after_price_change(
    client: AsyncClient, create_product: CreateProduct, admin: dict[str, str]
) -> None:
    product = await create_product(price="10.00")
    url = f"/api/v1/products/{product['id']}"
    assert (await client.get(url)).json()["price"] == "10.00"  # попадает в кэш

    await client.patch(url, json={"price": "12.50"}, headers=admin)
    assert (await client.get(url)).json()["price"] == "12.50"


async def test_unknown_category_rejected(client: AsyncClient, admin: dict[str, str]) -> None:
    response = await client.post(
        "/api/v1/products",
        json={"sku": "X-1", "name": "X", "price": "1.00", "category_id": str(uuid7())},
        headers=admin,
    )
    assert response.status_code == 422


# ---------- категории ----------


async def test_categories_crud(
    client: AsyncClient, create_product: CreateProduct, admin: dict[str, str], user: dict[str, str]
) -> None:
    assert (
        await client.post("/api/v1/categories", json={"name": "Кухня"}, headers=user)
    ).status_code == 403
    created = await client.post("/api/v1/categories", json={"name": "Кухня"}, headers=admin)
    assert created.status_code == 201
    category_id = created.json()["id"]
    duplicate = await client.post("/api/v1/categories", json={"name": "Кухня"}, headers=admin)
    assert duplicate.status_code == 409

    renamed = await client.patch(
        f"/api/v1/categories/{category_id}", json={"name": "Кухня и столовая"}, headers=admin
    )
    assert renamed.json()["name"] == "Кухня и столовая"
    assert [c["name"] for c in (await client.get("/api/v1/categories")).json()] == [
        "Кухня и столовая"
    ]

    product = await create_product(category_id=category_id)
    in_use = await client.delete(f"/api/v1/categories/{category_id}", headers=admin)
    assert in_use.status_code == 409

    await client.delete(f"/api/v1/products/{product['id']}", headers=admin)
    assert (
        await client.delete(f"/api/v1/categories/{category_id}", headers=admin)
    ).status_code == 204
    assert (
        await client.delete(f"/api/v1/categories/{category_id}", headers=admin)
    ).status_code == 404
