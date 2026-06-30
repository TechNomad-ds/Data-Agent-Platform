# 对话回答区支持「文件卡」展示

## 目标与范围

用户希望对话回答区能展示各种内容（除音视频外）。现状盘点：
- **表格** ✅ 已支持（markdown 表格 + ```answer CSV 结果卡）
- **图片** ✅ 已支持（markdown `![](url)` + 刚加的 img 样式）
- **代码/图表/公式** ✅ 已支持
- **文件** ❌ 缺口 —— assistant 回答里无法给出可下载/预览的文件卡

本次只做用户选定的范围：**展示「已有文件」的文件卡**（用户上传的 / 项目里的 / agent 下载进来的）。不做「agent 生成新文件供下载」（那需要改沙箱，是另一个大工程）。

触发方式（用户已选）：**agent 显式输出 ```file 块**，前端识别并渲染成文件卡。与现有 chart/answer 块同一套机制，最一致、不误伤正文里顺口提到的文件名。

## 关键约束（已核查）

- 下载接口 `GET /api/files/{file_id}/download` 已存在，需 JWT 鉴权（`Depends(get_current_user)` + `File.user_id == current_user.id`），流式返回、`Content-Disposition: attachment`。
- **agent 手里只有文件名，没有 file_id**（`list_files` 只返回文件名/类型/大小）。所以文件卡要靠「文件名 + 当前对话上下文」解析到可下载的文件。
- 前端 `api` axios 实例会自动带 JWT，下载要走 `api.get('/files/{id}/download', {responseType:'blob'})`（DataManager 的 ImagePreview 已是此模式），不能用裸 `<a href download>`（不带 token，401）。
- 后端 `_get_file_path(filename, user_id, data_space_id)` 已能按「文件名 + 活跃空间」解析文件（含跨空间、同名取第一个），新端点可复用同逻辑拿到 file_id。
- ChatView 已有 `conversationId` / `selectedSpaceId` / `selectedSpaceIds`，可下传给渲染器用于解析。

## 设计

### 后端：新增「按文件名解析为可下载文件」端点

`backend/app/routers/data_spaces.py` 新增：
```
GET /api/data-spaces/conversation/{conversation_id}/resolve-file?filename=xxx
```
- 鉴权：校验 conversation 属于 current_user（与现有 conversation 端点一致）。
- 逻辑：拿该对话的活跃空间集合（主空间 + 临时空间，与 chat.py 里 `extra_space_ids` 同源），在其中按 `filename` 查 File（复用 `_get_file_path` 的查询思路，按 user_id + filename + space 限定）。
- 返回：`{file_id, filename, file_type, file_size, mime_type}`；找不到返回 404。
- 为什么按对话解析而非全局：避免越权拿到别的空间/别人的同名文件；与 agent 本轮可见范围一致。

（备选：直接复用 `listConversationFiles` 在前端做文件名匹配。但那只覆盖临时区，不含主项目空间；新端点更准。）

### 前端：```file 块 → 文件卡组件

1. **MarkdownRenderer.tsx**：扩展 `specialBlockRe`，把 `chart|answer` 加上 `file`：
   `/```(chart|answer|file)\n([\s\S]*?)```/g`，新增分支渲染 `<FileCard>`。
   - 需要把 `conversationId` 透传进来：给 `MarkdownRenderer` 加可选 prop `conversationId`，由 MessageContent/ChatView 下传。

2. **新增 `FileCard.tsx`**：
   - 输入：```file 块内容（一行文件名，或 `文件名` JSON——先支持纯文件名，简单）。
   - 挂载时调用 resolve-file 拿到 file_id + 元信息。
   - 渲染：图标（按扩展名）+ 文件名 + 大小 + 「下载」按钮；图片类型额外给「预览」（复用 ImagePreview 的 blob 模式，弹 Modal）。
   - 下载：`api.get('/files/{id}/download',{responseType:'blob'})` → `file-saver` 的 saveAs（项目已装 file-saver，见 ExportButton）。
   - 解析失败（404）：降级显示「文件名（未找到，可能已删除）」纯文本，不报错、不留裂卡。

3. **样式**：卡片复用 colors token，与附件 chip 视觉一致（圆角、边框、bgSubtle）。

### 后端：提示词告诉 agent 怎么用 ```file 块

`backend/app/agent/loop.py` 的静态提示词「输出格式」段补一句：
- 当用户要「给我那个文件 / 把 X 文件发我 / 下载 X」或回答中需要让用户直接拿到某个**已存在的文件**时，用 ```file 块单独一行写文件名（如 ```file\nsales.csv```），平台会渲染成可下载/预览的文件卡。
- 仅用于数据空间里真实存在的文件（来自 list_files 的准确文件名）；不要臆造文件名；普通提及文件不必用。

## 实施步骤

1. 后端 resolve-file 端点（data_spaces.py）+ 复用 `_get_file_path` 逻辑。
2. 前端 FileCard.tsx 组件（resolve → 下载/预览，含失败降级）。
3. MarkdownRenderer 扩展 file 块 + 透传 conversationId；MessageContent/ChatView 下传 prop。
4. 提示词补 ```file 用法（loop.py）。
5. 验证：tsc 构建、后端 import/语法、重启、手测（让 agent 输出 ```file 块看是否成卡、能否下载、图片能否预览、不存在文件是否优雅降级）。

## 验证

- `npx tsc -b --noEmit` + `npm run build` 通过。
- 后端 `import app.main` 干净、重启 health 200。
- 手测：选个有文件的项目，让 agent「把 xxx.csv 发我下载」→ 出现文件卡 → 点下载得到文件；图片文件出现「预览」。
- 边界：```file 写一个不存在的文件名 → 优雅降级为纯文本提示，不报错。

## 不做

- 不做 agent 生成新文件（改沙箱，另立项）。
- 不做图片 lightbox/gallery（可作为后续小优化，本次先把文件卡做扎实）。
- 不动音视频。
- 不动鉴权模型、不裸链下载。
