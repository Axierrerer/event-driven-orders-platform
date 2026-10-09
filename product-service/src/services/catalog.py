"""Сценарии каталога. Изменения товара и событие product.changed — в одной транзакции MongoDB."""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pymongo.errors import DuplicateKeyError

from events import ProductChanged, ProductChangedPayload, Role, uuid7
from platform_lib.auth import Principal
from platform_lib.logging import get_logger
from platform_lib.outbox import MongoOutbox
from src.domain.errors import (
    CategoryInUseError,
    CategoryNotFoundError,
    DuplicateCategoryError,
    DuplicateSkuError,
    InvalidFilterError,
    ProductNotFoundError,
    VersionConflictError,
)
from src.domain.models import Category, Page, Product, ProductFilter, ProductSort
from src.repositories.categories import CategoryRepository
from src.repositories.products import ProductRepository
from src.services.cache import ProductCache

log = get_logger(__name__)

SERVICE_NAME = "product-service"
MAX_BATCH = 100


def can_see_unpublished(principal: Principal | None) -> bool:
    return principal is not None and principal.has_any({Role.ADMIN, Role.MANAGER})


class CatalogService:
    def __init__(
        self,
        client: Any,
        db: Any,
        cache: ProductCache,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._client = client
        self._products = ProductRepository(db)
        self._categories = CategoryRepository(db)
        self._outbox = MongoOutbox(db.outbox)
        self._cache = cache
        self._now = clock

    # ---------- чтение ----------

    async def get_product(self, product_id: UUID, principal: Principal | None) -> Product:
        product = await self._cache.get(product_id)
        if product is None:
            product = await self._products.get(product_id)
            if product is None:
                raise ProductNotFoundError
            await self._cache.put(product)
        if not product.is_published and not can_see_unpublished(principal):
            raise ProductNotFoundError  # неопубликованный товар для покупателя не существует
        return product

    async def get_for_internal(self, product_id: UUID) -> Product | None:
        """Для gRPC: включая неопубликованные (решение о продаже принимает вызывающий)."""
        product = await self._cache.get(product_id)
        if product is None:
            product = await self._products.get(product_id)
            if product is not None:
                await self._cache.put(product)
        return product

    async def get_many_for_internal(self, product_ids: list[UUID]) -> list[Product]:
        if len(product_ids) > MAX_BATCH:
            raise InvalidFilterError(f"не более {MAX_BATCH} товаров за запрос")
        return await self._products.get_many(product_ids)

    async def search(
        self,
        flt: ProductFilter,
        sort: ProductSort,
        *,
        limit: int,
        offset: int,
    ) -> Page[Product]:
        if (
            flt.price_min is not None
            and flt.price_max is not None
            and flt.price_min > flt.price_max
        ):
            raise InvalidFilterError("price_min больше price_max")
        return await self._products.search(flt, sort, limit=limit, offset=offset)

    # ---------- изменение товаров ----------

    async def create_product(self, data: dict[str, Any]) -> Product:
        await self._ensure_category(data.get("category_id"))
        now = self._now()
        product = Product(
            id=uuid7(),
            is_deleted=False,
            version=1,
            created_at=now,
            updated_at=now,
            **data,
        )
        try:
            async with await self._client.start_session() as session:
                async with session.start_transaction():
                    await self._products.insert(product, session=session)
                    await self._publish(product, session)
        except DuplicateKeyError as exc:
            raise DuplicateSkuError(product.sku) from exc
        log.info("product_created", product_id=str(product.id))
        return product

    async def update_product(
        self,
        product_id: UUID,
        changes: dict[str, Any],
        *,
        expected_version: int | None,
    ) -> Product:
        """Частичное или полное обновление (changes — только изменяемые поля)."""
        if "category_id" in changes:
            await self._ensure_category(changes["category_id"])
        try:
            async with await self._client.start_session() as session:
                async with session.start_transaction():
                    current = await self._products.get(product_id, session=session)
                    if current is None:
                        raise ProductNotFoundError
                    if expected_version is not None and current.version != expected_version:
                        raise VersionConflictError
                    candidate = Product.model_validate(
                        {**current.model_dump(), **changes, "updated_at": self._now()}
                    )
                    saved = await self._products.replace_if_version(
                        candidate, current.version, session=session
                    )
                    if saved is None:
                        raise VersionConflictError
                    await self._publish(saved, session)
        except DuplicateKeyError as exc:
            raise DuplicateSkuError(changes.get("sku", "")) from exc
        await self._cache.invalidate(product_id)
        return saved

    async def set_published(self, product_id: UUID, published: bool) -> Product:
        current = await self._products.get(product_id)
        if current is None:
            raise ProductNotFoundError
        if current.is_published == published:
            return current
        return await self.update_product(
            product_id, {"is_published": published}, expected_version=None
        )

    async def delete_product(self, product_id: UUID) -> None:
        await self.update_product(product_id, {"is_deleted": True}, expected_version=None)
        log.info("product_deleted", product_id=str(product_id))

    async def _publish(self, product: Product, session: Any) -> None:
        await self._outbox.add(
            ProductChanged(
                producer=SERVICE_NAME,
                correlation_id=product.id,
                payload=ProductChangedPayload(
                    product_id=product.id,
                    sku=product.sku,
                    name=product.name,
                    price=product.price,
                    currency=product.currency,
                    is_published=product.is_published,
                    is_deleted=product.is_deleted,
                ),
            ),
            session=session,
        )

    # ---------- категории ----------

    async def _ensure_category(self, category_id: UUID | None) -> None:
        if category_id is not None and await self._categories.get(category_id) is None:
            raise CategoryNotFoundError

    async def list_categories(self) -> list[Category]:
        return await self._categories.list_all()

    async def create_category(self, name: str, description: str) -> Category:
        category = Category(id=uuid7(), name=name, description=description, created_at=self._now())
        try:
            await self._categories.insert(category)
        except DuplicateKeyError as exc:
            raise DuplicateCategoryError(name) from exc
        return category

    async def update_category(self, category_id: UUID, values: dict[str, Any]) -> Category:
        try:
            category = await self._categories.update(category_id, values)
        except DuplicateKeyError as exc:
            raise DuplicateCategoryError(values.get("name", "")) from exc
        if category is None:
            raise CategoryNotFoundError
        return category

    async def delete_category(self, category_id: UUID) -> None:
        if await self._products.exists_in_category(category_id):
            raise CategoryInUseError
        if not await self._categories.delete(category_id):
            raise CategoryNotFoundError
