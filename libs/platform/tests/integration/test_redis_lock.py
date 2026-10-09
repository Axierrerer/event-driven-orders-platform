import asyncio

import pytest
from redis.asyncio import Redis

from platform_lib.locks import LockNotAcquiredError, RedisLock

pytestmark = pytest.mark.integration


async def test_only_one_holder(redis: Redis) -> None:
    first = RedisLock(redis, "job", ttl_ms=5_000)
    second = RedisLock(redis, "job", ttl_ms=5_000)

    assert await first.acquire()
    assert not await second.acquire()
    assert await first.release()
    assert await second.acquire()


async def test_cannot_release_or_extend_foreign_lock(redis: Redis) -> None:
    owner = RedisLock(redis, "job", ttl_ms=5_000)
    intruder = RedisLock(redis, "job", ttl_ms=5_000)
    await owner.acquire()

    assert not await intruder.release()
    assert not await intruder.extend()
    assert await redis.exists("lock:job") == 1


async def test_lock_expires_by_ttl(redis: Redis) -> None:
    crashed = RedisLock(redis, "job", ttl_ms=100)
    await crashed.acquire()
    await asyncio.sleep(0.25)

    assert await RedisLock(redis, "job").acquire()
    assert not await crashed.release()  # истёкшая блокировка уже чужая


async def test_extend_keeps_lock_alive(redis: Redis) -> None:
    lock = RedisLock(redis, "job", ttl_ms=300)
    await lock.acquire()
    await asyncio.sleep(0.2)
    assert await lock.extend()
    await asyncio.sleep(0.2)
    assert not await RedisLock(redis, "job").acquire()


async def test_context_manager(redis: Redis) -> None:
    async with RedisLock(redis, "job"):
        with pytest.raises(LockNotAcquiredError):
            async with RedisLock(redis, "job"):
                pass
    assert await redis.exists("lock:job") == 0


async def test_parallel_contenders_single_winner(redis: Redis) -> None:
    locks = [RedisLock(redis, "job") for _ in range(20)]
    results = await asyncio.gather(*(lock.acquire() for lock in locks))
    assert sum(results) == 1
