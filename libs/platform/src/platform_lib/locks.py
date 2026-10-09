"""Распределённая блокировка на одном узле Redis: SET NX PX + токен владельца.

Снять или продлить блокировку может только её владелец (проверка токена в Lua-скрипте),
по истечении TTL она освобождается сама — упавший процесс не держит её вечно.
"""

import secrets
from types import TracebackType
from typing import Self

from redis.asyncio import Redis

_RELEASE = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
end
return 0
"""

_EXTEND = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('pexpire', KEYS[1], ARGV[2])
end
return 0
"""


class LockNotAcquiredError(RuntimeError):
    pass


class RedisLock:
    def __init__(self, redis: Redis, name: str, ttl_ms: int = 30_000) -> None:
        self._redis = redis
        self.name = f"lock:{name}"
        self.ttl_ms = ttl_ms
        self._token = secrets.token_hex(16)

    async def acquire(self) -> bool:
        return bool(await self._redis.set(self.name, self._token, nx=True, px=self.ttl_ms))

    async def release(self) -> bool:
        result = await self._redis.eval(_RELEASE, 1, self.name, self._token)
        return bool(result)

    async def extend(self) -> bool:
        result = await self._redis.eval(_EXTEND, 1, self.name, self._token, str(self.ttl_ms))
        return bool(result)

    async def __aenter__(self) -> Self:
        if not await self.acquire():
            raise LockNotAcquiredError(self.name)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.release()
