#!/bin/bash
# DataMind 后端启动脚本（带 .env 加载与 ModelScope 镜像缓存）
cd /root/datamind/Data-Agent-Platform/backend

# 离线模式：模型已缓存到 ~/.cache/chroma，禁止联网下载兜底
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1

exec venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8002
