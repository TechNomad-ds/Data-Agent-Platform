<h1 align="center">DataMind Platform</h1>

<p align="center">
  <b>AI-powered data interaction platform for business teams</b><br/>
  Upload data · Ask questions · Auto visualization · Export reports
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.11-3776ab" alt="Python" />
  <img src="https://img.shields.io/badge/FastAPI-0.115-009688" alt="FastAPI" />
  <img src="https://img.shields.io/badge/React-18-61dafb" alt="React" />
  <img src="https://img.shields.io/badge/PostgreSQL-16-336791" alt="PostgreSQL" />
  <img src="https://img.shields.io/badge/Redis-7-dc382d" alt="Redis" />
  <img src="https://img.shields.io/badge/ChromaDB-vector-7a5af8" alt="ChromaDB" />
  <img src="https://img.shields.io/badge/LLM-Anthropic_%7C_OpenAI-orange" alt="LLM" />
  <img src="https://img.shields.io/badge/tests-pytest-0a9edc" alt="Tests" />
</p>

<p align="center">
  English | <a href="README.zh-CN.md">简体中文</a>
</p>

<p align="center">
  <a href="#overview">Overview</a> ·
  <a href="#core-capabilities">Capabilities</a> ·
  <a href="#quick-start">Quick Start</a> ·
  <a href="#production-deployment">Deployment</a> ·
  <a href="#architecture">Architecture</a> ·
  <a href="#api-reference">API</a>
</p>

---

## Table of Contents

