"""Redis 客户端 - 连接池管理"""
import redis.asyncio as aioredis
from typing import Optional

from app.config import settings

_pool: Optional[aioredis.Redis] = None


async def get_redis() -> aioredis.Redis:
    global _pool
    if _pool is None:
        _pool = aioredis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
            max_connections=50,
        )
    return _pool


async def close_redis():
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
