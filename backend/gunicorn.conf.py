"""Gunicorn 生产环境配置"""
import multiprocessing
import os

# 绑定地址：默认只监听本机，由 nginx 对外暴露。
bind = os.getenv("BIND", "127.0.0.1:8002")

# Worker 数量：默认 4 个，避免数据库连接池在默认 PostgreSQL 100 连接上限下超配。
# 需要更高并发时，先同步调小 DB_POOL_SIZE/DB_MAX_OVERFLOW 或接入 PgBouncer。
workers = int(os.getenv("WORKERS", min(multiprocessing.cpu_count(), 4)))

# 使用 uvicorn worker 支持 async
worker_class = "uvicorn.workers.UvicornWorker"

# 超时（Agent 对话可能很长）
timeout = 300
graceful_timeout = 30
keepalive = 5

# 日志
accesslog = "-"
errorlog = "-"
loglevel = os.getenv("LOG_LEVEL", "info")

# 不预加载应用：避免 Chroma/embedding/Redis 连接等状态在 fork 后共享造成隐性问题。
preload_app = os.getenv("PRELOAD_APP", "false").lower() in ("1", "true", "yes")

# Worker 重启策略（防止内存泄漏）
max_requests = 1000
max_requests_jitter = 100
