import asyncio
import logging
import uuid

from redis.asyncio import Redis


logger = logging.getLogger("attendance")


class RedisLease:
    _RENEW = """
    if redis.call('get', KEYS[1]) == ARGV[1] then
        return redis.call('expire', KEYS[1], ARGV[2])
    end
    return 0
    """
    _RELEASE = """
    if redis.call('get', KEYS[1]) == ARGV[1] then
        return redis.call('del', KEYS[1])
    end
    return 0
    """

    def __init__(self, redis_url: str, key: str, ttl_seconds: int = 30):
        self.redis = Redis.from_url(redis_url, decode_responses=True)
        self.key = key
        self.ttl_seconds = ttl_seconds
        self.owner = uuid.uuid4().hex

    async def acquire(self) -> bool:
        return bool(
            await self.redis.set(self.key, self.owner, nx=True, ex=self.ttl_seconds)
        )

    async def keep_alive(self, stop_polling):
        while True:
            await asyncio.sleep(self.ttl_seconds / 3)
            try:
                renewed = await self.redis.eval(
                    self._RENEW, 1, self.key, self.owner, self.ttl_seconds
                )
            except Exception:
                logger.exception(
                    "bot_singleton_lease_lost",
                    extra={"event": "bot_singleton_lease_lost", "reason": "redis_renewal_error"},
                )
                await stop_polling()
                return
            if not renewed:
                logger.critical(
                    "bot_singleton_lease_lost",
                    extra={"event": "bot_singleton_lease_lost", "reason": "owner_changed_or_expired"},
                )
                await stop_polling()
                return

    async def release(self):
        try:
            await self.redis.eval(self._RELEASE, 1, self.key, self.owner)
        finally:
            await self.redis.aclose()
