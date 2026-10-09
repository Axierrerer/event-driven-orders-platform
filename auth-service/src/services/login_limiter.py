import hashlib

from redis.asyncio import Redis


class LoginAttemptLimiter:
    """Счётчик неудачных входов по email в Redis (фиксированное окно).

    В ключе — хеш email, а не сам адрес: персональные данные не попадают в Redis.
    """

    def __init__(self, redis: Redis, *, max_failures: int, window_seconds: int) -> None:
        self._redis = redis
        self._max_failures = max_failures
        self._window = window_seconds

    def _key(self, email: str) -> str:
        return f"login-failures:{hashlib.sha256(email.encode()).hexdigest()}"

    async def retry_after(self, email: str) -> int | None:
        """Сколько секунд ждать, если лимит исчерпан; None — входить можно."""
        key = self._key(email)
        failures = await self._redis.get(key)
        if failures is None or int(failures) < self._max_failures:
            return None
        ttl = await self._redis.ttl(key)
        return max(int(ttl), 1)

    async def register_failure(self, email: str) -> None:
        key = self._key(email)
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.incr(key)
            pipe.expire(key, self._window, nx=True)
            await pipe.execute()

    async def reset(self, email: str) -> None:
        await self._redis.delete(self._key(email))
