from collections.abc import AsyncIterator

import grpc
import pytest
from httpx import AsyncClient
from orders_proto.inventory.v1 import inventory_pb2, inventory_pb2_grpc
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from events import Role, uuid7
from platform_lib.testing import TokenFactory
from src import db

from ..conftest import Handle, order_created, put_stock, stock_row

pytestmark = pytest.mark.integration


@pytest.fixture
async def stub(client: AsyncClient) -> AsyncIterator[inventory_pb2_grpc.InventoryServiceStub]:
    port = client.app.state.grpc_port  # type: ignore[attr-defined]
    async with grpc.aio.insecure_channel(f"localhost:{port}") as channel:
        yield inventory_pb2_grpc.InventoryServiceStub(channel)  # type: ignore[no-untyped-call]


def item(product_id: object, quantity: int) -> inventory_pb2.Item:
    return inventory_pb2.Item(product_id=str(product_id), quantity=quantity)


# ---------- gRPC ----------


async def test_check_availability_reports_per_item_without_changes(
    stub: inventory_pb2_grpc.InventoryServiceStub,
    handle: Handle,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    mug, plate, unknown = uuid7(), uuid7(), uuid7()
    await put_stock(session_factory, mug, 5)
    await put_stock(session_factory, plate, 3)
    await handle(order_created([(plate, 2)]))  # доступно 1 из 3

    ok = await stub.CheckAvailability(
        inventory_pb2.CheckAvailabilityRequest(items=[item(mug, 2), item(mug, 3), item(plate, 1)])
    )
    assert ok.available is True
    assert {(i.product_id, i.requested, i.available) for i in ok.items} == {
        (str(mug), 5, 5),
        (str(plate), 1, 1),
    }

    short = await stub.CheckAvailability(
        inventory_pb2.CheckAvailabilityRequest(items=[item(plate, 2), item(unknown, 1)])
    )
    assert short.available is False
    assert {(i.product_id, i.available) for i in short.items} == {
        (str(plate), 1),
        (str(unknown), 0),
    }

    assert await stock_row(session_factory, mug) == (5, 0)  # только чтение
    assert await stock_row(session_factory, plate) == (3, 2)


@pytest.mark.parametrize(
    "items",
    [[], [inventory_pb2.Item(product_id="nope", quantity=1)], [item(uuid7(), 0)]],
    ids=["empty", "bad-id", "zero-quantity"],
)
async def test_check_availability_validates_input(
    stub: inventory_pb2_grpc.InventoryServiceStub, items: list[inventory_pb2.Item]
) -> None:
    with pytest.raises(grpc.aio.AioRpcError) as exc:
        await stub.CheckAvailability(inventory_pb2.CheckAvailabilityRequest(items=items))
    assert exc.value.code() == grpc.StatusCode.INVALID_ARGUMENT


# ---------- REST ----------


async def test_staff_reads_and_adjusts_stock(
    client: AsyncClient, tokens: TokenFactory, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    mug = uuid7()
    await put_stock(session_factory, mug, 5)
    manager_id = uuid7()
    headers = tokens.headers(manager_id, [Role.MANAGER])

    stock = await client.get(f"/api/v1/inventory/stock/{mug}", headers=headers)
    assert stock.json() == {"product_id": str(mug), "on_hand": 5, "reserved": 0, "available": 5}

    adjusted = await client.post(
        f"/api/v1/inventory/stock/{mug}/adjust",
        json={"delta": 10, "reason": "поставка №42"},
        headers=headers,
    )
    assert adjusted.status_code == 200
    assert adjusted.json()["on_hand"] == 15

    async with session_factory() as session:
        movement = (
            await session.execute(
                select(db.stock_movements).where(db.stock_movements.c.reason == "ADJUST")
            )
        ).one()
    assert movement.delta_on_hand == 10
    assert movement.comment == "поставка №42"
    assert movement.ref_id == manager_id


async def test_adjust_below_reserved_conflicts(
    client: AsyncClient,
    tokens: TokenFactory,
    handle: Handle,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    mug = uuid7()
    await put_stock(session_factory, mug, 5)
    await handle(order_created([(mug, 3)]))
    headers = tokens.headers(uuid7(), [Role.ADMIN])

    response = await client.post(
        f"/api/v1/inventory/stock/{mug}/adjust",
        json={"delta": -3, "reason": "списание"},
        headers=headers,
    )
    assert response.status_code == 409
    assert await stock_row(session_factory, mug) == (5, 3)


async def test_stock_endpoints_require_staff_and_known_product(
    client: AsyncClient, tokens: TokenFactory
) -> None:
    url = f"/api/v1/inventory/stock/{uuid7()}"
    assert (await client.get(url)).status_code == 401
    assert (await client.get(url, headers=tokens.headers(uuid7(), [Role.USER]))).status_code == 403
    admin = tokens.headers(uuid7(), [Role.ADMIN])
    assert (await client.get(url, headers=admin)).status_code == 404
    response = await client.post(f"{url}/adjust", json={"delta": 1, "reason": "x"}, headers=admin)
    assert response.status_code == 404
