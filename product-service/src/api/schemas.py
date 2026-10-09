from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from events import Currency, Money
from src.domain.models import Attributes, AttributeValue, ImageUrl, Product

Sku = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._-]+$")]
Name = Annotated[str, Field(min_length=1, max_length=200)]
Description = Annotated[str, Field(max_length=5000)]
Images = Annotated[list[ImageUrl], Field(max_length=20)]


class ProductFields(BaseModel):
    """Редактируемые поля товара (PUT заменяет их все)."""

    model_config = ConfigDict(extra="forbid")

    sku: Sku
    name: Name
    description: Description = ""
    category_id: UUID | None = None
    price: Money
    currency: Currency = "RUB"
    attributes: Attributes = Field(default_factory=dict)
    images: Images = Field(default_factory=list)


class ProductCreate(ProductFields):
    is_published: bool = False


class ProductPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sku: Sku | None = None
    name: Name | None = None
    description: Description | None = None
    category_id: UUID | None = None
    price: Money | None = None
    currency: Currency | None = None
    attributes: Attributes | None = None
    images: Images | None = None


class ProductOut(BaseModel):
    id: UUID
    sku: str
    name: str
    description: str
    category_id: UUID | None
    price: Money
    currency: str
    attributes: dict[str, AttributeValue]
    images: list[str]
    is_published: bool
    version: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def of(cls, product: Product) -> "ProductOut":
        return cls.model_validate(product.model_dump(exclude={"is_deleted"}))


class ProductPage(BaseModel):
    items: list[ProductOut]
    total: int
    limit: int
    offset: int


class CategoryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name
    description: Description = ""


class CategoryPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name | None = None
    description: Description | None = None


class CategoryOut(BaseModel):
    id: UUID
    name: str
    description: str
    created_at: datetime
