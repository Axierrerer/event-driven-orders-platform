"""gRPC-адаптеры портов каталога и склада."""

from collections.abc import Iterable
from decimal import Decimal
from uuid import UUID

import grpc
from orders_proto.catalog.v1 import product_pb2, product_pb2_grpc
from orders_proto.inventory.v1 import inventory_pb2, inventory_pb2_grpc

from src.services.ports import Availability, CatalogProduct


class GrpcCatalog:
    def __init__(self, channel: grpc.aio.Channel, *, timeout_seconds: float) -> None:
        self._stub = product_pb2_grpc.ProductServiceStub(channel)  # type: ignore[no-untyped-call]
        self._timeout = timeout_seconds

    async def get_products(self, product_ids: Iterable[UUID]) -> dict[UUID, CatalogProduct]:
        response = await self._stub.GetProducts(
            product_pb2.GetProductsRequest(product_ids=[str(pid) for pid in product_ids]),
            timeout=self._timeout,
        )
        return {
            UUID(p.id): CatalogProduct(
                product_id=UUID(p.id),
                name=p.name,
                price=Decimal(p.price),
                currency=p.currency,
                is_published=p.is_published,
            )
            for p in response.products
        }


class GrpcInventory:
    def __init__(self, channel: grpc.aio.Channel, *, timeout_seconds: float) -> None:
        self._stub = inventory_pb2_grpc.InventoryServiceStub(channel)  # type: ignore[no-untyped-call]
        self._timeout = timeout_seconds

    async def check(self, items: dict[UUID, int]) -> Availability:
        response = await self._stub.CheckAvailability(
            inventory_pb2.CheckAvailabilityRequest(
                items=[
                    inventory_pb2.Item(product_id=str(pid), quantity=qty)
                    for pid, qty in items.items()
                ]
            ),
            timeout=self._timeout,
        )
        return Availability(
            available=response.available,
            items=[(UUID(i.product_id), i.requested, i.available) for i in response.items],
        )
