from collections.abc import Iterable
from decimal import Decimal
from typing import Any
from uuid import UUID

from bson.decimal128 import Decimal128
from pymongo import ASCENDING, DESCENDING, ReturnDocument

from src.domain.models import Page, Product, ProductFilter, ProductSort


def _to_doc(product: Product) -> dict[str, Any]:
    return {
        "_id": str(product.id),
        "sku": product.sku,
        "name": product.name,
        "description": product.description,
        "category_id": str(product.category_id) if product.category_id else None,
        "price": Decimal128(str(product.price)),
        "currency": product.currency,
        "attributes": product.attributes,
        "images": product.images,
        "is_published": product.is_published,
        "is_deleted": product.is_deleted,
        "version": product.version,
        "created_at": product.created_at,
        "updated_at": product.updated_at,
    }


def _from_doc(doc: dict[str, Any]) -> Product:
    return Product(
        id=UUID(doc["_id"]),
        sku=doc["sku"],
        name=doc["name"],
        description=doc.get("description", ""),
        category_id=UUID(doc["category_id"]) if doc.get("category_id") else None,
        price=doc["price"].to_decimal(),
        currency=doc["currency"],
        attributes=doc.get("attributes", {}),
        images=doc.get("images", []),
        is_published=doc["is_published"],
        is_deleted=doc["is_deleted"],
        version=doc["version"],
        created_at=doc["created_at"],
        updated_at=doc["updated_at"],
    )


def _decimal(value: Decimal) -> Decimal128:
    return Decimal128(str(value))


class ProductRepository:
    def __init__(self, db: Any) -> None:
        self._products = db.products

    async def insert(self, product: Product, *, session: Any) -> None:
        await self._products.insert_one(_to_doc(product), session=session)

    async def get(self, product_id: UUID, *, session: Any = None) -> Product | None:
        doc = await self._products.find_one(
            {"_id": str(product_id), "is_deleted": False}, session=session
        )
        return _from_doc(doc) if doc else None

    async def get_many(self, product_ids: Iterable[UUID]) -> list[Product]:
        ids = [str(pid) for pid in product_ids]
        docs = await self._products.find({"_id": {"$in": ids}, "is_deleted": False}).to_list(
            len(ids)
        )
        return [_from_doc(doc) for doc in docs]

    async def replace_if_version(
        self, product: Product, expected_version: int | None, *, session: Any
    ) -> Product | None:
        """Сохраняет новую версию документа. None — версия не совпала или товара нет."""
        query: dict[str, Any] = {"_id": str(product.id), "is_deleted": False}
        if expected_version is not None:
            query["version"] = expected_version
        doc = _to_doc(product)
        del doc["_id"], doc["version"], doc["created_at"]
        updated = await self._products.find_one_and_update(
            query,
            {"$set": doc, "$inc": {"version": 1}},
            return_document=ReturnDocument.AFTER,
            session=session,
        )
        return _from_doc(updated) if updated else None

    async def exists_in_category(self, category_id: UUID) -> bool:
        doc = await self._products.find_one(
            {"category_id": str(category_id), "is_deleted": False}, projection={"_id": 1}
        )
        return doc is not None

    async def search(
        self, flt: ProductFilter, sort: ProductSort, *, limit: int, offset: int
    ) -> Page[Product]:
        query: dict[str, Any] = {"is_deleted": False}
        if not flt.include_unpublished:
            query["is_published"] = True
        if flt.text:
            query["$text"] = {"$search": flt.text}
        if flt.category_id:
            query["category_id"] = str(flt.category_id)
        price: dict[str, Decimal128] = {}
        if flt.price_min is not None:
            price["$gte"] = _decimal(flt.price_min)
        if flt.price_max is not None:
            price["$lte"] = _decimal(flt.price_max)
        if price:
            query["price"] = price

        projection: dict[str, Any] | None = None
        order: list[tuple[str, Any]]
        if sort is ProductSort.RELEVANCE and flt.text:
            projection = {"score": {"$meta": "textScore"}}
            order = [("score", {"$meta": "textScore"}), ("_id", ASCENDING)]
        elif sort is ProductSort.PRICE_ASC:
            order = [("price", ASCENDING), ("_id", ASCENDING)]
        elif sort is ProductSort.PRICE_DESC:
            order = [("price", DESCENDING), ("_id", ASCENDING)]
        elif sort is ProductSort.OLDEST:
            order = [("created_at", ASCENDING), ("_id", ASCENDING)]
        else:
            order = [("created_at", DESCENDING), ("_id", ASCENDING)]

        cursor = self._products.find(query, projection).sort(order).skip(offset).limit(limit)
        items = [_from_doc(doc) for doc in await cursor.to_list(limit)]
        total = await self._products.count_documents(query)
        return Page(items=items, total=total, limit=limit, offset=offset)
