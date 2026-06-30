# Channel 对话渠道接入层 — 设计文档

> 目标：让用户**不打开网页**，直接在飞书 / 邮箱里跟 DataMind 的 AI agent 对话，
> 把"邮箱、飞书、AI 工具"收敛成 DataMind 这一个使用入口。
> 设计参考 同类开源客户端 的 channel 机制（借架构，不搬代码）。

## 0. 与已有 #5/#6 的关系

| | 已有 `docs/feishu-email-integration.md`（#5/#6） | 本项目（channel 对话层） |
|---|---|---|
| 解决什么 | 飞书扫码**登录** + 把飞书云文件/邮件附件**导入**数据空间 | 在飞书/邮箱里**直接和 agent 对话**（多一种使用方式） |
| 数据方向 | 外部数据 → 平台 | 双向消息流：用户 ↔ agent |
| 复用 | `file_intake.register_file_to_space` | `agent/loop.py::AgentLoop.run` |

两者**共用同一个飞书自建应用**（同一套 App ID/Secret），互补：扫码登录拿到身份 → 配对绑定 → 之后飞书消息直达 agent。本项目不替代 #5/#6，是在其之上加"对话通道"。

## 1. 可行性结论

**可行，借架构/知识，不做运行时复用。** 同类产品 是 Electron 前端，引擎在独立开源仓 `其 Rust 引擎`（Apache-2.0，Rust/Axum，channel 在 `其源码`，17.8K 行）。经源码实证评估（见 §10），**否决"运行时复用 同类引擎 channel"**，采用"读源码当参考 + Python 在 DataMind 内重写薄 channel 层"。同类产品 channel 的 4 个核心抽象能干净映射到 FastAPI：

1. **统一消息契约**（`IUnifiedIncoming/OutgoingMessage`）→ Pydantic `InboundMessage` / `OutboundMessage`，让 agent 层完全不感知平台差异。
2. **可插拔渠道适配器**（`BasePlugin: start/stop/sendMessage/editMessage/onMessage`）→ Python `Protocol`/ABC `ChannelAdapter`。
3. **配对绑定安全模型**（PairingService：IM 发码 → 主程序本地批准）→ `external_identities` 表 + 配对码流程。
4. **流式回写二态**（`sendMessage` 发新消息 / `editMessage` 更新消息）→ 飞书消息卡片"先发后更新"模拟流式。

## 2. 核心矛盾：SSE vs Webhook

现有对话是**浏览器长连接 SSE**（`POST /api/chat/.../messages` → `text/event-stream`）。
外部渠道是**异步 webhook**：平台推一条事件进来，要求**立即 200 应答**，回复随后异步发回。
二者协议不兼容 → channel 层的关键职责就是**桥接**：

```
飞书/邮件 → webhook → 立即 200
              └→ 后台任务：buffer AgentLoop.run() 的 yield → 组装 → 调平台 API 发回
```

复用点：`AgentLoop.run()` 本身就是 async generator，channel 层只是**不把 yield 喂给 SSE，而是聚合后回写渠道**。agent / tools / services 全部零改动。

## 3. 架构映射（同类产品 → DataMind）

```
飞书/邮箱/…                         IM 平台
   ↓ webhook / IMAP poll
ChannelAdapter (feishu.py / email.py)   ← 平台适配，实现统一契约
   ↓ parse_inbound() → InboundMessage
ChannelRouter / Dispatcher              ← 鉴权(配对)、找/建会话、路由
   ↓
AgentBridge.run_and_reply()             ← buffer AgentLoop.run(), 节流回写
   ↓ 复用 agent/loop.py::AgentLoop.run （零改动）
AgentBridge ← OutboundMessage → ChannelAdapter.send/edit_message → 平台 API
```

对照 同类产品：`ChannelAdapter`≈Plugin，`ChannelRouter`≈ActionExecutor，`AgentBridge`≈ChannelMessageService，配对≈PairingService。

## 4. 关键设计决策

