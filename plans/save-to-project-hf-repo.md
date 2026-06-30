# 与 agent 聊天即可把数据保存进项目（含 HuggingFace 整仓下载）

## 需求

用户希望：和 agent 聊天时让它把外部数据「保存进当前项目」。
- 通用对话（未选项目）→ 明确告知不能保存，请先进项目；
- 选了项目 → 能保存，典型场景：把一个 HuggingFace 仓库下载进项目。

## 现状（已核查）

- 工具 `download_to_space`（tools.py:1535）**已存在**：选了项目能下载，自动登记+建索引。
- 通用对话时它已返回「未选择数据空间，无法下载。请先绑定一个数据空间」——**"通用不能存"的逻辑后端已有**，只是文案是给 agent 看的、且 agent 不一定主动转述。
- 下载器 `downloader.py` 支持 http/https 直链、GitHub、HuggingFace 单文件（自动改写到 hf-mirror.com），有 SSRF 防护 + 500MB 单文件上限。
- **真实缺口**：`download_url_to_path` 只能下**单个文件**（一个 URL→一个文件）。给 HF 仓库链接只会抓到一个文件/HTML 页面，**下不了整仓**。
- HF 已装 `huggingface_hub` 0.36.2；hf-mirror 的 `/api/{datasets|models}/{repo}/tree/{rev}` 可列出文件树（含 size），`/{...}/resolve/{rev}/{path}` 是单文件直链。
- agent 现在是「单一静态提示词 + 工具自助」，提示词没专门讲"保存数据/下载仓库"这条路径。

## 设计

### 1. 下载器：新增 HuggingFace 整仓下载

`app/services/downloader.py` 新增 `download_hf_repo_to_dir(repo_id, repo_type, dest_dir) -> list[(path, name)]`：
- 用 hf-mirror 的 tree API（`https://hf-mirror.com/api/{datasets|models}/{repo_id}/tree/main?recursive=true`）列出全部文件（含子目录）与 size。
- 跳过过大文件（单文件 > 500MB 上限，沿用 MAX_DOWNLOAD_BYTES）；累计总量上限（如 2GB）防把盘下满；文件数上限（如 200）。
- 逐个走 `resolve/main/{path}` 直链流式下载（复用现有 `download_url_to_path` 的流式+SSRF+大小校验）。
- 跳过 `.gitattributes` 等无意义文件可选；保留目录结构映射到文件名（用 `仓库名_子路径` 或扁平化，落盘到该 file_id 目录）。
- 返回已下载文件列表，交由工具层逐个 `register_file_to_space`。

新增 URL 解析 `parse_hf_url(url)`：识别 `huggingface.co/datasets/{repo}`、`huggingface.co/{org}/{model}`、或裸 `datasets/xxx`/`org/model` 形式，判定 repo_type（dataset/model）与 repo_id。

### 2. 工具：download_to_space 支持「仓库」

`app/agent/tools.py` `_tool_download_to_space`：
- 入参增加可选 `source_type`（auto|file|hf_repo），默认 auto。
- auto 时：URL 命中 HF 仓库形态（非单文件 resolve 链接）→ 走整仓下载；否则按现有单文件逻辑。
- 整仓：调用 `download_hf_repo_to_dir`，对每个文件 `register_file_to_space`，返回汇总（下载了 N 个文件、跳过哪些大文件、总大小）。
- 通用对话（无 data_space_id）的提示文案优化为面向用户：「当前是普通对话，没有可保存的项目。请先在左侧选择或新建一个项目，再让我把数据下载进去。」
- 工具 description 里写明：能下载 HF 整仓 / GitHub / 直链到当前项目；通用对话不可用。

### 3. 提示词：补「保存数据进项目」这条路径

`app/agent/loop.py` 静态提示词补一小节（简洁）：
- 用户要「把某数据/某 HF 仓库/某链接保存/下载进项目」时，用 `download_to_space`（支持 HF 整仓、GitHub、直链）。
- 若当前是普通对话（无项目），不要假装能存，明确告诉用户：先在左侧选/建项目再来，下载需要一个项目作为落点。
- 大模型权重等超大文件可能超限被跳过，如实告知。

### 4. 前端：基本无需改

- 下载是工具调用，进度在「工具调用」区已可见；完成后文件出现在项目里（DataManager 可见、可预览）。
- 可选小优化：agent 回答里用上次做的 ```file 块把下载好的关键文件渲染成文件卡（提示词可顺带提示），方便用户直接点开/下载。本次先不强加。

## 实施步骤

1. downloader.py：`parse_hf_url` + `download_hf_repo_to_dir`（tree 列举→逐文件下载，带大小/数量/总量上限）。
2. tools.py：`_tool_download_to_space` 支持 hf_repo 分支 + 优化通用对话文案 + 更新 tool description。
3. loop.py：提示词补「保存数据进项目 / 普通对话不可存」小节。
4. 验证：后端 import/语法；真实下载一个**小** HF dataset（如 fka/awesome-chatgpt-prompts，仅 ~5MB csv）到测试项目，确认多文件落盘+登记+索引；通用对话下让 agent 下载，确认它如实告知"请先进项目"。
5. 重启后端上线（纯后端改动，前端不动；如加文件卡提示则前端也构建）。

## 边界与安全

- 沿用 SSRF 防护（拒内网）、单文件 500MB、新增整仓总量上限（2GB）+ 文件数上限（200），防把磁盘下满 / 滥用。
- 大模型仓库（动辄几十 GB）会因超限被跳过并如实告知，不静默失败。
- 不引入 HF token（只下公开仓库）；私有仓库报错提示需登录，不在本次范围。
- 下载是 IO 密集，已在 async + 流式；整仓逐文件串行下载，避免并发把带宽/连接打满（可后续优化为有限并发）。

## 不做

- 不做私有 HF 仓库 / 需认证源（kaggle 等）。
- 不改沙箱、不做 agent 生成新文件。
- 不动多项目/文件卡既有逻辑。
