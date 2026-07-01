# 渠道接入 — 部署与运维指南

面向「拿到这个 PR 要把飞书/微信渠道跑起来」的人。设计细节见 `channel-integration-design.md`，本文只讲**怎么部署、怎么更新库、怎么操作、代码怎么合的**。

## 0. 这个 PR 加了什么（代码怎么合的）

给 DataMind 加「IM 渠道接入」：用户在飞书/微信里直接和 DataMind 的 agent 对话。新增/改动：

| 位置 | 作用 |
|---|---|
| `backend/app/channels/` | 核心。`contracts`(统一消息契约)、`adapters/{feishu,weixin,mock}`、`manager`(连接管理+入站调度)、`bridge`(AgentLoop↔渠道回写)、`pairing`(配对)、`store`(凭据加密存取)、`registry` |
| `backend/app/routers/channels.py` | REST API，挂在 `/api/channels`（`main.py` 已 include） |
| `backend/app/services/{channel_ingest,feishu_doc}.py` | 附件 / 飞书云文档入库 |
| `backend/app/models/{channel_config,external_identity}.py`、`conversation.py` | 新表 + 会话加 `channel`/`channel_thread_id` 列 |
| `frontend/src/pages/Channels/` + `NavRail` | 前端「远程连接」页 + 侧栏入口 |

**关键架构点**：channel manager 是**独立进程**，不能塞进 gunicorn worker——每个已启用渠道 = 一条常驻出站连接（飞书 WSS / 微信 iLink 长轮询），多 worker 并发会导致同一条消息被重复处理、credits 重复扣。manager 收到消息 → `Dispatcher` → `AgentLoop` → 回写渠道。

## 1. 数据库更新

用 Alembic。部署/更新时跑一次：

```bash
cd backend
alembic upgrade head        # 建表 / 加列，幂等
alembic current             # 应等于 alembic heads（单头）
```

本 PR 新增的迁移（已在链上，单头）：

- `c1d2e3f4a5b6_add_channels` — `external_identities` 表（IM 用户→内部 user 绑定）+ `conversations.channel` / `channel_thread_id`
- `d1e2f3a4b5c6_add_channel_configs` — `channel_configs` 表（每用户每渠道一行：加密凭据 + 启用/连接状态 + 默认空间/模型）
- `f1a2b3c4d5e6_merge_...` — 空合并节点，把渠道线和上游 `conversation_data_space_ids` 线归一（无 schema 变更）

回滚：`alembic downgrade <rev>`。

## 2. 环境变量（部署前必设）

| 变量 | 说明 |
|---|---|
| `DATABASE_URL` | 如 `postgresql+asyncpg://user:pass@host:5432/datamind`（alembic 用其同步版 `database_url_sync`） |
| `REDIS_URL` | **必须**。配对码要跨进程共享（manager 出码、web 审批走同一 Redis） |
| `SECRET_KEY` | ⚠️**最关键**，见下 |

**关于 `SECRET_KEY`（务必看）**：渠道凭据用 Fernet 加密落库，密钥由 `SECRET_KEY` 派生（`app/core/security.py`，sha256）。因此：

1. 必须设成稳定的随机值：`python -c "import secrets; print(secrets.token_urlsafe(32))"`
2. **后端 API 进程和 manager 进程必须共用同一个 `SECRET_KEY`**，否则 manager 解不开凭据、连接全失败
3. **`SECRET_KEY` 一旦更换，已存的所有渠道凭据（及 API key）都会失效**，需在网页端重填

LLM 相关（`anthropic_api_key` / `openai_api_key` 等）沿用 DataMind 原有配置。

## 3. 启动（比原来多一个进程）

```bash
cd backend
alembic upgrade head                                   # 1) 迁移
uvicorn app.main:app --host 0.0.0.0 --port 8077        # 2) 后端 API（原有）
python webserve.py                                     # 3) 前端：先 (cd ../frontend && npm ci && npm run build) 出 dist
python -m app.channels.manager                         # 4) 渠道连接管理进程（本 PR 新增，单实例！）
```

manager 必须**单实例**且长驻。生产用 systemd/supervisor 守护（当前是裸进程，崩溃不自恢复）：

```ini
# /etc/systemd/system/datamind-channel-manager.service
[Service]
WorkingDirectory=/opt/DataMind/backend
EnvironmentFile=/opt/DataMind/.env
ExecStart=/opt/DataMind/backend/.venv/bin/python -m app.channels.manager
Restart=always
RestartSec=3
[Install]
WantedBy=multi-user.target
```

## 4. 各种操作（运维 / 使用）

**配置一个渠道（网页端）**：登录 → 左侧「远程连接」→
- 飞书：填 App ID + App Secret（可选 Encrypt Key / Verification Token）→「测试并连接」
- 微信：扫码登录
- 选**默认数据空间** + **模型** → 打开**启用**开关（触发 manager `start_one` 起连接，connected 变绿）

**用户绑定（配对）**：IM 用户给 bot 发任意消息 → bot 回**配对码** → 网页端「待配对」区输码/批准 → 写 `external_identities`。之后该 IM 用户的消息按绑定路由到其账号、扣其 credits。

**发文件 / 文档**：把文件发给 bot → 自动下载入库到该渠道默认数据空间（飞书已实现；微信附件待补）。发飞书云文档/表格/wiki 链接（任意渠道均可）→ 用该用户配置的飞书应用凭据抓取入库。入库后台解析，`DataProfile.status=ready` 即可提问（注：`File.parse_status` 是死字段，看 `DataProfile.status`）。

**启停 / 排错**：网页开关 = REST → manager `start_one`/`stop_one`（停用会把 `connected` 置回 false）。排错看 manager 日志（飞书 WSS / 微信轮询 / dispatch 异常）。重启 manager 后 `start_all` 会自动重连所有已启用渠道。

## 5. 外部平台前置配置

- **飞书自建应用**：开启**长连接模式** + 订阅 `im.message.receive_v1` 事件；云文档接入需 docx/sheets/wiki **读权限**且把文档**授权给应用**；改动后要**发布版本**
- **微信**：iLink 官方协议，扫码登录即可

## 6. 已知限制

- 微信文件/图片附件：下载框架已就位，待补 iLink 媒体消息格式（飞书附件已实现）
- manager 无进程守护 → 建议 systemd/supervisor
- 钉钉本期不支持（已从代码移除）

## 7. 测试（本仓无 CI，测试套件是唯一门）

```bash
cd backend
python -m pytest tests/test_channel*.py tests/test_feishu_adapter.py -q --noconftest
# 渠道相关约 157 条，均应通过
```