- **鉴权**：webhook 端点**不走 JWT**（外部平台不持 token），改为**验证渠道签名**（飞书 `Encrypt`/`token`/AES、邮件 IMAP 账号）。验签通过后，用 `external_identities` 把平台用户映射到内部 user，再以该 user 身份调 agent。
- **配对绑定（防劫持）**：陌生平台用户首次发消息 → bot 回 6 位配对码（10min，存 Redis）→ 用户**在网页端登录后输入配对码批准** → 写 `external_identities` 白名单。授权动作**只在已认证的网页端完成**，绝不通过 IM 通道授权（沿用 同类产品 配对安全原则）。
- **流式回写**：飞书支持更新消息卡片 → 先 `send`（占位/首块）拿 message_id，后续 `update`（节流 ~500ms，与 同类产品 一致），`done` 时落终态。邮件不支持流式 → 仅在 `done` 时一封回信。
- **会话归属**：`conversations` 加 `channel` + `channel_thread_id`，把外部会话线程映射到内部 conversation，实现"同一飞书会话连续多轮"。
- **复用而非分叉**：不复制 `chat.py` 的会话创建/保存逻辑——抽出共享函数（`create_conversation` / 消息落库），webhook 和 SSE 两条路都调它。

## 5. 数据模型变更（alembic 迁移）

```sql
-- 新表：外部身份映射
CREATE TABLE external_identities (
  id UUID PRIMARY KEY,
  user_id UUID REFERENCES users(id) ON DELETE CASCADE,
  channel TEXT NOT NULL,            -- 'feishu' | 'email'
  platform_user_id TEXT NOT NULL,   -- 飞书 open_id / 邮箱地址
  authorized_at TIMESTAMPTZ,
  UNIQUE (channel, platform_user_id)
);

-- conversations 增列
ALTER TABLE conversations ADD COLUMN channel TEXT DEFAULT 'web';
ALTER TABLE conversations ADD COLUMN channel_thread_id TEXT;  -- 外部线程去重
```

## 6. 新增模块清单（backend/app/）

```
channels/
  __init__.py
  contracts.py        # InboundMessage / OutboundMessage (Pydantic) + ChannelAdapter (Protocol)
  registry.py         # 渠道注册表：按 config 启用哪些 adapter
  router.py           # ChannelRouter：验签 → 鉴权/配对 → 找会话 → 派发
  bridge.py           # AgentBridge：buffer AgentLoop.run() + 节流回写
  pairing.py          # 配对码签发/校验（Redis）
  adapters/
    feishu.py         # 飞书：验签解密 / parse / send_message / update_message
    email.py          # 邮件：IMAP 轮询入站 + SMTP 回信（无流式）
routers/
  channels.py         # FastAPI 路由：POST /api/channels/feishu/webhook 等 + 管理端点
```

`main.py` 注册 `channels` 路由；`config.py` 复用已有 `feishu_*` / `email_imap_*`，补 `feishu_encrypt_key` / `feishu_verification_token` / SMTP 字段。

## 7. 分阶段实施计划

- **P0 地基**：alembic 迁移（`external_identities` + conversations 增列）；config 补字段；抽出共享的会话创建/落库函数。*（无外部依赖，可立即做）*
- **P1 channel 核心**：`contracts.py` + `registry.py` + `router.py` + `bridge.py` + `pairing.py`。用一个 **mock/echo adapter** + pytest 跑通"入站→AgentBridge→出站"全链路（不依赖真实凭据）。
- **P2 飞书 adapter**：webhook 验签解密、事件解析、配对流程、消息卡片 send/update 流式回写。**需要飞书 App 凭据**。
- **P3 邮件 adapter**：IMAP 轮询（后台 asyncio task / APScheduler）入站、SMTP 回信。**需要邮箱授权码**。
- **P4 管理 UI**：网页端"渠道管理"页（启用/配置渠道、审批配对请求、查看授权用户），对标 同类产品 设置页。
- **P5 扩展位（可选）**：抽象成"渠道插件"声明式注册（参考 同类产品 extension manifest），方便后续接钉钉/企微/Telegram。

P0/P1 不需要任何外部凭据即可落地并测试；P2/P3 卡在凭据上（与 #5/#6 同一阻塞点）。

## 8. 风险与开放问题

