# Channel 对话渠道接入 — 复刻 同类产品 设计

> 目标：让用户在飞书/钉钉/微信里直接和 DataMind 的 agent 对话。
> **定位：复刻 同类开源客户端 的 channel 功能**——前端配置页 + 用户自带凭据(BYO) + 出站长连接接入，**整体照搬**，只把"回答的 agent"换成 DataMind 的 `AgentLoop`、身份/存储接到 DataMind 现有体系。
> 本文为经 grilling 收敛后的复刻规格。同类产品 源码：前端 `同类开源客户端`，引擎 `其 Rust 引擎`(Rust，仅作参考，不运行时复用，见 §8)。

## 1. 已锁定决策（grilling 收敛）

| # | 决策 |
|---|---|
| 方向 | 外部渠道**反向够到** DataMind 的 agent（不是 DataMind 去连外部） |
| 实现路径 | DataMind 内**同进程**，channel 层直接调 `AgentLoop.run()`（不经 同类引擎） |
| 复用方式 | **复刻** 同类产品 channel(UI+BYO+出站连接)；同类引擎 当协议参考，不运行 |
| 产品 | C 端个人；身份跨组织 |
| P0 渠道 | 飞书 + 钉钉 + 微信（微信走官方 iLink，见 §2/§7） |
| 凭据模型 | **BYO**：用户自带各平台自建应用凭据（绕开 ISV / 企业主体） |
| 身份 | 配对绑定到**已有 DataMind 账号**（不自动开户） |
| 配对流程 | IM 发起出码 → 网页端登录态输码 → 绑到本人账号 |
| 数据空间 | 配对/配置时定默认空间 + `/space` 命令切换 |
| 会话 | 一个 IM 私聊 = 一个滚动 conversation + `/new` 重置 |
| 范围 | **仅私聊**（群聊永不做，身份归属唯一） |
| 回复 | 只发终态（agent 跑完发一条；不做细粒度流式） |
| 计费/限流/错误 | 复用现有：按绑定用户 credits 扣、复用 Redis 限流、转发 AgentLoop 错误文案 |

## 2. 三渠道 BYO 接入 runbook（全部出站连接，免公网回调）

### 飞书 Lark — 出站 WSS（protobuf）
- 凭据：`app_id` + `app_secret`（可选 `encrypt_key`/`verification_token`，WS 模式不用）。
- 连接：`POST /auth/v3/tenant_access_token/internal` 拿 token（2h，提前 5min 刷）→ `POST /callback/ws/endpoint`(body `{AppID,AppSecret}`) 拿 wss URL → 连 WSS(**ALPN 强制 http/1.1**)→ protobuf 帧(分片按 `message_id`+`seq`/`sum` 重组)→ ping/pong + 收 event 回 ACK。
- 用户在开放平台：建**自建应用** + 权限 `im:message`/`im:message:send_as_bot`/`bot:info` + 开机器人 + 订阅 `im.message.receive_v1`；**不填回调 URL**。
- 入站：`event.sender.sender_id.open_id`(用户) / `event.message.chat_id` / `message_type=text` 时 `content.text`。`event_id` TTL 去重。
- 回复：`POST /im/v1/messages?receive_id_type=chat_id`(msg_type=interactive，card json)→ 拿 message_id；改：`PATCH /im/v1/messages/{id}`。
- 测连：`GET /bot/v3/info`。

### 钉钉 DingTalk — 出站 WS Stream（JSON 帧）
- 凭据：`client_id` + `client_secret`。
- 连接：`POST /v1.0/oauth2/accessToken` → `POST /v1.0/gateway/connections/open`(订阅 `/v1.0/im/bot/messages/get` 等) 拿 endpoint+ticket → 连 WS → SYSTEM/ping 回 ACK、CALLBACK 处理消息回 ACK(`{code:200,...}`)。
- 用户在开放平台：建**企业内部应用** + 开机器人 + 权限 `qyapi_robot_sendmsg`(+群/AI Card 权限按需)；**不填回调 URL**。
- 入站：`data` 二次 parse → `senderStaffId`(用户) / `conversationType`(1 单聊/2 群) / `text.content`。chat_id 编码 `user:{staffId}` 或 `group:{convId}`。
- 回复：无按钮→AI Card 三段(`/card/instances` 建 → `/deliver` 投 → `/card/streaming` 写)；有按钮→`/robot/oToMessages/batchSend`。
- 测连：`POST /v1.0/im/robot/info`。

