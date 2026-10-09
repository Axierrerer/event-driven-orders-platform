from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status

from events import OrderStatus
from platform_lib.auth import CurrentPrincipal
from src.api.schemas import CancelRequest, CreateOrderRequest, OrderOut
from src.services.orders import OrderService

router = APIRouter(prefix="/api/v1/orders", tags=["orders"])


def get_orders(request: Request) -> OrderService:
    service: OrderService = request.app.state.orders
    return service


Orders = Annotated[OrderService, Depends(get_orders)]
IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)]


@router.post(
    "",
    response_model=OrderOut,
    status_code=status.HTTP_201_CREATED,
    responses={200: {"description": "Повтор запроса с тем же Idempotency-Key"}},
)
async def create_order(
    body: CreateOrderRequest,
    principal: CurrentPrincipal,
    orders: Orders,
    response: Response,
    idempotency_key: IdempotencyKey,
) -> OrderOut:
    result = await orders.create(
        principal, [(i.product_id, i.quantity) for i in body.items], idempotency_key
    )
    if not result.created:
        response.status_code = status.HTTP_200_OK
    response.headers["Location"] = f"/api/v1/orders/{result.order.id}"
    return OrderOut.of(result.order)


@router.get("", response_model=list[OrderOut])
async def list_orders(
    principal: CurrentPrincipal,
    orders: Orders,
    status_filter: Annotated[OrderStatus | None, Query(alias="status")] = None,
    user_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[OrderOut]:
    found = await orders.list_orders(
        principal, status=status_filter, user_id=user_id, limit=limit, offset=offset
    )
    return [OrderOut.of(order) for order in found]


@router.get("/{order_id}", response_model=OrderOut)
async def get_order(order_id: UUID, principal: CurrentPrincipal, orders: Orders) -> OrderOut:
    return OrderOut.of(await orders.get(principal, order_id))


@router.post("/{order_id}/pay", response_model=OrderOut)
async def pay(order_id: UUID, principal: CurrentPrincipal, orders: Orders) -> OrderOut:
    return OrderOut.of(await orders.pay(principal, order_id))


@router.post("/{order_id}/cancel", response_model=OrderOut)
async def cancel(
    order_id: UUID,
    principal: CurrentPrincipal,
    orders: Orders,
    body: CancelRequest | None = None,
) -> OrderOut:
    reason = body.reason if body else None
    return OrderOut.of(await orders.cancel(principal, order_id, reason))


@router.post("/{order_id}/ship", response_model=OrderOut)
async def ship(order_id: UUID, principal: CurrentPrincipal, orders: Orders) -> OrderOut:
    return OrderOut.of(await orders.ship(principal, order_id))


@router.post("/{order_id}/complete", response_model=OrderOut)
async def complete(order_id: UUID, principal: CurrentPrincipal, orders: Orders) -> OrderOut:
    return OrderOut.of(await orders.complete(principal, order_id))
