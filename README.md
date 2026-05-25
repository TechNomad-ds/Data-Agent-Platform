# Data Agent Platform

多租户数据智能交互平台。用户上传数据，组织为数据空间，通过自然语言与 Data Agent 交互完成数据分析、文档问答、代码执行等任务。

## 快速开始

```bash
# 1. 复制环境变量
cp .env.example .env
# 编辑 .env 填入你的 LLM API 配置

# 2. 启动基础服务
docker-compose up -d postgres redis chroma

# 3. 启动后端
cd backend
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload --port 8000

# 4. 启动前端
cd frontend
npm install
npm run dev
```

## 技术栈

- **后端**: Python 3.11 + FastAPI + SQLAlchemy + Alembic
- **前端**: React 18 + Ant Design 5 + Vite + Zustand
- **数据库**: PostgreSQL + ChromaDB (向量)
- **缓存**: Redis
- **LLM**: OpenAI 标准格式 API 中转站
