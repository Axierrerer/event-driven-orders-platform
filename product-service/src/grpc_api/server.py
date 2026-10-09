"""gRPC API каталога для внутренних вызовов (api-gateway, order-service)."""

from typing import Any
from uuid import UUID

import grpc
from grpc_health.v1 import health, health_pb2, health_pb2_grpc
from orders_proto.catalog.v1 import product_pb2, product_pb2_grpc

from platform_lib.logging import get_logger
from src.domain.errors import InvalidFilterError
from src.domain.models import Product
from src.services.catalog import MAX_BATCH, CatalogService

log = get_logger(__name__)


def to_message(product: Product) -> product_pb2.Product:
    return product_pb2.Product(
        id=str(product.id),
        sku=product.sku,
        name=product.name,
        description=product.description,
        category_id=str(product.category_id) if product.category_id else "",
        price=f"{product.price:.2f}",
        currency=product.currency,
        is_published=product.is_published,
        version=product.version,
    )


async def _parse_id(value: str, context: Any) -> UUID:
    try:
        return UUID(value)
    except ValueError:
        await context.abort(grpc.StatusCode.INVALID_ARGUMENT, f"invalid product id: {value!r}")
        raise  # abort бросает исключение; строка для анализатора типов


class ProductGrpcService(product_pb2_grpc.ProductServiceServicer):
    def __init__(self, catalog: CatalogService) -> None:
        self._catalog = catalog

    async def GetProduct(
        self, request: product_pb2.GetProductRequest, context: Any
    ) -> product_pb2.Product:
        product_id = await _parse_id(request.product_id, context)
        product = await self._catalog.get_for_internal(product_id)
        if product is None:
            await context.abort(grpc.StatusCode.NOT_FOUND, "product not found")
        assert product is not None  # noqa: S101 — abort выше бросает исключение
        return to_message(product)

    async def GetProducts(
        self, request: product_pb2.GetProductsRequest, context: Any
    ) -> product_pb2.GetProductsResponse:
        if len(request.product_ids) > MAX_BATCH:
            await context.abort(
                grpc.StatusCode.INVALID_ARGUMENT, f"at most {MAX_BATCH} product ids per call"
            )
        ids = [await _parse_id(value, context) for value in request.product_ids]
        try:
            products = await self._catalog.get_many_for_internal(ids)
        except InvalidFilterError as exc:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(exc))
            raise
        return product_pb2.GetProductsResponse(products=[to_message(p) for p in products])


async def start_grpc_server(catalog: CatalogService, port: int) -> tuple[grpc.aio.Server, int]:
    """Запускает сервер; port=0 — свободный порт. Возвращает сервер и фактический порт."""
    server = grpc.aio.server()
    product_pb2_grpc.add_ProductServiceServicer_to_server(  # type: ignore[no-untyped-call]
        ProductGrpcService(catalog), server
    )
    health_servicer = health.aio.HealthServicer()
    health_pb2_grpc.add_HealthServicer_to_server(health_servicer, server)
    await health_servicer.set("", health_pb2.HealthCheckResponse.SERVING)
    bound = server.add_insecure_port(f"[::]:{port}")
    await server.start()
    log.info("grpc_server_started", port=bound)
    return server, bound
