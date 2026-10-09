from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from events import Role
from platform_lib.auth import Principal, require_roles
from src.domain.models import StockLevel
from src.services.inventory import InventoryService

router = APIRouter(prefix="/api/v1/inventory", tags=["inventory"])


def get_inventory(request: Request) -> InventoryService:
    service: InventoryService = request.app.state.inventory
    return service


Inventory = Annotated[InventoryService, Depends(get_inventory)]
Staff = Annotated[Principal, Depends(require_roles(Role.MANAGER, Role.ADMIN))]


class StockOut(BaseModel):
    product_id: UUID
    on_hand: int
    reserved: int
    available: int

    @classmethod
    def of(cls, level: StockLevel) -> "StockOut":
        return cls(
            product_id=level.product_id,
            on_hand=level.on_hand,
            reserved=level.reserved,
            available=level.available,
        )


class AdjustRequest(BaseModel):
    delta: int = Field(ge=-1_000_000, le=1_000_000)
    reason: str = Field(min_length=1, max_length=500)


@router.get("/stock/{product_id}", response_model=StockOut)
async def get_stock(product_id: UUID, _staff: Staff, inventory: Inventory) -> StockOut:
    return StockOut.of(await inventory.get_stock(product_id))


@router.post("/stock/{product_id}/adjust", response_model=StockOut)
async def adjust_stock(
    product_id: UUID, body: AdjustRequest, staff: Staff, inventory: Inventory
) -> StockOut:
    level = await inventory.adjust(product_id, body.delta, comment=body.reason, actor=staff.user_id)
    return StockOut.of(level)
