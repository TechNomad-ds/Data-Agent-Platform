"""限流中间件 - 基于 Redis 滑动窗口"""
import time
from fastapi import Request
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
        # 未认证接口用 IP 限流（防暴力破解和批量注册）
        self.ip_limits = {
            "/api/auth/login": (10, 60),       # 每分钟10次
            "/api/auth/register": (3, 300),    # 每5分钟3次
            "/api/auth/refresh": (10, 60),     # 每分钟10次
        }

    async def dispatch(self, request: Request, call_next):
        if request.method == "OPTIONS":
            return await call_next(request)

        path = request.url.path

        # IP 级限流：针对认证相关接口
        if request.method == "POST":
            for prefix, (limit, window) in self.ip_limits.items():
                if path.startswith(prefix):
                    client_ip = request.client.host if request.client else "unknown"
                    forwarded = request.headers.get("x-forwarded-for")
                    if forwarded:
                        client_ip = forwarded.split(",")[0].strip()
                    blocked = await self._check_rate(f"ip:{client_ip}:{prefix}", limit, window)
                    if blocked:
                        return JSONResponse(
                            status_code=429,
                            content={"detail": "请求过于频繁，请稍后再试"},
                            headers={"Retry-After": str(window)},
                        )
                    break

        # 用户级限流：针对已认证接口
        auth_header = request.headers.get("authorization", "")
        if not auth_header:
            return await call_next(request)

        # 从 JWT 中提取 user_id 作为限流 key
        token = auth_header.replace("Bearer ", "").replace("bearer ", "")
        try:
            import json, base64
            payload = token.split(".")[1]
            padding = 4 - len(payload) % 4
            payload += "=" * padding
            decoded = json.loads(base64.urlsafe_b64decode(payload))
            user_key = decoded.get("sub", token[-16:])
        except Exception:
            user_key = token[-16:]

        limit = self.default_limit
        for prefix, path_limit in self.path_limits.items():
            if path.startswith(prefix) and request.method == "POST":
                limit = path_limit
                break

        blocked = await self._check_rate(
            f"rate:{user_key}:{path.split('/')[2] if len(path.split('/')) > 2 else 'default'}",
            limit,
            self.window,
        )
        if blocked:
            return JSONResponse(
                status_code=429,
                content={"detail": "请求过于频繁，请稍后再试"},
                headers={"Retry-After": str(self.window)},
            )

        return await call_next(request)

    async def _check_rate(self, key: str, limit: int, window: int) -> bool:
        try:
            redis = await get_redis()
            now = time.time()
            pipe = redis.pipeline()
            pipe.zremrangebyscore(key, 0, now - window)
            pipe.zadd(key, {str(now): now})
            pipe.zcard(key)
            pipe.expire(key, window)
            results = await pipe.execute()
            return results[2] > limit
        except Exception:
            return False
