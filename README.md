<p align="center">
  <img src="image.png" alt="Data Agent Platform" width="120" />
</p>

<h1 align="center">Data Agent Platform</h1>

<p align="center">
  <b>面向业务的智能数据交互平台</b><br/>
  上传数据 · 对话分析 · 可视化 · 一键报告
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.11-3776ab" alt="Python" />
  <img src="https://img.shields.io/badge/FastAPI-0.115-009688" alt="FastAPI" />
  <img src="https://img.shields.io/badge/React-18-61dafb" alt="React" />
  <img src="https://img.shields.io/badge/PostgreSQL-16-336791" alt="PostgreSQL" />
  <img src="https://img.shields.io/badge/Redis-7-dc382d" alt="Redis" />
  <img src="https://img.shields.io/badge/ChromaDB-vector-7a5af8" alt="ChromaDB" />
  <img src="https://img.shields.io/badge/LLM-Anthropic_%7C_OpenAI-orange" alt="LLM" />
</p>

---

## 为什么需要 Data Agent Platform

传统数据分析有两道门槛：**会用 SQL/Python** 和 **看得懂业务**。Data Agent Platform 把这两道门槛同时拆掉——

- **不会写 SQL 的业务人员**：上传 Excel/CSV，直接用中文提问"哪些客户复购率最高？画个折线图看每月销售趋势"，Agent 自动完成分析、出图、给结论。
- **数据团队**：把临时取数、报告制作、可视化等重复劳动交给 Agent，团队聚焦在数据建模和深度洞察上。
- **管理层**：跨多个数据空间隔离，每个项目/部门一个空间，权限、配额、记忆各自独立，对话即报告。

> Data Agent 不是一个被动的 SQL 工具，而是一个会主动 **理解数据 → 制定方案 → 执行代码 → 检查结果 → 修正策略** 的 Agent。配合 14 个内置工具（搜索、SQL、Pandas、可视化、知识图谱、记忆等），它能在数十轮交互中持续解决复杂分析问题。

---

## 核心能力

### 数据接入 · 一键上传，自动理解
- 支持 **20+ 种数据格式**：CSV、Excel、Parquet、JSON、SQLite、PDF、Word、Markdown、Stata/SPSS/SAS 等
- 支持 **ZIP 批量上传**，自动解压、识别编码（UTF-8 / GBK / Latin-1 / Shift-JIS）、推断列类型
- 支持 **外部数据库**只读连接（MySQL / PostgreSQL）
- 上传即自动生成**数据画像**：列统计、分布、缺失值、相关性、异常值（IQR）、重复行检测

### 智能对话 · 自然语言驱动分析
- 与 Agent 中文对话，自动选择正确的数据文件、决定用 SQL 还是 Pandas、出什么图
- **多步推理**：Agent 会 inspect → query → 验证 → 出图 → 总结，每一步透明可见
- **SSE 流式输出**：实时看到 Agent 的思考和工具调用过程
- **智能建议**：进入数据空间即给出分析切入点，降低冷启动门槛

### 可视化 · 自动出图
- 一句话生成柱状图、折线图、饼图、散点图、热力图（ECharts 引擎）
- 图表内嵌在对话中，可直接导出到报告

### 知识沉淀 · 记忆 + 知识图谱
- Agent 跨对话**记住偏好和发现**（按用户、按数据空间隔离）
- 文档自动抽取**三元组**构建知识图谱，支持图遍历查询
- 检索引擎：向量 + BM25 + 多查询融合（RRF），命中率显著高于单一向量检索

### 安全 · 多租户隔离
| 维度 | 隔离粒度 |
|------|----------|
| 数据库查询 | 所有 SQL 强制按 `user_id` 过滤 |
| 文件存储 | 每用户独立目录 `storage/{user_id}/` |
| 向量索引 | 每数据空间独立 ChromaDB collection |
| 记忆 | `user_id` + `scope` 双重隔离 |
| SQLite 引擎 | 每数据空间独立内存数据库 |
| Agent 上下文 | 只加载当前用户当前空间的文件 |

### 一键报告
- 对话过程可一键导出为 Markdown 报告，包含数据洞察、图表、结论
- 适合直接给老板/客户看

---

## 截图

> _建议团队补充几张产品截图替换此区块：数据空间列表 / 对话页 / 报告导出页_

---

## 快速开始

### 方式一：macOS 本地一键部署

