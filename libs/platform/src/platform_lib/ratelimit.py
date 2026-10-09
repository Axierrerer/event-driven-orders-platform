"""Token bucket в Redis. Весь расчёт — в одном Lua-скрипте, поэтому атомарен при
конкурентных вызовах и при нескольких репликах. Время берётся из Redis (TIME)."""

from dataclasses import dataclass

from redis.asyncio import Redis

_SCRIPT = """
local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local refill_ms = tonumber(ARGV[2])
local t = redis.call('TIME')
local now = tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)
local data = redis.call('HMGET', key, 'tokens', 'ts')
local tokens = tonumber(data[1]) or capacity
local ts = tonumber(data[2]) or now
tokens = math.min(capacity, tokens + math.max(0, now - ts) / refill_ms)
local allowed = 0
local retry_ms = 0
if tokens >= 1 then
    tokens = tokens - 1
    allowed = 1
else
    retry_ms = math.ceil((1 - tokens) * refill_ms)
end
redis.call('HSET', key, 'tokens', tostring(tokens), 'ts', tostring(now))
redis.call('PEXPIRE', key, math.ceil(capacity * refill_ms) + 1000)
return {allowed, retry_ms, math.floor(tokens)}
"""


@dataclass(frozen=True, slots=True)
class BucketConfig:
    capacity: int
    refill_seconds: float  # время на один токен


@dataclass(frozen=True, slots=True)
class Decision:
    allowed: bool
    retry_after_seconds: float
    remaining: int = 0


class TokenBucket:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis
        self._script = redis.register_script(_SCRIPT)

    async def take(self, key: str, config: BucketConfig) -> Decision:
        allowed, retry_ms, remaining = await self._script(
            keys=[f"bucket:{key}"],
            args=[config.capacity, max(int(config.refill_seconds * 1000), 1)],
        )
        return Decision(
            allowed=bool(allowed),
            retry_after_seconds=int(retry_ms) / 1000,
            remaining=int(remaining),
        )
