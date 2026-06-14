"""FastAPI 应用入口"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.core.database import Base, get_engine
from app.routers import auth, files, data_spaces, chat, credits, feedback, admin, models, reports, suggestions, datasources, user_settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    import logging
    logger = logging.getLogger("lifespan")

    from app.seed import seed_models
    await seed_models()

    # 从 Redis 恢复运行时配置（管理员通过后台修改的值）
    try:
        from app.core.redis_client import get_redis
        from app.routers.admin import RUNTIME_CONFIG_KEYS
        redis = await get_redis()
        for key, meta in RUNTIME_CONFIG_KEYS.items():
            cached = await redis.get(f"config:{key}")
            if cached is not None:
                if meta["type"] == "bool":
                    setattr(settings, key, cached.lower() in ("true", "1"))
                else:
                    setattr(settings, key, int(cached))
                logger.info(f"从 Redis 恢复配置: {key}={cached}")
    except Exception as e:
        logger.warning(f"恢复运行时配置失败: {e}")

    # 预热 embedding 模型（在线程池中加载，不阻塞启动），消除首次上传的加载延迟
    try:
        import asyncio
        from app.services.embedding import warmup
        asyncio.get_running_loop().run_in_executor(None, warmup)
        logger.info("embedding 模型预热已在后台启动")
    except Exception as e:
        logger.warning(f"启动 embedding 预热失败: {e}")

    # 启动自愈：补跑因进程重启（--reload / 崩溃 / 部署）而中断的画像任务。
    # 放后台执行，不阻塞启动；避免大量待补文件拖慢服务可用时间。
    try:
        import asyncio
        from app.services.preprocessing import recover_unprocessed_files
        asyncio.create_task(recover_unprocessed_files())
        logger.info("启动自愈任务已在后台启动")
    except Exception as e:
        logger.warning(f"启动自愈任务失败: {e}")

    # 周期清理无主的 SQLite 临时文件（崩溃/中断会遗留 /tmp/space_*.db，长期撑满磁盘）
    try:
        import asyncio
        from app.services.sqlite_engine import periodic_cleanup_loop
        asyncio.create_task(periodic_cleanup_loop())
        logger.info("SQLite 临时文件周期清理已在后台启动")
    except Exception as e:
        logger.warning(f"启动 SQLite 临时文件清理失败: {e}")

    yield

    # 关闭 Redis 连接
    try:
        from app.core.redis_client import close_redis
        await close_redis()
    except Exception as e:
        logger.warning(f"关闭 Redis 连接失败: {e}")

    # 清理 SQLite 临时文件
    try:
        from app.services.sqlite_engine import cleanup_all
        cleanup_all()
    except Exception as e:
        logger.warning(f"清理 SQLite 临时文件失败: {e}")


app = FastAPI(
    title="DataMind Platform",
    description="多租户数据智能交互平台",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS 配置
_cors_origins = [settings.frontend_url]
if settings.cors_origins:
    _cors_origins.extend(o.strip() for o in settings.cors_origins.split(",") if o.strip())
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 安全响应头
from app.middleware.security_headers import SecurityHeadersMiddleware
app.add_middleware(SecurityHeadersMiddleware)

# IP 黑名单
from app.middleware.ip_block import IPBlockMiddleware
app.add_middleware(IPBlockMiddleware)

# 限流中间件
from app.middleware.rate_limit import RateLimitMiddleware
app.add_middleware(RateLimitMiddleware, default_limit=60, window=60)

# 注册路由
app.include_router(auth.router, prefix="/api/auth", tags=["认证"])
app.include_router(files.router, prefix="/api/files", tags=["文件管理"])
app.include_router(data_spaces.router, prefix="/api/data-spaces", tags=["数据空间"])
app.include_router(chat.router, prefix="/api/chat", tags=["对话"])
app.include_router(credits.router, prefix="/api/credits", tags=["额度"])
app.include_router(feedback.router, prefix="/api/feedback", tags=["反馈"])
app.include_router(admin.router, prefix="/api/admin", tags=["管理后台"])
app.include_router(models.router, prefix="/api/models", tags=["模型"])
app.include_router(reports.router, prefix="/api/reports", tags=["报告"])
app.include_router(suggestions.router, prefix="/api/data-spaces", tags=["智能建议"])
app.include_router(datasources.router, prefix="/api/datasources", tags=["外部数据源"])
app.include_router(user_settings.router, prefix="/api/settings", tags=["用户设置"])


@app.get("/api/health")
async def health_check():
    checks = {"version": "0.1.0"}

    # 检查数据库连接
    try:
        from app.core.database import get_session_factory
        async with get_session_factory()() as db:
            from sqlalchemy import text
            await db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {str(e)[:100]}"

    # 检查 Redis 连接
    try:
        from app.core.redis_client import get_redis
        redis = await get_redis()
        await redis.ping()
        checks["redis"] = "ok"
    except Exception as e:
        checks["redis"] = f"error: {str(e)[:100]}"

    all_ok = checks.get("database") == "ok" and checks.get("redis") == "ok"
    checks["status"] = "ok" if all_ok else "degraded"
    return checks
