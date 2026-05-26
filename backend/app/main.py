"""FastAPI 应用入口"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.core.database import Base, get_engine
from app.routers import auth, files, data_spaces, chat, credits, feedback, admin, models, reports, suggestions, datasources, graph, user_settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    from app.seed import seed_models
    await seed_models()
    yield


app = FastAPI(
    title="Data Agent Platform",
    description="多租户数据智能交互平台",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url, "http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
app.include_router(graph.router, prefix="/api/data-spaces", tags=["知识图谱"])
app.include_router(user_settings.router, prefix="/api/settings", tags=["用户设置"])


@app.get("/api/health")
async def health_check():
    return {"status": "ok", "version": "0.1.0"}
