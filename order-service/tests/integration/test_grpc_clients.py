"""gRPC-адаптеры против настоящих gRPC-серверов в процессе теста."""

import asyncio
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Any

import grpc
import pytest
from orders_proto.catalog.v1 import product_pb2, product_pb2_grpc
from orders_proto.inventory.v1 import inventory_pb2, inventory_pb2_grpc

from events import uuid7
from src.services.grpc_clients import GrpcCatalog, GrpcInventory

pytestmark = pytest.mark.integration

PRODUCT = uuid7()


class Catalog(product_pb2_grpc.ProductServiceServicer):
    async def GetProducts(self, request: Any, context: Any) -> Any:
        return product_pb2.GetProductsResponse(
            products=[
                product_pb2.Product(
                    id=pid, name="Чайник", price="1490.10", currency="RUB", is_published=True
                )
                for pid in request.product_ids
                if pid == str(PRODUCT)
            ]
        )


class Inventory(inventory_pb2_grpc.InventoryServiceServicer):
    def __init__(self, delay: float = 0.0) -> None:
        self.delay = delay

    async def CheckAvailability(self, request: Any, context: Any) -> Any:
        await asyncio.sleep(self.delay)
        return inventory_pb2.CheckAvailabilityResponse(
            available=False,
            items=[
                inventory_pb2.ItemAvailability(
                    product_id=i.product_id, requested=i.quantity, available=1
                )
                for i in request.items
            ],
        )


@pytest.fixture
async def channel() -> AsyncIterator[tuple[grpc.aio.Channel, Inventory]]:
    server = grpc.aio.server()
    inventory = Inventory()
    product_pb2_grpc.add_ProductServiceServicer_to_server(Catalog(), server)  # type: ignore[no-untyped-call]
    inventory_pb2_grpc.add_InventoryServiceServicer_to_server(inventory, server)  # type: ignore[no-untyped-call]
    port = server.add_insecure_port("127.0.0.1:0")
    await server.start()
    async with grpc.aio.insecure_channel(f"127.0.0.1:{port}") as ch:
        yield ch, inventory
    await server.stop(None)


async def test_catalog_adapter_parses_decimal_prices(
    channel: tuple[grpc.aio.Channel, Inventory],
) -> None:
    products = await GrpcCatalog(channel[0], timeout_seconds=1).get_products([PRODUCT, uuid7()])
    assert list(products) == [PRODUCT]
    assert products[PRODUCT].price == Decimal("1490.10")
    assert products[PRODUCT].is_published is True


async def test_inventory_adapter_and_deadline(
    channel: tuple[grpc.aio.Channel, Inventory],
) -> None:
    ch, inventory = channel
    adapter = GrpcInventory(ch, timeout_seconds=0.3)
    result = await adapter.check({PRODUCT: 2})
    assert result.available is False
    assert result.items == [(PRODUCT, 2, 1)]

    inventory.delay = 1.0  # медленнее дедлайна
    with pytest.raises(grpc.aio.AioRpcError) as exc:
        await adapter.check({PRODUCT: 1})
    assert exc.value.code() == grpc.StatusCode.DEADLINE_EXCEEDED