### 微信 Weixin — 官方 iLink 协议，HTTP 长轮询
- **`ilinkai.weixin.qq.com` 是腾讯官方协议**（2026-03 随官方「微信 ClawBot 插件」`@tencent-weixin/openclaw-weixin` 推出，有官方使用条款，专为合法把个人微信接给 AI Agent、终结旧的逆向封号灰区）。QR 登录个人微信、**无需企业主体、无封号风险**。
- 注意：iLink 是"官方 relay、但非开放第三方平台"（无公开文档/控制台/自助注册）。我们直连其协议的姿态同 同类产品/Qwen Code（社区逆向协议 + SDK），走官方通道但非官方第三方接入计划。`context_token` 24h 窗口。
- 凭据：扫码登录获得 `bot_token` + `account_id`（`get_bot_qrcode` → 2s 轮询 `get_qrcode_status` 到 confirmed）。
- 连接：长轮询 `POST /ilink/bot/getupdates`(游标 `get_updates_buf`，timeout 40s)。
- 入站：`from_user_id`(用户) / `context_token`(回复必带，需持久化) / `item_list`(type1 文本/type3 语音转文字)。
- 回复：`POST /ilink/bot/sendmessage`(带 `context_token`)。**不支持改消息**（发新代替）。

## 3. 前端复刻（React + AntD）

照搬 同类产品 「渠道配置」页：
- 渠道列表：每行 = Collapse(Logo 14px + 名称 + `Coming Soon` Tag? + 启用 Switch)，默认折叠。
- 展开表单：飞书(App ID + App Secret + "显示可选配置"折叠[Encrypt Key/Verification Token] + **测试并连接**)、钉钉(Client ID + Client Secret + 测试并连接)、微信(扫码登录状态机 idle→loading_qr→showing_qr→scanned→connected，走 SSE)。
- 公共：**默认数据空间**下拉 + **模型**选择器（替换 同类产品 的"对话Agent/对话模型"）；启用开关(启用前校验已配凭据)。
- **待配对请求**区：列表(用户名/配对码/过期倒计时 + 批准/拒绝)，WebSocket 实时 prepend。
- **已授权用户**区：列表(平台/授权时间 + 撤销)；有授权用户时凭据字段锁定。
- IPC/HTTP 接口对照：`getPluginStatus`/`enablePlugin`/`disablePlugin`/`testPlugin`/`getPendingPairings`/`approvePairing`/`rejectPairing`/`getAuthorizedUsers`/`revokeUser`/`getPlatformSettings`/`setAssistantSetting`/`setDefaultModelSetting` + WS 事件 `pairing-requested`/`plugin-status-changed`/`user-authorized`。

## 4. 4 处必须适配（DataMind ≠ 同类产品）

1. **agent**：同类产品 `ACP` → DataMind `AgentLoop.run()`（buffer 事件流，done 时发终态）。
2. **身份**：同类产品 单 owner → 谁登录态配的凭据，bot 绑到谁的账号；消息按 `external_identities` 路由、扣其 credits。
3. **存储**：同类产品 自带 SQLite → DataMind PG（见 §5）。
4. **连接**：出站长连接接 DataMind 的**连接管理进程**（见 §7 风险）。

## 5. 数据模型（alembic）

已落 `external_identities`(channel/platform_user_id→user_id+授权时间) + `conversations.channel`/`channel_thread_id`。
待加：渠道凭据表(per-user per-channel，凭据用 `encrypt_api_key` 加密)、配对码(可用 Redis 带 TTL)、每渠道默认空间/模型设置。

## 6. 后端模块（backend/app/channels/，已搭脚手架）

`contracts.py`(Inbound/OutboundMessage + ChannelAdapter Protocol) · `bridge.py`(AgentBridge：buffer AgentLoop.run → 回写) · `registry.py` · `pairing.py`(出码/校验) · `adapters/{feishu,dingtalk,weixin}.py`(各平台出站连接+收发) · `routers/channels.py`(配置/配对/授权 HTTP API)。连接管理见 §7。

## 7. 风险与待决

- **连接管理/扩展(最大工程代价)**：共享后端下每个已配置 app = 一条常驻出站连接(WS/轮询)。用户多 = N 条常驻连接，需**独立连接管理进程**(不能在 4 个 gunicorn worker 里各起，否则重复连/重复处理)。这是 BYO+长连接复刻 同类产品 的固有代价。
- **微信 iLink 平台姿态**：iLink 是官方协议但非开放第三方平台（无公开文档/控制台），我们直连其协议（社区逆向）同 同类产品/Qwen Code；功能可用、无封号风险，但腾讯未来若收紧或推出正式第三方接入，需跟进。非 P0 阻塞。
- **BYO 设置门槛**：用户需有能建自建应用的飞书/钉钉组织（个人版能否建应用待用户确认）；适合技术型用户。

## 8. 不运行时复用 同类引擎（保留结论）

同类引擎 是 Rust/Axum，channel 与其单账号/单组织/自带 SQLite/自带 JWT 内核焊死，C 端多租户对不上(实证见 git 历史)；其 agent 也非 DataMind 的 AgentLoop。故**不运行 同类引擎**，只读其源码当协议参考(本文 §2 即据此提炼)。
