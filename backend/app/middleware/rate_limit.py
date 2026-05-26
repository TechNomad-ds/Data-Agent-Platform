"""限流中间件 - 基于 Redis 滑动窗口"""
import time
from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.core.redis_client import get_redis


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, default_limit: int = 60, window: int = 60):
        super().__init__(app)
        self.default_limit = default_limit
        self.window = window
        self.path_limits = {
            "/api/chat/conversations/": 20,
            "/api/data-spaces/": 30,
            "/api/files": 10,
        }

    async def dispatch(self, request: Request, call_next):
        if request.method == "OPTIONS":
            return await call_next(request)

        auth_header = request.headers.get("authorization", "")
        if not auth_header:
            return await call_next(request)

        user_key = auth_header[-16:]
        path = request.url.path

        limit = self.default_limit
        for prefix, path_limit in self.path_limits.items():
            if path.startswith(prefix) and request.method == "POST":
                limit = path_limit
                break

        try:
            redis = await get_redis()
            key = f"rate:{user_key}:{path.split('/')[2] if len(path.split('/')) > 2 else 'default'}"
            now = time.time()

            pipe = redis.pipeline()
            pipe.zremrangebyscore(key, 0, now - self.window)
            pipe.zadd(key, {str(now): now})
            pipe.zcard(key)
            pipe.expire(key, self.window)
            results = await pipe.execute()

            current_count = results[2]
            if current_count > limit:
                return JSONResponse(
                    status_code=429,
                    content={"detail": "请求过于频繁，请稍后再试"},
                    headers={"Retry-After": str(self.window)},
                )
        except Exception:
            pass

        return await call_next(request)
