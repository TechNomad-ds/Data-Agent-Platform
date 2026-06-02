"""Gunicorn 生产环境配置"""
import multiprocessing
import os

# 绑定地址
bind = os.getenv("BIND", "0.0.0.0:8002")

# Worker 数量：CPU 核心数 * 2 + 1（适合 IO 密集型）
workers = int(os.getenv("WORKERS", min(multiprocessing.cpu_count() * 2 + 1, 8)))

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

# 预加载应用（共享内存，减少启动时间）
preload_app = True

# Worker 重启策略（防止内存泄漏）
max_requests = 1000
max_requests_jitter = 100
