import asyncio

import pytest
from redis.asyncio import Redis

from platform_lib.ratelimit import BucketConfig, TokenBucket

pytestmark = pytest.mark.integration


async def test_bucket_allows_capacity_then_refills(redis: Redis) -> None:
    bucket = TokenBucket(redis)
    config = BucketConfig(capacity=3, refill_seconds=0.1)
    decisions = [await bucket.take("k", config) for _ in range(4)]
    assert [d.allowed for d in decisions] == [True, True, True, False]
    assert [d.remaining for d in decisions[:3]] == [2, 1, 0]
    assert 0 < decisions[3].retry_after_seconds <= 0.1
    await asyncio.sleep(0.15)
    assert (await bucket.take("k", config)).allowed


async def test_bucket_is_atomic_and_keys_are_independent(redis: Redis) -> None:
    bucket = TokenBucket(redis)
    config = BucketConfig(capacity=10, refill_seconds=60)
    decisions = await asyncio.gather(*(bucket.take("a", config) for _ in range(50)))
    assert sum(d.allowed for d in decisions) == 10
    assert (await bucket.take("b", config)).allowed
