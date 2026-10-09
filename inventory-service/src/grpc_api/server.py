"""gRPC API склада для order-service."""

from typing import Any
from uuid import UUID

import grpc
from grpc_health.v1 import health, health_pb2, health_pb2_grpc
from orders_proto.inventory.v1 import inventory_pb2, inventory_pb2_grpc

from platform_lib.logging import get_logger
from src.services.inventory import InventoryService

log = get_logger(__name__)

MAX_ITEMS = 100


class InventoryGrpcService(inventory_pb2_grpc.InventoryServiceServicer):
    def __init__(self, inventory: InventoryService) -> None:
        self._inventory = inventory

    async def CheckAvailability(
        self, request: inventory_pb2.CheckAvailabilityRequest, context: Any
    ) -> inventory_pb2.CheckAvailabilityResponse:
        if not request.items or len(request.items) > MAX_ITEMS:
            await context.abort(
                grpc.StatusCode.INVALID_ARGUMENT, f"1..{MAX_ITEMS} items per request"
            )
        items: list[tuple[UUID, int]] = []
        for item in request.items:
            try:
                product_id = UUID(item.product_id)
            except ValueError:
                await context.abort(
                    grpc.StatusCode.INVALID_ARGUMENT, f"invalid product id: {item.product_id!r}"
                )
                raise
            if item.quantity <= 0:
                await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "quantity must be positive")
            items.append((product_id, item.quantity))

        available, details = await self._inventory.check_availability(items)
        return inventory_pb2.CheckAvailabilityResponse(
            available=available,
            items=[
                inventory_pb2.ItemAvailability(
                    product_id=str(product_id), requested=requested, available=in_stock
                )
                for product_id, (requested, in_stock) in details.items()
            ],
        )


async def start_grpc_server(inventory: InventoryService, port: int) -> tuple[grpc.aio.Server, int]:
    """Запускает сервер; port=0 — свободный порт. Возвращает сервер и фактический порт."""
    server = grpc.aio.server()
    inventory_pb2_grpc.add_InventoryServiceServicer_to_server(  # type: ignore[no-untyped-call]
        InventoryGrpcService(inventory), server
    )
    health_servicer = health.aio.HealthServicer()
    health_pb2_grpc.add_HealthServicer_to_server(health_servicer, server)
    await health_servicer.set("", health_pb2.HealthCheckResponse.SERVING)
    bound = server.add_insecure_port(f"[::]:{port}")
    await server.start()
    log.info("grpc_server_started", port=bound)
    return server, bound
