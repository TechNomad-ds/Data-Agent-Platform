"""缓存服务 - Redis 缓存层"""
import json
from typing import Any, Optional

from app.core.redis_client import get_redis


async def cache_get(key: str) -> Optional[Any]:
    redis = await get_redis()
    data = await redis.get(key)
    if data:
        return json.loads(data)
    return None


async def cache_set(key: str, value: Any, ttl: int = 300) -> None:
    redis = await get_redis()
    await redis.setex(key, ttl, json.dumps(value, ensure_ascii=False, default=str))


async def cache_delete(key: str) -> None:
    redis = await get_redis()
    await redis.delete(key)


async def cache_delete_pattern(pattern: str) -> None:
    redis = await get_redis()
    keys = []
    async for key in redis.scan_iter(match=pattern):
        keys.append(key)
    if keys:
        await redis.delete(*keys)