```bash
# 1. 安装基础环境（首次）
brew install postgresql@16 redis python@3.11 uv
brew services start postgresql@16
brew services start redis
createdb data_agent

# 2. 克隆并配置
git clone <your-repo-url> Data-Agent-Platform
cd Data-Agent-Platform
cp .env.example .env
# 编辑 .env：填入 ANTHROPIC_API_KEY 或 OPENAI_API_KEY

# 3. 后端
cd backend
uv venv venv --python $(which python3.11)
uv pip install --python venv/bin/python -r requirements.txt
venv/bin/alembic upgrade head
venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8002 --reload

# 4. 前端（新开终端）
cd frontend
npm install
npm run dev
```

打开 **http://localhost:5200** 注册账号即可使用。后端 API 文档：**http://localhost:8002/docs**

### 方式二：Linux

```bash
sudo apt install -y postgresql redis-server python3.11 python3.11-venv
sudo systemctl start postgresql redis
sudo -u postgres createdb data_agent
# 其余步骤同 macOS
```

### 国内网络环境

如果 `pip install` 慢，配置清华源：

```bash
export UV_INDEX_URL="https://pypi.tuna.tsinghua.edu.cn/simple"
npm config set registry https://registry.npmmirror.com
```

---

## 配置说明

在项目根目录复制 `.env.example` 为 `.env`。最低需要填的两个：

```bash
LLM_BACKEND=anthropic            # 或 openai
ANTHROPIC_API_KEY=sk-ant-xxx     # 走 Claude
# 或
OPENAI_API_BASE=https://api.deepseek.com/v1
OPENAI_API_KEY=sk-xxx
OPENAI_MODEL=deepseek-chat
```

完整配置项见 [.env.example](.env.example)，包含数据库、Redis、JWT、检索、知识图谱、配额、端口等。

---

## 架构

```
┌──────────────────────────────────────────────────────────────┐
│                          浏览器                                │
│            React 18 + Antd 5 + ECharts + Zustand              │
└──────────────────────────────────┬───────────────────────────┘
                                   │ HTTPS (SSE)
┌──────────────────────────────────▼───────────────────────────┐
│                     FastAPI Backend                           │
│  ┌───────────┐  ┌──────────────┐  ┌───────────────────────┐ │
│  │  Auth /   │  │  Data Space  │  │     Chat (SSE)        │ │
│  │  Credits  │  │  Files       │  │     Agent Loop        │ │
│  └───────────┘  └──────────────┘  └──────────┬────────────┘ │
│                                              │              │
│  ┌─────────────────────────────────────────▼─────────────┐ │
│  │  Agent 工具集 (14 个)                                    │ │
│  │  search · read_file · inspect · pandas · sqlite        │ │
│  │  python · chart · memory · graph · nl2sql · ...        │ │
│  └────────────────────────────────────────────────────────┘ │
└─────┬──────────────┬──────────────────┬──────────────┬──────┘
      │              │                  │              │
┌─────▼─────┐  ┌─────▼────┐  ┌──────────▼───┐  ┌──────▼────────┐
│ PostgreSQL│  │  Redis   │  │   ChromaDB   │  │ Anthropic /   │
│  (元数据) │  │  (缓存)  │  │  (向量索引)   │  │ OpenAI API    │
└───────────┘  └──────────┘  └──────────────┘  └───────────────┘
```

---

## 技术栈

| 层级 | 选型 | 说明 |
|------|------|------|
| 前端 | React 18 + TypeScript 5 + Vite 5 + Ant Design 5 + ECharts 5 + Zustand | 现代化前端，热重载 |
| 后端 | FastAPI 0.115 + SQLAlchemy 2 (async) + Pydantic 2 | 全异步，类型安全 |
| 数据库 | PostgreSQL 16 | 元数据、用户、对话历史 |
| 缓存 | Redis 7 | 数据画像、列表、限流 |
| 向量库 | ChromaDB 0.5 | 文档语义检索 |
| 检索 | BM25 + Vector + RRF 融合 | 召回率显著优于单向量 |
| 嵌入 | sentence-transformers | 本地推理，无外部依赖 |
| LLM | Anthropic Claude / OpenAI 兼容 | 可对接 DeepSeek、Qwen、通义、任意中转 |
| 文档解析 | PyMuPDF + python-docx + openpyxl | PDF/Word/Excel 原生解析 |
| 异步队列 | Celery (可选) | 长任务异步处理 |

---

## Agent 工具

后端为 Agent 暴露了 **14 个工具**，覆盖搜索、查询、计算、可视化、记忆、图谱五大类：