- **会话身份**：一个飞书用户对应一个内部 user，多轮如何复用 conversation（按 `channel_thread_id`？按用户单例会话？）—— 建议默认"每飞书会话一个 conversation"。
- **数据空间选择**：飞书里对话默认绑哪个数据空间？需在配对/绑定时让用户指定默认数据空间（对应 同类产品 的 assistantBinding）。
- **并发与限额**：channel 入站要复用现有 Redis 并发限流，避免 bot 被刷。
- **飞书消息卡片流式频率**：飞书 API 有更新频率限制，节流参数需实测。
- **凭据归属**：邮件授权码按用户加密存（沿用 `encrypt_api_key`），不要进全局 env（#5 文档已强调）。

## 9. 参考

- 同类产品 channel 设计：`.同类产品/FEATURE_CHANNELS.md`、`packages/desktop/src/common/types/channel/channel.ts`、`examples/ext-wecom-bot/`（最完整的扩展渠道示例，含 webhook + 流式状态机）。
- 本仓库复用点：`agent/loop.py::AgentLoop.run`、`routers/chat.py`（SSE 链路参照）、`services/file_intake.py`、`core/security.py`。

## 10. 同类引擎 运行时复用评估（结论：否决，用反证法）

对 `其 Rust 引擎`（开源 Rust 引擎）做了源码实证，评估"复用 同类引擎 channel + 让 DataMind 的 agent 回答"是否比"Python 重写"更优。结论：**否决运行时复用，Python 重写。**

**前提澄清**：(1) 只需 DataMind 自己的 agent 能连上，不需要 同类引擎 托管 codex 等多 agent；(2) DataMind 的 agent = 自写 ReAct 循环 `AgentLoop`（裸 `anthropic`/`openai` SDK，非 langgraph、非 Claude Agent SDK），本进程内一个 Python 类，`AgentLoop.run()` 本身是 async generator。

**反证法 grid（带 file:line，路径相对 同类引擎 仓）**：

| 方案 / 命题 | 判定 | 实证 |
|---|---|---|
| ① fork：改 `IWorkerTaskManager` 桥到 DataMind | ☠️ | `同类产品-app/src/services.rs:167` 唯一实现写死，factory 只 dispatch Acp/其运行时，无 HTTP 分支 → 必 fork+重编 |
| ② ACP·能否不 fork 注册外部 agent | 可（对②有利） | `同类产品-ai-agent/src/services/custom.rs:56` 运行期写 `agent_type=acp/source=custom/command=任意进程`，即时生效 |
| ② ACP·双栈状态 | ☠️ | 会话/消息沉淀 同类引擎 SQLite（挂 owner 账号），`assistant_users/sessions` 硬依赖，无委托/无 SSO（`同类产品-auth/.../middleware.rs`，JWT 硬编码 `iss=同类产品`） |
| ② ACP·飞书跨组织 | ☠️ | `channel/src/plugins/lark/api.rs:75` 用 `/tenant_access_token/internal`（企业自建应用，单组织），无 app_ticket/tenant_key（ISV 缺失） |
| ② ACP·逆向成本 | ☠️ | ACP 协议无文档，在外部 dep `其运行时 v0.1.37` |
| ② 单账号破多租户 | ☠️ | `channel/src/state.rs:471` 所有 IM 用户塌进一个 owner（兜底 `system_default_user`） |
| ③ 重写是否太大 | 推翻→③活 | 17.8K 行，35-40% 为可移植踩坑知识，6-8 人周；直接复用 DataMind 现有 agent/PG/auth/计费 |

**关键判断**：同类引擎 的 channel 解的是"桌面端无公网回调"难题（飞书走 WS 长连接 + protobuf 帧，最复杂的 ~2.7K 行）——DataMind 有公网地址，应直接用**飞书事件订阅 webhook**，根本不需要那段。它最难的代码在解你没有的问题；你最难的问题（跨组织多租户）它没解。

**值得抄的（知识，非运行时）**：飞书 Interactive Card 结构 + "只能发卡片再编辑"的流式二态（`lark/types.rs`）、钉钉 AI Card 三步流式（`dingtalk/types.rs`）、验签/AES/配对状态机设计（`pairing.rs`）。**飞书接入用 webhook，不抄它的 WS 长连接。**

**跨方案都得自做、谁都不白送**：跨组织飞书（ISV: app_ticket→tenant_key→per-tenant token）、IM 身份→DataMind 多租户用户映射。③ 能原生长进多租户模型，复用则要跟 同类引擎 单组织/单账号假设硬掰。
