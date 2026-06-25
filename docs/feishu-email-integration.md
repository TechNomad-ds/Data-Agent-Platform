# 飞书 / 邮件集成接入说明（#5、#6）

这两项需要**外部凭据**，无法在没有凭据时真正打通。下面是已就绪的骨架与接入步骤，
拿到凭据后按此启用即可。配置位已在 `backend/app/config.py` 与 `.env.example` 预留。

## #6 飞书扫码登录 + #5 飞书文件导入

### 你需要提供
1. 在 [飞书开放平台](https://open.feishu.cn/) 创建企业自建应用，拿到：
   - `App ID`、`App Secret` → 填入 `.env` 的 `FEISHU_APP_ID` / `FEISHU_APP_SECRET`
   - 配置「安全设置 → 重定向 URL」为你的回调地址 → 填 `FEISHU_REDIRECT_URI`
2. 开通权限：`contact:user.base:readonly`（登录获取用户）、
   `drive:drive:readonly` / `docs:doc:readonly`（读取云文档/文件）。

### 接入步骤（拿到凭据后）
1. 新增 `backend/app/services/feishu.py`：
   - `get_tenant_access_token()`：POST `https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal`
   - `get_login_url(state)` / `exchange_code(code)`：扫码登录 OAuth（authen/v1/access_token）
   - `list_drive_files()` / `download_drive_file(token)`：拉取云空间文件
2. 新增路由 `backend/app/routers/feishu.py`：
   - `GET /feishu/login-url`、`GET /feishu/callback`（建/绑定本地用户，复用现有 JWT 签发）
   - `POST /feishu/import`：把选中的飞书文件下载后，调用
     `app/services/file_intake.py::register_file_to_space` 登记进数据空间（与 download_to_space 同路径）。
3. 前端：登录页加「飞书扫码登录」按钮；数据空间页加「从飞书导入」入口。

## #5 邮件导入（IMAP）

### 你需要提供
- 邮箱 IMAP 主机/端口（`EMAIL_IMAP_HOST` / `EMAIL_IMAP_PORT`，默认 993）。
- **每用户**的邮箱账号 + 授权码（不要把私人邮箱密码写进全局 env；建议前端让用户自填，
  后端加密存储，参考现有 `decrypt_api_key` 的密钥管理）。

### 接入步骤
1. 新增 `backend/app/services/email_import.py`：用标准库 `imaplib` + `email`
   连接、按条件（发件人/主题/时间）拉取邮件与附件。
2. 路由 `POST /email/import`：把附件/正文落盘 → `register_file_to_space` 登记进数据空间。
3. 前端：数据空间页加「从邮箱导入」表单（邮箱、授权码、筛选条件）。

## 复用点（已就绪）
- 文件登记进空间：`app/services/file_intake.py::register_file_to_space`（自动建索引）。
- 下载落盘：`app/services/downloader.py`（含 SSRF 防护、大小限制）。
- 这两个已被 `download_to_space` 工具验证可用，飞书/邮件导入直接复用即可。

## 当前状态
- 配置位、复用服务已就绪；**服务层与路由尚未实现**（等凭据）。
- 不影响现有功能：未配置时这些入口不启用。