| 类别 | 工具 | 说明 |
|------|------|------|
| 检索 | `search_data_space` | 向量 + BM25 混合检索 |
| 检索 | `read_file` | 按文件名读取原始内容 |
| 数据 | `inspect_data` | 列类型、缺失值、自动 Join 检测 |
| 数据 | `pandas_query` | Pandas 表达式（AST 白名单校验） |
| 数据 | `sqlite_query` | 多表 JOIN 的 SQL 查询 |
| 数据 | `nl2sql` | 自然语言转 SQL |
| 数据 | `db_import_csv` | CSV → SQLite 自动导入 |
| 数据 | `kb_reindex_file` | 单文件重建索引 |
| 执行 | `execute_python` | 受限 Python 沙箱 |
| 可视化 | `generate_chart` | ECharts JSON 配置生成 |
| 记忆 | `save_memory` | 跨对话记忆持久化 |
| 图谱 | `graph_search` | 知识图谱节点/边检索 |
| 图谱 | `graph_traverse` | 多跳关系遍历 |
| 图谱 | `graph_extract_from_text` | 文档三元组抽取 |

---

## 支持的数据格式

| 类别 | 格式 |
|------|------|
| 表格数据 | CSV, TSV, Excel (.xlsx/.xls), JSON, JSONL, Parquet, Feather |
| 数据库 | SQLite (.sqlite/.db), MySQL 远程, PostgreSQL 远程 |
| 文档 | PDF, DOCX, TXT, Markdown |
| 代码 | Python, SQL, R, HTML, XML, YAML |
| 统计软件 | Stata (.dta), SPSS (.sav), SAS (.sas7bdat) |
| 图片 | PNG, JPG, GIF, BMP, WebP |
| 压缩包 | ZIP（自动解压） |

---

## 性能与运维

- **PostgreSQL 连接池**：pool_size=20，max_overflow=10
- **Redis 缓存**：数据画像、空间列表、用户配额
- **限流**：60 req/min/user，聊天 20 req/min
- **上传**：异步预处理，不阻塞接口
- **对话**：SSE 流式推送，长任务可中断
- **配额**：每日免费额度可配，单次 Agent 运行有上限保护

---

## API 文档

启动后端后访问 **http://localhost:8002/docs**（Swagger UI）。

常用接口：

| 方法 | 路径 | 用途 |
|------|------|------|
| POST | `/api/auth/login` | 登录 |
| POST | `/api/auth/register` | 注册 |
| POST | `/api/data-spaces/{id}/upload` | 上传文件（支持 ZIP） |
| GET | `/api/data-spaces/{id}/profile` | 获取数据画像 |
| GET | `/api/data-spaces/{id}/suggestions` | 智能分析建议 |
| POST | `/api/chat/conversations/{id}/messages` | Agent 对话（SSE） |
| POST | `/api/reports/generate` | 导出对话报告 |
| GET | `/api/graph/{space_id}` | 知识图谱查询 |

---

## 项目结构

```
Data-Agent-Platform/
├── backend/
│   ├── app/
│   │   ├── agent/          # Agent 主循环 + 14 个工具实现
│   │   ├── core/           # 数据库、Redis、依赖注入
│   │   ├── middleware/     # 限流、鉴权
│   │   ├── models/         # SQLAlchemy ORM（10+ 表）
│   │   ├── routers/        # 15 个 API 路由模块
│   │   ├── schemas/        # Pydantic 请求/响应
│   │   ├── services/       # 业务逻辑层
│   │   │   ├── preprocessing.py   # 数据画像
│   │   │   ├── chunking.py        # 文档分段
│   │   │   ├── embedding.py       # 向量嵌入
│   │   │   ├── retrieval.py       # 混合检索（向量+BM25+RRF）
│   │   │   ├── memory.py          # 记忆系统
│   │   │   ├── graph.py           # 知识图谱
│   │   │   ├── nl2sql.py          # NL → SQL
│   │   │   ├── sqlite_engine.py   # 内存 SQL 引擎
│   │   │   └── report_generator.py
│   │   ├── indexing/       # 索引构建
│   │   ├── config.py       # 配置（pydantic-settings）
│   │   └── main.py         # FastAPI 入口
│   ├── alembic/            # 数据库迁移
│   └── requirements.txt
├── frontend/
│   └── src/
│       ├── pages/          # Login, Register, Chat, DataSpaces, Files, Settings, Admin ...
│       ├── components/     # Chat, DataPanel, Charts, Sidebar, Graph, Onboarding ...
│       ├── api/            # axios 客户端按模块拆分
│       ├── stores/         # Zustand 状态管理
│       └── theme/          # Antd 主题
└── .env.example
```

---

## 路线图

- [ ] 团队空间（多人协作，角色权限）
- [ ] 定时报告（周报/月报自动生成 + 推送）
- [ ] 更多可视化（地理热力、桑基图、组织树）
- [ ] 数据血缘可视化
- [ ] 插件市场（自定义 Agent 工具）

---

## 许可

内部项目。如需开源或商业授权，请联系项目维护者。