- [Overview](#overview)
- [Who It Helps](#who-it-helps)
- [Core Capabilities](#core-capabilities)
- [Requirements](#requirements)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [Production Deployment](#production-deployment)
- [Operations CLI](#operations-cli)
- [Testing](#testing)
- [Architecture](#architecture)
- [Tech Stack](#tech-stack)
- [Agent Tools](#agent-tools)
- [Supported Data Formats](#supported-data-formats)
- [API Reference](#api-reference)
- [Project Structure](#project-structure)
- [Security Checklist](#security-checklist)
- [Troubleshooting](#troubleshooting)
- [Contributing](#contributing)

---

## Overview

DataMind Platform is an AI-native analytics workspace that lets non-technical users analyze data through natural language conversations.

Instead of waiting for SQL/Python support for every ad-hoc request, teams can:

1. Upload business data files or connect data sources
2. Ask analytical questions in plain language
3. Get charts, explanations, and exportable reports in minutes

Behind the UI is a multi-step agent workflow that can inspect datasets, generate and validate queries, execute tools, visualize findings, and refine answers automatically.

## Who It Helps

| Role | Typical pain point | Outcome with DataMind |
|------|--------------------|-----------------------|
| Business / Operations / Marketing | Cannot write SQL, depends on analysts for every request | Self-service analysis with charts and conclusions |
| Data Analysts | Repeated ad-hoc extraction and reporting | Offload repetitive work and focus on modeling/insights |
| Managers / Leads | Slow reporting cycles and fragmented data visibility | Faster decisions via conversation-first reporting |
| IT / Platform Admins | Security, isolation, and governance concerns | Tenant isolation, quotas, and auditable operations |

---

## Core Capabilities

### Data Ingestion and Understanding
- Supports 20+ formats: CSV, Excel, JSON, Parquet, SQLite, PDF, DOCX, Markdown, Stata/SPSS/SAS, etc.
- Supports ZIP batch upload with auto extraction and encoding detection
- Supports read-only external data source integration (MySQL/PostgreSQL)
- Automatically builds data profiles (schema, missing values, distribution, anomalies)

### Conversational Analytics
- Ask questions in plain language and let the agent choose SQL or Pandas automatically
- Multi-step transparent reasoning and tool execution
- SSE streaming response for real-time interaction
- Smart suggestions to reduce cold start time

### Visualization and Reporting
- One-line chart generation (bar, line, pie, scatter, heatmap via ECharts)
- In-chat charts and report export workflow

### Memory and Knowledge Graph
- User-scoped and space-scoped memory persistence
- Automatic triple extraction from documents
- Hybrid retrieval (vector + BM25 + RRF)

### Multi-tenant Isolation

| Dimension | Isolation strategy |
|----------|--------------------|
| SQL access | Enforced `user_id` filtering |
| File storage | Per-user directory under `storage/{user_id}/` |
| Vector index | Per data-space Chroma collection |
| Memory | `user_id + scope` isolation |
| SQLite engine | Per data-space in-memory DB |
| Agent context | Current user + current space only |

---

## Requirements

| Component | Version | Notes |
|----------|---------|------|
| Python | 3.11+ | Backend runtime |
| Node.js | 18+ | Frontend build/runtime |
| PostgreSQL | 16 | Metadata storage (local or remote) |
| Redis | 7 | Cache and rate limiting (local or remote) |
| LLM API Key | - | Anthropic or OpenAI-compatible provider |

---

## Quick Start

### Option 1: One-command setup (recommended)

```bash
git clone git@github.com:TechNomad-ds/Data-Agent-Platform.git DataMind-Platform
cd DataMind-Platform
cp .env.example .env
# edit .env and set ANTHROPIC_API_KEY or OPENAI_API_KEY
bash deploy.sh
```

`deploy.sh` checks OS and dependencies, installs Python/frontend packages, runs migrations, and builds frontend assets.

### Option 2: Manual setup (macOS example)

```bash
brew install postgresql@16 redis python@3.11 uv
brew services start postgresql@16
brew services start redis
createdb data_agent

git clone git@github.com:TechNomad-ds/Data-Agent-Platform.git DataMind-Platform
cd DataMind-Platform
cp .env.example .env

cd backend
uv venv venv --python $(which python3.11)
uv pip install --python venv/bin/python -r requirements.txt
venv/bin/alembic upgrade head
venv/bin/python manage.py seed
venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8002 --reload

# new terminal
cd frontend
npm install
npm run dev
```

App URL: `http://localhost:5200`  
Backend docs: `http://localhost:8002/docs`

### China network mirror (optional)

```bash
export UV_INDEX_URL="https://pypi.tuna.tsinghua.edu.cn/simple"
npm config set registry https://registry.npmmirror.com
```

---

## Configuration

Copy `.env.example` to `.env` in project root.

Minimal required setup:

```bash
LLM_BACKEND=anthropic
ANTHROPIC_API_KEY=sk-ant-xxx
# or OpenAI-compatible provider
OPENAI_API_BASE=https://api.deepseek.com/v1
OPENAI_API_KEY=sk-xxx
OPENAI_MODEL=deepseek-chat
```

Common settings:

| Key | Description |
|-----|-------------|
| `DATABASE_URL` | Async PostgreSQL DSN |
| `REDIS_URL` | Redis DSN |
| `SECRET_KEY` | JWT signing key (must change in production) |
| `RETRIEVAL_MODE` | `vector` / `bm25` / `hybrid` / `multi_query` |
| `GRAPH_AUTO_EXTRACT` | Auto knowledge graph extraction |
| `DAILY_FREE_CREDITS` | Daily free usage quota |
| `MAX_CREDITS_PER_RUN` | Per-run usage cap |
| `BACKEND_PORT` | API service port |
| `FRONTEND_URL` | CORS origin |

---

## Production Deployment

Recommended stack: `Gunicorn + UvicornWorker + Nginx`.

### Backend

```bash
cd backend
venv/bin/gunicorn app.main:app -c gunicorn.conf.py
```

`gunicorn.conf.py` already includes:
- worker sizing (`CPU * 2 + 1`, capped at 8)
- `timeout=300` for long-running agent interactions
- `preload_app=True`, `max_requests=1000` for stability

### Frontend

```bash
cd frontend
npm run build
```

Serve `frontend/dist/` with Nginx. See `frontend/nginx.conf`.

### systemd example

```ini
[Unit]
Description=DataMind Platform Backend
After=network.target postgresql.service redis.service

[Service]
WorkingDirectory=/opt/DataMind-Platform/backend
ExecStart=/opt/DataMind-Platform/backend/venv/bin/gunicorn app.main:app -c gunicorn.conf.py
Restart=always
EnvironmentFile=/opt/DataMind-Platform/.env

[Install]
WantedBy=multi-user.target
```

### Backups

Use `backup.sh` for database/storage backup automation.

---

## Operations CLI

```bash
cd backend
venv/bin/python manage.py create-admin
venv/bin/python manage.py reset-password EMAIL
venv/bin/python manage.py stats
venv/bin/python manage.py list-models
venv/bin/python manage.py seed
```

---

## Testing

```bash
cd backend
venv/bin/pytest
venv/bin/pytest tests/test_auth.py -v
venv/bin/pytest -k security
```

Main coverage includes auth, chat, credits, data spaces, files, security, services, suggestions, and health checks.

---

## Architecture

```text
Browser (React + Ant Design + ECharts)
    -> FastAPI (Auth / Data Spaces / Chat / Agent Loop)
        -> Agent Tools (search, sql, pandas, python, chart, memory, graph)
            -> PostgreSQL / Redis / ChromaDB / LLM Provider
```

---

## Tech Stack

| Layer | Technologies |
|------|--------------|
| Frontend | React 18, TypeScript 5, Vite 5, Ant Design 5, ECharts 5, Zustand |
| Backend | FastAPI 0.115, SQLAlchemy 2 async, Pydantic 2 |
| Database | PostgreSQL 16 |
| Cache | Redis 7 |
| Vector DB | ChromaDB 0.5 |
| Retrieval | BM25 + Vector + RRF |
| Embedding | sentence-transformers |
| LLM | Anthropic / OpenAI-compatible |
| Production | Gunicorn + UvicornWorker + Nginx |

---

## Agent Tools

DataMind exposes 14 agent tools:

`search_data_space`, `read_file`, `inspect_data`, `pandas_query`, `sqlite_query`, `execute_python`, `generate_chart`, `save_memory`, `nl2sql`, `kb_reindex_file`, `db_import_csv`, `graph_search`, `graph_traverse`, `graph_extract_from_text`

---

## Supported Data Formats

| Category | Formats |
|---------|---------|
| Tabular | CSV, TSV, Excel, JSON, JSONL, Parquet, Feather |
| Databases | SQLite, MySQL (remote), PostgreSQL (remote) |
| Documents | PDF, DOCX, TXT, Markdown |
| Code | Python, SQL, R, HTML, XML, YAML |
| Statistical | Stata, SPSS, SAS |
| Images | PNG, JPG, GIF, BMP, WebP |
| Archive | ZIP |

---

## API Reference

Swagger: `http://localhost:8002/docs`

Key endpoints:

| Method | Path | Purpose |
|-------|------|---------|
| POST | `/api/auth/login` | Sign in |
| POST | `/api/auth/register` | Sign up |
| POST | `/api/files/upload` | Upload files |
| POST | `/api/data-spaces/{id}/upload` | Upload files to a data space |
| GET | `/api/data-spaces/{id}/profile` | Get data profile |
| GET | `/api/data-spaces/{id}/suggestions` | Intelligent suggestions |
| POST | `/api/chat/conversations/{id}/messages` | Agent chat (SSE) |
| POST | `/api/reports/generate` | Export report |

> Note: `backend/app/routers/graph.py` exists, but it is not currently mounted in `backend/app/main.py`.

---

## Project Structure

```text
DataMind-Platform/
├── backend/
│   ├── app/
│   │   ├── agent/
│   │   ├── core/
│   │   ├── middleware/
│   │   ├── models/         # 12 ORM models across 10 model files
│   │   ├── routers/        # 13 API router modules
│   │   ├── schemas/
│   │   ├── services/
│   │   ├── indexing/
│   │   ├── config.py
│   │   └── main.py
│   ├── alembic/
│   ├── tests/
│   ├── gunicorn.conf.py
│   ├── manage.py
│   └── requirements.txt
├── frontend/
│   └── src/
│       ├── pages/          # Admin, Credits, DataSpaces, Files, Login, Register, Settings
│       ├── components/
│       ├── api/
│       ├── stores/
│       └── theme/
├── deploy.sh
├── backup.sh
└── .env.example
```

---

## Security Checklist

- Change default admin password immediately
- Set a strong random `SECRET_KEY` for production
- Never commit `.env` or credentials
- Use dedicated DB/Redis users with network restrictions
- Keep external data source access read-only

---

## Troubleshooting

| Symptom | Resolution |
|--------|------------|
| DB connection failure at startup | Verify PostgreSQL is running and `DATABASE_URL` is correct |
| `alembic upgrade head` fails | Check DB permissions and run in `backend/` |
| Frontend works but API returns CORS/401 | Verify `FRONTEND_URL` in `.env` |
| No models available in admin/chat | Run `python manage.py seed` and verify API key |
| Slow package install | Use mirror settings shown above |
| Long chat interrupted | Use production gunicorn config with `timeout=300` |

---

## Contributing

1. Create feature branches from `main` (e.g. `feat/*`, `fix/*`, `docs/*`)
2. Prefer Conventional Commits
3. Run backend tests before opening a PR
4. Include Alembic migrations for schema changes
