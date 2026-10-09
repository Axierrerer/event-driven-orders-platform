import json
from collections.abc import AsyncIterator

import grpc
import pytest
from httpx import AsyncClient
from orders_proto.catalog.v1 import product_pb2, product_pb2_grpc

from events import uuid7

from ..conftest import CreateProduct

pytestmark = pytest.mark.integration


@pytest.fixture
async def stub(client: AsyncClient) -> AsyncIterator[product_pb2_grpc.ProductServiceStub]:
    port = client.app.state.grpc_port  # type: ignore[attr-defined]
    async with grpc.aio.insecure_channel(f"localhost:{port}") as channel:
        yield product_pb2_grpc.ProductServiceStub(channel)  # type: ignore[no-untyped-call]


async def test_get_products_returns_known_and_skips_unknown(
    stub: product_pb2_grpc.ProductServiceStub, create_product: CreateProduct
) -> None:
    first = await create_product(price="10.10", is_published=False)
    second = await create_product(price="0.30")

    response = await stub.GetProducts(
        product_pb2.GetProductsRequest(product_ids=[first["id"], str(uuid7()), second["id"]])
    )
    by_id = {p.id: p for p in response.products}
    assert set(by_id) == {first["id"], second["id"]}
    assert by_id[first["id"]].price == "10.10"
    assert by_id[first["id"]].is_published is False  # решение о продаже — у вызывающего
    assert by_id[second["id"]].currency == "RUB"


async def test_get_products_limit(stub: product_pb2_grpc.ProductServiceStub) -> None:
    ids = [str(uuid7()) for _ in range(101)]
    with pytest.raises(grpc.aio.AioRpcError) as exc:
        await stub.GetProducts(product_pb2.GetProductsRequest(product_ids=ids))
    assert exc.value.code() == grpc.StatusCode.INVALID_ARGUMENT


async def test_get_product_not_found_and_invalid_id(
    stub: product_pb2_grpc.ProductServiceStub, create_product: CreateProduct
) -> None:
    product = await create_product(
        name="Чашка", images=["https://cdn.test/cup.png"], attributes={"volume_ml": 300}
    )
    found = await stub.GetProduct(product_pb2.GetProductRequest(product_id=product["id"]))
    assert found.name == "Чашка"
    assert list(found.images) == ["https://cdn.test/cup.png"]
    assert json.loads(found.attributes_json) == {"volume_ml": 300}
    assert found.created_at.startswith("20")

    with pytest.raises(grpc.aio.AioRpcError) as missing:
        await stub.GetProduct(product_pb2.GetProductRequest(product_id=str(uuid7())))
    assert missing.value.code() == grpc.StatusCode.NOT_FOUND

    with pytest.raises(grpc.aio.AioRpcError) as invalid:
        await stub.GetProduct(product_pb2.GetProductRequest(product_id="not-a-uuid"))
    assert invalid.value.code() == grpc.StatusCode.INVALID_ARGUMENT
