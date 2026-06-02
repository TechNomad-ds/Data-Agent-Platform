"""IP 黑名单中间件 — 管理员通过后台封禁的 IP 直接拒绝"""
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


class IPBlockMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        client_ip = request.client.host if request.client else "unknown"
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            client_ip = forwarded.split(",")[0].strip()

        try:
            from app.core.redis_client import get_redis
            redis = await get_redis()
            if await redis.get(f"ip_block:{client_ip}"):
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Access denied"},
                )
        except Exception:
            pass

        return await call_next(request)
