from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status

from events import Role
from platform_lib.auth import OptionalPrincipal, Principal, require_roles
from src.api.schemas import (
    CategoryCreate,
    CategoryOut,
    CategoryPatch,
    ProductCreate,
    ProductFields,
    ProductOut,
    ProductPage,
    ProductPatch,
)
from src.domain.models import Product, ProductFilter, ProductSort
from src.services.catalog import CatalogService, can_see_unpublished

products = APIRouter(prefix="/api/v1/products", tags=["products"])
categories = APIRouter(prefix="/api/v1/categories", tags=["categories"])


def get_catalog(request: Request) -> CatalogService:
    service: CatalogService = request.app.state.catalog
    return service


Catalog = Annotated[CatalogService, Depends(get_catalog)]
Admin = Annotated[Principal, Depends(require_roles(Role.ADMIN))]
Staff = Annotated[Principal, Depends(require_roles(Role.ADMIN, Role.MANAGER))]
Price = Annotated[Decimal | None, Query(ge=0, max_digits=12, decimal_places=2)]


def etag(product: Product) -> str:
    return f'"{product.version}"'


def parse_if_match(if_match: str | None) -> int | None:
    if if_match is None:
        return None
    value = if_match.strip().removeprefix("W/").strip('"')
    if not value.isdigit():
        raise HTTPException(status.HTTP_412_PRECONDITION_FAILED, detail="invalid If-Match")
    return int(value)


def respond(product: Product, response: Response) -> ProductOut:
    response.headers["ETag"] = etag(product)
    return ProductOut.of(product)


IfMatch = Annotated[str | None, Header(alias="If-Match")]


# ---------------- товары ----------------


@products.get("", response_model=ProductPage)
async def search_products(
    catalog: Catalog,
    principal: OptionalPrincipal,
    q: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
    category: UUID | None = None,
    price_min: Price = None,
    price_max: Price = None,
    sort: ProductSort = ProductSort.RELEVANCE,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0, le=10_000)] = 0,
) -> ProductPage:
    page = await catalog.search(
        ProductFilter(
            text=q,
            category_id=category,
            price_min=price_min,
            price_max=price_max,
            include_unpublished=can_see_unpublished(principal),
        ),
        sort,
        limit=limit,
        offset=offset,
    )
    return ProductPage(
        items=[ProductOut.of(p) for p in page.items],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
    )


@products.get("/{product_id}", response_model=ProductOut)
async def get_product(
    product_id: UUID, catalog: Catalog, principal: OptionalPrincipal, response: Response
) -> ProductOut:
    return respond(await catalog.get_product(product_id, principal), response)


@products.post("", status_code=status.HTTP_201_CREATED, response_model=ProductOut)
async def create_product(
    body: ProductCreate, _admin: Admin, catalog: Catalog, response: Response
) -> ProductOut:
    product = await catalog.create_product(body.model_dump())
    response.headers["Location"] = f"/api/v1/products/{product.id}"
    return respond(product, response)


@products.put("/{product_id}", response_model=ProductOut)
async def replace_product(
    product_id: UUID,
    body: ProductFields,
    _admin: Admin,
    catalog: Catalog,
    response: Response,
    if_match: IfMatch = None,
) -> ProductOut:
    product = await catalog.update_product(
        product_id, body.model_dump(), expected_version=parse_if_match(if_match)
    )
    return respond(product, response)


@products.patch("/{product_id}", response_model=ProductOut)
async def patch_product(
    product_id: UUID,
    body: ProductPatch,
    _admin: Admin,
    catalog: Catalog,
    response: Response,
    if_match: IfMatch = None,
) -> ProductOut:
    changes = body.model_dump(exclude_unset=True)
    required = {"sku", "name", "price", "currency", "attributes", "images", "description"}
    if any(changes.get(field) is None for field in required & changes.keys()):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="field cannot be null")
    product = await catalog.update_product(
        product_id, changes, expected_version=parse_if_match(if_match)
    )
    return respond(product, response)


@products.post("/{product_id}/publish", response_model=ProductOut)
async def publish(
    product_id: UUID, _staff: Staff, catalog: Catalog, response: Response
) -> ProductOut:
    return respond(await catalog.set_published(product_id, True), response)


@products.post("/{product_id}/unpublish", response_model=ProductOut)
async def unpublish(
    product_id: UUID, _staff: Staff, catalog: Catalog, response: Response
) -> ProductOut:
    return respond(await catalog.set_published(product_id, False), response)


@products.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_product(product_id: UUID, _admin: Admin, catalog: Catalog) -> Response:
    await catalog.delete_product(product_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------- категории ----------------


@categories.get("", response_model=list[CategoryOut])
async def list_categories(catalog: Catalog) -> list[CategoryOut]:
    return [CategoryOut.model_validate(c.model_dump()) for c in await catalog.list_categories()]


@categories.post("", status_code=status.HTTP_201_CREATED, response_model=CategoryOut)
async def create_category(body: CategoryCreate, _admin: Admin, catalog: Catalog) -> CategoryOut:
    category = await catalog.create_category(body.name, body.description)
    return CategoryOut.model_validate(category.model_dump())


@categories.patch("/{category_id}", response_model=CategoryOut)
async def update_category(
    category_id: UUID, body: CategoryPatch, _admin: Admin, catalog: Catalog
) -> CategoryOut:
    values = body.model_dump(exclude_unset=True, exclude_none=True)
    category = await catalog.update_category(category_id, values)
    return CategoryOut.model_validate(category.model_dump())


@categories.delete("/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_category(category_id: UUID, _admin: Admin, catalog: Catalog) -> Response:
    await catalog.delete_category(category_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
