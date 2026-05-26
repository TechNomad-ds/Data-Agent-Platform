# Data Agent Platform

智能数据交互平台 - 让普通用户也能轻松理解和分析数据。

上传数据，自动预处理，通过自然语言对话完成数据分析、可视化、报告导出。

## 功能概览

- **数据空间管理**：创建数据空间，上传文件（支持 ZIP 批量上传），自动解压和预处理
- **数据预览面板**：右侧面板直接查看表格数据（分页浏览）、文本内容，支持文件管理
- **智能建议**：基于数据画像自动生成分析建议，降低使用门槛
- **智能对话**：与 Data Agent 自然语言对话，分析数据、生成图表、导出报告
- **数据预处理**：上传后自动生成数据画像（列统计、分布、缺失值、相关性）
- **可视化图表**：Agent 可生成柱状图、折线图、饼图、散点图、热力图
- **记忆系统**：Agent 记住你的偏好和发现，跨对话保持上下文
- **报告导出**：一键导出对话分析为 Markdown 报告
- **文件管理**：在数据面板中直接上传、预览、删除文件

## 技术栈

| 层级 | 技术 |
|------|------|
| 前端 | React 18 + TypeScript + Ant Design 5 + ECharts + Zustand |
| 后端 | FastAPI + SQLAlchemy 2 (async) + Pydantic |
| 数据库 | PostgreSQL 16 |
| 缓存 | Redis 7 |
| 向量库 | ChromaDB |
| LLM | OpenAI 兼容 API（可接入任意模型） |

## 快速开始

### 1. 环境准备

```bash
# 安装 PostgreSQL 和 Redis
# macOS
brew install postgresql@16 redis
brew services start postgresql@16
brew services start redis

# Ubuntu/Debian
sudo apt install postgresql redis-server
sudo systemctl start postgresql redis
```

### 2. 数据库初始化

```bash
createdb data_agent
```

### 3. 后端启动

```bash
cd backend

# 安装依赖
pip install -r requirements.txt

# 配置环境变量
cp ../.env.example ../.env
# 编辑 .env 填入你的 LLM API 配置

# 数据库迁移
alembic upgrade head

# 启动
uvicorn app.main:app --host 0.0.0.0 --port 8002 --reload
```

### 4. 前端启动

```bash
cd frontend
npm install
npm run dev
```

访问 http://localhost:5173

## 环境变量

在项目根目录创建 `.env`：

```env
# 数据库
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/data_agent
DATABASE_URL_SYNC=postgresql://postgres:postgres@localhost:5432/data_agent

# Redis
REDIS_URL=redis://localhost:6379/0

# LLM API（OpenAI 兼容格式）
LLM_API_BASE_URL=https://your-api-endpoint/v1
LLM_API_KEY=sk-your-key
LLM_DEFAULT_MODEL=your-model-name

# JWT
SECRET_KEY=change-this-in-production

# 存储
STORAGE_ROOT=./storage
CHROMA_PERSIST_DIR=./chroma_data
```

## 项目结构

```
Data-Agent-Platform/
├── backend/
│   ├── app/
│   │   ├── agent/          # Agent 循环和工具（8个）
│   │   ├── core/           # 数据库、Redis
│   │   ├── middleware/     # 限流
│   │   ├── models/         # ORM 模型（10个表）
│   │   ├── routers/        # API 路由
│   │   ├── schemas/        # 请求/响应模型
│   │   └── services/       # 业务逻辑
│   │       ├── preprocessing.py  # 数据预处理
│   │       ├── chunking.py       # 文本分段
│   │       ├── embedding.py      # 向量嵌入
│   │       ├── memory.py         # 记忆系统
│   │       ├── sqlite_engine.py  # SQL 查询引擎
│   │       └── report_generator.py
│   ├── alembic/            # 数据库迁移
│   └── storage/            # 用户文件存储
├── frontend/
│   └── src/
│       ├── components/     # Sidebar, Chat, Charts
│       ├── pages/          # Login, Register, Chat
│       ├── api/            # API 客户端
│       ├── stores/         # Zustand 状态
│       └── theme/          # 主题配置
└── README.md
```

## Agent 工具

| 工具 | 功能 |
|------|------|
| `search_data_space` | 语义搜索 + 关键词回退 |
| `read_file` | 读取文件内容 |
| `inspect_data` | 数据结构分析 + 自动 Join 检测 |
| `pandas_query` | Pandas 表达式（AST 安全验证） |
| `sqlite_query` | SQL 查询（多表关联） |
| `execute_python` | Python 代码执行（沙箱） |
| `generate_chart` | 生成 ECharts 图表 |
| `save_memory` | 保存重要发现到记忆 |

## 支持的数据格式

| 类别 | 格式 |
|------|------|
| 表格数据 | CSV, TSV, Excel (.xlsx/.xls), JSON, JSONL, Parquet, Feather |
| 数据库 | SQLite (.sqlite/.db), MySQL (远程连接), PostgreSQL (远程连接) |
| 文档 | PDF, DOCX, TXT, Markdown |
| 代码 | Python, SQL, R, HTML, XML, YAML |
| 统计软件 | Stata (.dta), SPSS (.sav), SAS (.sas7bdat) |
| 图片 | PNG, JPG, GIF, BMP, WebP |
| 压缩包 | ZIP（自动解压） |

特性：
- 自动编码检测（UTF-8, GBK, Latin-1, Shift-JIS 等）
- SQLite 数据库上传后自动解析表结构
- 外部数据库连接（MySQL/PostgreSQL）支持只读查询
- 数据质量报告：重复行检测、异常值检测（IQR）、类型推断建议

## 多租户隔离

- **数据库**：所有查询带 user_id 过滤
- **文件存储**：每用户独立目录 `storage/{user_id}/`
- **向量索引**：每数据空间独立 ChromaDB collection
- **记忆**：按 user_id + scope 隔离
- **Agent**：每次对话只加载当前用户当前数据空间的文件
- **SQLite**：每数据空间独立内存数据库

## 并发性能

- PostgreSQL 连接池：pool_size=20, max_overflow=10
- Redis 缓存：数据画像、列表缓存
- 限流：60 req/min/user（聊天 20 req/min）
- 异步预处理：不阻塞上传
- SSE 流式：实时推送 Agent 回复

## API 文档

启动后端后访问 http://localhost:8002/docs

核心接口：
- `POST /api/auth/login` - 登录
- `POST /api/data-spaces/{id}/upload` - 上传文件（支持 ZIP）
- `GET /api/data-spaces/{id}/profile` - 数据画像
- `POST /api/chat/conversations/{id}/messages` - 对话（SSE）
- `POST /api/reports/generate` - 导出报告
