from uuid import UUID

from redis.asyncio import Redis

from platform_lib.logging import get_logger
from src.domain.models import Product

log = get_logger(__name__)


class ProductCache:
    """Cache-aside для карточек товара. Ошибки Redis не ломают чтение каталога."""

    def __init__(self, redis: Redis, ttl_seconds: int) -> None:
        self._redis = redis
        self._ttl = ttl_seconds

    @staticmethod
    def _key(product_id: UUID) -> str:
        return f"product:{product_id}"

    async def get(self, product_id: UUID) -> Product | None:
        try:
            raw = await self._redis.get(self._key(product_id))
        except Exception as exc:
            log.warning("product_cache_unavailable", error=str(exc))
            return None
        return Product.model_validate_json(raw) if raw else None

    async def put(self, product: Product) -> None:
        try:
            await self._redis.set(self._key(product.id), product.model_dump_json(), ex=self._ttl)
        except Exception as exc:
            log.warning("product_cache_unavailable", error=str(exc))

    async def invalidate(self, product_id: UUID) -> None:
        try:
            await self._redis.delete(self._key(product_id))
        except Exception as exc:
            log.warning(
                "product_cache_invalidate_failed", error=str(exc), product_id=str(product_id)
            )
