#!/bin/bash
# DataMind Analyst 后端启动脚本（带 .env 加载与 ModelScope 镜像缓存）
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/backend"

# 离线模式：模型已缓存到 ~/.cache/chroma，禁止联网下载兜底
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1

# 生产默认使用 gunicorn 多 worker；WORKERS 可在环境变量里覆盖。
export WORKERS="${WORKERS:-4}"
exec venv/bin/gunicorn app.main:app -c gunicorn.conf.py
