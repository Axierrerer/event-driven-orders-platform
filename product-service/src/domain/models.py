from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, Field

from events import Currency, Money

AttributeValue = str | int | bool
Attributes = Annotated[dict[str, AttributeValue], Field(max_length=50)]
ImageUrl = Annotated[str, Field(min_length=1, max_length=500)]


class Product(BaseModel):
    id: UUID
    sku: str
    name: str
    description: str
    category_id: UUID | None
    price: Money
    currency: Currency
    attributes: dict[str, AttributeValue]
    images: list[str]
    is_published: bool
    is_deleted: bool
    version: int
    created_at: datetime
    updated_at: datetime


class Category(BaseModel):
    id: UUID
    name: str
    description: str
    created_at: datetime


class ProductSort(StrEnum):
    RELEVANCE = "relevance"
    PRICE_ASC = "price"
    PRICE_DESC = "-price"
    NEWEST = "-created_at"
    OLDEST = "created_at"


@dataclass(frozen=True)
class ProductFilter:
    text: str | None = None
    category_id: UUID | None = None
    price_min: Decimal | None = None
    price_max: Decimal | None = None
    include_unpublished: bool = False


@dataclass(frozen=True)
class Page[T]:
    items: list[T]
    total: int
    limit: int
    offset: int
