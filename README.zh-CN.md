<h1 align="center">DataMind Analyst</h1>

<p align="center">
  <b>面向业务团队的 AI 数据交互平台</b><br/>
  上传数据 · 对话分析 · 自动可视化 · 报告导出
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
  <a href="README.md">English</a> | 简体中文
</p>

<p align="center">
  <a href="#项目简介">项目简介</a> ·
  <a href="#项目状态">状态</a> ·
  <a href="#截图">截图</a> ·
  <a href="#核心能力">核心能力</a> ·
  <a href="#快速开始">快速开始</a> ·
  <a href="#生产部署">生产部署</a> ·
  <a href="#架构">架构</a> ·
  <a href="#api-参考">API</a>
</p>

---

## 目录

- [项目简介](#项目简介)
- [项目状态](#项目状态)
- [截图](#截图)
- [适用角色](#适用角色)
- [核心能力](#核心能力)
- [环境要求](#环境要求)
- [快速开始](#快速开始)
- [配置说明](#配置说明)
- [生产部署](#生产部署)
- [运维 CLI](#运维-cli)
- [测试](#测试)
- [架构](#架构)
- [技术栈](#技术栈)
- [Agent 工具](#agent-工具)
- [支持的数据格式](#支持的数据格式)
- [API 参考](#api-参考)
- [项目结构](#项目结构)
- [隐私与安全模型](#隐私与安全模型)
- [已知限制](#已知限制)
- [安全清单](#安全清单)
- [故障排查](#故障排查)
- [许可证](#许可证)
- [贡献规范](#贡献规范)

---

## 项目简介

DataMind Analyst 是一个让业务人员通过自然语言直接完成数据分析的 AI 平台。

过去，很多企业的分析需求都要依赖 SQL/Python 人员排队处理。DataMind 把这个流程压缩成一次对话：

1. 上传业务数据文件或接入数据源
2. 用自然语言提出分析问题
3. 实时获得图表、结论和可导出的报告

平台背后不是简单问答机器人，而是可执行多步推理的 Agent：会自动检查数据、生成并校验查询、调用工具、产出可视化，并在必要时自我修正。

## 项目状态

DataMind Analyst 正在持续开发中，适合本地评估、内部试点和自托管实验。生产环境使用前，请完整检查安全清单，替换所有基础设施凭据，并结合你的部署方式验证数据访问边界。

当前仓库尚未包含 Docker Compose 配置，也尚未添加正式开源许可证文件。公开发布前请补充 `LICENSE` 文件。

## 截图

公开发布前建议补充产品截图或短 GIF。推荐展示：

- 数据空间上传与文件画像
- 对话式分析与工具调用过程
- 对话中的自动图表
- 管理后台的模型与额度配置

## 适用角色

| 角色 | 常见痛点 | DataMind 带来的改变 |
|------|----------|---------------------|
| 业务 / 运营 / 市场 | 不会 SQL，分析需求依赖数据团队 | 自助提问，快速拿到图表和结论 |
| 数据分析师 | 大量临时取数和重复报表工作 | 释放重复劳动，聚焦建模和洞察 |
| 管理层 | 报告周期长，跨团队看数困难 | 以对话方式更快获得决策信息 |
| IT / 平台管理员 | 担心权限隔离和数据治理 | 多租户隔离、配额控制、可审计 |

---

## 核心能力

### 数据接入与理解
- 支持 20+ 数据格式：CSV、Excel、JSON、Parquet、SQLite、PDF、DOCX、Markdown、Stata/SPSS/SAS 等
- 支持 ZIP 批量上传、自动解压、编码识别
- 支持只读外部数据源接入（MySQL / PostgreSQL）
- 自动生成数据画像（字段、缺失、分布、异常）

### 对话式分析
- 通过自然语言提问，自动选择 SQL 或 Pandas
- 多步推理 + 工具调用过程可见
- SSE 流式输出，反馈实时
- 智能建议降低冷启动门槛

### 可视化与报告
- 一句话生成图表（柱状、折线、饼图、散点、热力）
- 支持对话结果导出为报告

### 记忆与知识图谱
- 用户级 / 空间级记忆隔离存储
- 文档自动抽取三元组构建图谱
- 混合检索（向量 + BM25 + RRF）

### 多租户隔离

| 维度 | 隔离策略 |
|------|----------|
| SQL 查询 | 强制 `user_id` 过滤 |
| 文件存储 | `storage/{user_id}/` 独立目录 |
| 向量索引 | 每个数据空间独立 collection |
| 记忆 | `user_id + scope` 隔离 |
| SQLite 引擎 | 每个空间独立内存库 |
| Agent 上下文 | 仅当前用户与当前空间 |

---

## 环境要求

| 组件 | 版本 | 说明 |
|------|------|------|
| Python | 3.11+ | 后端运行时 |
| Node.js | 18+ | 前端构建 |
| PostgreSQL | 16 | 元数据存储（本地或远程） |
| Redis | 7 | 缓存与限流（本地或远程） |
| LLM API Key | - | Anthropic 或 OpenAI 兼容服务 |

---

## 快速开始

### 方式一：一键部署（推荐）

```bash
git clone https://github.com/TechNomad-ds/DataMind-Analyst.git DataMind-Analyst
cd DataMind-Analyst
cp .env.example .env
# 运行前先编辑 .env：
# - 将 ADMIN_PASSWORD 改成强密码
# - 将 SECRET_KEY 改成随机密钥
# - 填写 ANTHROPIC_API_KEY 或 OPENAI_API_KEY
bash deploy.sh
```

`deploy.sh` 会检测系统与依赖、安装 Python/前端依赖、执行数据库迁移并构建前端。脚本不会自动创建 PostgreSQL 或 Redis 实例；如果你没有使用本地默认账号，请先在 `.env` 中配置 `DATABASE_URL` 和 `REDIS_URL`。

### 方式二：手动部署（macOS 示例）

```bash
brew install postgresql@16 redis python@3.11 uv
brew services start postgresql@16
brew services start redis
createdb data_agent

git clone https://github.com/TechNomad-ds/DataMind-Analyst.git DataMind-Analyst
cd DataMind-Analyst
cp .env.example .env
# 编辑 .env，修改 ADMIN_PASSWORD、SECRET_KEY 和 LLM API 配置

cd backend
uv venv venv --python $(which python3.11)
uv pip install --python venv/bin/python -r requirements.txt
venv/bin/alembic upgrade head
venv/bin/python manage.py seed
venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8002 --reload

# 新终端
cd frontend
npm install
npm run dev
```

访问地址：
- 前端：`http://localhost:5200`
- 后端文档：`http://localhost:8002/docs`

### 国内网络镜像（可选）

```bash
export UV_INDEX_URL="https://pypi.tuna.tsinghua.edu.cn/simple"
npm config set registry https://registry.npmmirror.com
```

---

## 配置说明

将 `.env.example` 复制为 `.env`：

```bash
SECRET_KEY=change-me-to-a-random-secret
ADMIN_PASSWORD=change-me-before-first-start

# Anthropic
LLM_BACKEND=anthropic
ANTHROPIC_API_KEY=sk-ant-xxx
```

或使用 OpenAI 兼容服务：

```bash
LLM_BACKEND=openai
OPENAI_API_BASE=https://api.deepseek.com/v1
OPENAI_API_KEY=sk-xxx
OPENAI_MODEL=deepseek-chat
```

常用配置项：

| 配置项 | 说明 |
|--------|------|
| `DATABASE_URL` | 异步 PostgreSQL 连接串 |
| `REDIS_URL` | Redis 连接串 |
| `SECRET_KEY` | JWT 签名密钥（生产必须修改） |
| `RETRIEVAL_MODE` | `vector` / `bm25` / `hybrid` / `multi_query` |
| `GRAPH_AUTO_EXTRACT` | 自动图谱抽取 |
| `DAILY_FREE_CREDITS` | 每日免费额度 |
| `MAX_CREDITS_PER_RUN` | 单次运行额度上限 |
| `BACKEND_PORT` | 后端服务端口 |
| `FRONTEND_URL` | 前端域名（CORS） |

服务启动后，管理员也可以在后台调整运行时配置、模型配置、API Key 和额度参数。

---

## 生产部署

推荐组合：`Gunicorn + UvicornWorker + Nginx`。

### 后端

```bash
cd backend
venv/bin/gunicorn app.main:app -c gunicorn.conf.py
```

`gunicorn.conf.py` 已包含：
- Worker 数量由 `WORKERS` 控制，默认 `min(cpu_count, 4)`
- `timeout=300`（长对话场景）
- 默认 `preload_app=false`，避免 Chroma、embedding、Redis 等状态在 fork 后被共享
- `max_requests=1000` 与 jitter，用于 worker 周期性回收

### 前端

```bash
cd frontend
npm run build
```

将 `frontend/dist/` 部署到 Nginx，参考 `frontend/nginx.conf`。

### systemd 示例

```ini
[Unit]
Description=DataMind Analyst Backend
After=network.target postgresql.service redis.service

[Service]
WorkingDirectory=/opt/DataMind-Analyst/backend
ExecStart=/opt/DataMind-Analyst/backend/venv/bin/gunicorn app.main:app -c gunicorn.conf.py
Restart=always
EnvironmentFile=/opt/DataMind-Analyst/.env

[Install]
WantedBy=multi-user.target
```

### 备份

可使用 `backup.sh` 进行数据库与存储目录备份自动化。

### Docker

当前尚未提供 Docker Compose。若面向开源用户发布，建议补充一个最小 `docker-compose.yml`，包含 PostgreSQL、Redis、后端和前端，降低首次试用成本。

---

## 运维 CLI

```bash
cd backend
venv/bin/python manage.py create-admin
venv/bin/python manage.py reset-password EMAIL
venv/bin/python manage.py stats
venv/bin/python manage.py list-models
venv/bin/python manage.py seed
```

---

## 测试

```bash
cd backend
venv/bin/pytest
venv/bin/pytest tests/test_auth.py -v
venv/bin/pytest -k security
```

测试覆盖认证、对话、积分、数据空间、文件、安全、服务、建议与健康检查。

---

## 架构

```text
Browser (React + Ant Design + ECharts)
    -> FastAPI (Auth / Data Spaces / Chat / Agent Loop)
        -> Agent Tools (search, sql, pandas, python, chart, memory, graph)
            -> PostgreSQL / Redis / ChromaDB / LLM Provider
```

---

## 技术栈

| 层级 | 技术 |
|------|------|
| 前端 | React 18, TypeScript 5, Vite 5, Ant Design 5, ECharts 5, Zustand |
| 后端 | FastAPI 0.115, SQLAlchemy 2 async, Pydantic 2 |
| 数据库 | PostgreSQL 16 |
| 缓存 | Redis 7 |
| 向量库 | ChromaDB 0.5 |
| 检索 | BM25 + Vector + RRF |
| 嵌入 | sentence-transformers |
| LLM | Anthropic / OpenAI 兼容 |
| 生产服务 | Gunicorn + UvicornWorker + Nginx |

---

## Agent 工具

当前共 14 个工具：

`search_data_space`, `read_file`, `inspect_data`, `pandas_query`, `sqlite_query`, `execute_python`, `generate_chart`, `save_memory`, `nl2sql`, `kb_reindex_file`, `db_import_csv`, `graph_search`, `graph_traverse`, `graph_extract_from_text`

---

## 支持的数据格式

| 类别 | 格式 |
|------|------|
| 表格 | CSV, TSV, Excel, JSON, JSONL, Parquet, Feather |
| 数据库 | SQLite, MySQL（远程）, PostgreSQL（远程） |
| 文档 | PDF, DOCX, TXT, Markdown |
| 代码 | Python, SQL, R, HTML, XML, YAML |
| 统计软件 | Stata, SPSS, SAS |
| 图片 | PNG, JPG, GIF, BMP, WebP |
| 压缩包 | ZIP |

---

## API 参考

Swagger：`http://localhost:8002/docs`

下方只列出常用接口。完整接口以 FastAPI 自动生成的 OpenAPI 文档为准。

常用接口：

| 方法 | 路径 | 用途 |
|------|------|------|
| POST | `/api/auth/login` | 登录 |
| POST | `/api/auth/register` | 注册 |
| POST | `/api/files/upload` | 通用文件上传 |
| POST | `/api/data-spaces/{id}/upload` | 上传到数据空间 |
| GET | `/api/data-spaces/{id}/profile` | 数据画像 |
| GET | `/api/data-spaces/{id}/suggestions` | 智能建议 |
| POST | `/api/chat/conversations/{id}/messages` | Agent 对话（SSE） |
| POST | `/api/reports/generate` | 报告导出 |

> 说明：`backend/app/routers/graph.py` 存在，但当前未在 `backend/app/main.py` 挂载。

---

## 项目结构

```text
DataMind-Analyst/
├── backend/
│   ├── app/
│   │   ├── agent/
│   │   ├── core/
│   │   ├── middleware/
│   │   ├── models/         # 10 个模型文件，12 个 ORM 模型
│   │   ├── routers/        # 13 个 API 路由模块
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

## 隐私与安全模型

DataMind 面向自托管部署。上传文件、数据画像、对话历史、额度账户和模型配置会存储在你自己的 PostgreSQL、文件目录、Redis 与 Chroma 目录中。

关键数据流说明：

- LLM 提示词可能包含用户问题、相关 schema/画像上下文、检索到的文档片段和工具执行结果。
- 不要使用具备写权限的生产数据库账号接入外部数据源，外部数据源应使用只读账号。
- Python 与数据工具在后端主机执行。允许不可信用户使用前，请检查沙箱、资源限制和部署隔离策略。
- 管理员可以配置全局模型 API Key 和额度策略，请使用强密码并限制管理后台访问范围。

---

## 已知限制

- 暂未提供 Docker Compose。
- 暂未包含正式 `LICENSE` 文件。
- 代码中存在 graph router，但当前未挂载到 FastAPI app。
- 额度计算目前较粗粒度，不等同于真实模型供应商 token 成本。
- 大文件、OCR 密集文档和高并发长对话需要额外调优 worker、数据库连接池和 Redis 连接数。

---

## 安全清单

- 首次上线后立即修改管理员默认密码
- 生产环境必须设置高强度 `SECRET_KEY`
- 严禁提交 `.env` 与敏感凭据
- 数据库和 Redis 使用独立账号并限制网络访问
- 外部数据源保持只读连接
- 上传敏感数据前，请先评估 LLM 提示词与数据流

---

## 故障排查

| 现象 | 处理建议 |
|------|----------|
| 启动时报数据库连接失败 | 检查 PostgreSQL 状态和 `DATABASE_URL` |
| `alembic upgrade head` 失败 | 检查数据库权限，并在 `backend/` 执行 |
| 前端正常但接口 401/CORS | 检查 `.env` 中 `FRONTEND_URL` |
| 模型列表为空或无法对话 | 运行 `python manage.py seed` 并核对 API Key |
| 依赖安装慢 | 使用上文镜像配置 |
| 长对话中断 | 使用生产 Gunicorn 配置并保留 `timeout=300` |

---

## 许可证

当前仓库尚未包含许可证文件。公开开源发布前，请选择并添加 MIT、Apache-2.0 或 AGPL-3.0 等许可证。

---

## 贡献规范

1. 从 `main` 创建分支（如 `feat/*`、`fix/*`、`docs/*`）
2. 推荐使用 Conventional Commits
3. 提交 PR 前运行后端测试
4. 数据库结构变更请同步提交 Alembic 迁移
