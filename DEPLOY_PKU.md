# 北大平台部署与初测清单

面向定位：数据处理，帮助学生学习和复习课程知识。

## 1. 运行环境

- Python 使用 3.11 或 3.12，不使用 3.13+。
  - 当前依赖中 `pandas/chromadb/sentence-transformers` 对 3.13 不稳定，可能触发源码编译或安装失败。
  - `deploy.sh` 已做版本拦截；必要时用 `PYTHON_BIN=/path/to/python3.11 bash deploy.sh`。
- Node.js 使用 18+。
- PostgreSQL 使用 16，Redis 使用 7。
- 后端生产启动使用 `start-backend.sh` 或：

```bash
cd backend
venv/bin/gunicorn app.main:app -c gunicorn.conf.py
```

## 2. 必填配置

上线前必须修改：

- `.env` 中的 `SECRET_KEY`
- `.env` 中的 `ADMIN_PASSWORD`
- `DATABASE_URL` / `DATABASE_URL_SYNC`
- `REDIS_URL`
- `FRONTEND_URL`，填写真实前端域名，例如 `https://xxx.pku.edu.cn`
- LLM 配置：`LLM_BACKEND` 及对应 API Key

如果通过 Nginx 暴露服务：

- `client_max_body_size` 不低于 `200M`
- `/api` 代理到后端 `127.0.0.1:8002` 或实际后端地址
- SSE 对话需要关闭代理缓冲：`proxy_buffering off`
- 上传请求建议关闭代理请求缓冲：`proxy_request_buffering off`
- `proxy_read_timeout` 不低于 `300s`

主机部署示例：

```bash
cd /path/to/Data-Agent-Platform
cd frontend && npm install && npm run build && cd ..
sudo mkdir -p /var/www/datamind
sudo rsync -a --delete frontend/dist/ /var/www/datamind/

# 复制 frontend/nginx.conf 后，把 root 改为 /var/www/datamind
sudo cp frontend/nginx.conf /etc/nginx/sites-available/datamind
sudo ln -sf /etc/nginx/sites-available/datamind /etc/nginx/sites-enabled/datamind
sudo nginx -t
sudo systemctl reload nginx
```

注意：`frontend/nginx.conf` 默认适用于“前端 Nginx 和后端 gunicorn 在同一台主机”的部署，代理到 `127.0.0.1:8002`。如果后续改成 Docker 网络，需要把 `proxy_pass` 改成对应服务名。

## 3. 课程资料支持范围

推荐学生上传：

- 文档：PDF、DOCX、PPTX、TXT、Markdown
- 表格：CSV、TSV、Excel、JSON/JSONL（多 sheet Excel 会自动展开为多张表）
- 笔记/代码：Markdown、TXT、Python、SQL、Jupyter Notebook
- 压缩包：ZIP

注意：

- 旧版 `.ppt` 可以上传留档，但无法稳定抽取文本；建议转为 `.pptx` 后上传。
- 扫描版 PDF/图片依赖 OCR 配置；未配置 OCR 时只保证可上传和基础画像。

## 4. 初测脚本

可先运行自动化基础链路验收。该脚本会生成 3 门课的 DOCX/PPTX/Markdown/TXT/CSV/多 sheet Excel 资料，通过 API 完成注册/登录、数据空间创建与改名、穿插上传、7 文件批量上传、文档/Excel 预览、处理状态和会话空间绑定检查；默认不调用 LLM。

```bash
# 前端关键回归：公式渲染与流式会话隔离
node scripts/pku_frontend_regression_check.mjs

# 在后端服务已经启动后运行
backend/venv/bin/python scripts/pku_acceptance_smoke.py \
  --base-url http://127.0.0.1:8002

# 如需复用固定测试账号
DATAMIND_SMOKE_EMAIL=pku-smoke@example.com \
DATAMIND_SMOKE_USERNAME=pku_smoke \
DATAMIND_SMOKE_PASSWORD='替换为强密码' \
backend/venv/bin/python scripts/pku_acceptance_smoke.py
```

脚本成功后会输出并写入 `eval/pku_acceptance_report.json`。如果失败，先根据报错检查后端日志和 `.env` 配置。

基础链路通过后，再运行真实 LLM 验收。该脚本会消耗模型额度/API 调用，用于验证多 sheet Excel 联合分析、公式回答、个性化学习解释和评论情感分类：

```bash
backend/venv/bin/python scripts/pku_llm_acceptance_check.py \
  --base-url http://127.0.0.1:8002

# 如需指定模型
DATAMIND_LLM_MODEL_ID=<模型ID> \
backend/venv/bin/python scripts/pku_llm_acceptance_check.py

# 复用固定账号重复验收时，可指定批次名避免数据空间混淆
DATAMIND_LLM_RUN_LABEL=round2 \
backend/venv/bin/python scripts/pku_llm_acceptance_check.py
```

脚本成功后会输出并写入 `eval/pku_llm_acceptance_report.json`。该报告可作为人工截图验收前的机器检查证据。

自动化脚本通过后，再做人工问答验收：

```bash
cp PKU_ACCEPTANCE_REPORT_TEMPLATE.md eval/pku_acceptance_manual_report.md
```

按 `eval/pku_acceptance_manual_report.md` 记录每个问题的通过标准、截图位置和问题日志。

建议创建 3 个数据空间：

1. `计算机体系结构`
   - 上传：PDF 讲义、PPTX 课件、Markdown/Word 个人笔记。
   - 问题：
     - “请解释流水线冒险、缓存局部性和 CPI 的关系。”
     - “我擅长 Python，但没学过硬件，我该如何理解 cache miss？”
     - “用公式说明平均访存时间 AMAT。”

2. `线性代数复习`
   - 上传：PDF/Word 笔记、PPTX 课件、习题 CSV 或 Markdown。
   - 问题：
     - “特征值和特征向量的几何意义是什么？”
     - “我会解方程组，但没理解线性变换，怎么理解矩阵？”
     - “把正交投影的公式用 LaTeX 写出来。”

3. `现代文学导论`
   - 上传：Word 阅读笔记、PPTX 课件、Markdown 摘要。
   - 问题：
     - “比较鲁迅和沈从文的叙事风格。”
     - “如果我熟悉历史背景但文学理论薄弱，应该怎么复习？”

穿插测试流程：

1. 先上传 `计算机体系结构` 的 2-3 个文件并提问。
2. 切到 `现代文学导论` 上传资料并提问。
3. 再切回 `计算机体系结构`，追问开头提过的 cache/CPI 话题。
4. 在某个数据空间回答流式输出时切到通用对话，确认通用对话界面不被污染。
5. 一次选择 7 个文件上传，确认不会出现“请求频繁”。
6. 提问包含公式的题目，确认 `$...$` 和 `$$...$$` 正常渲染。
7. 修改数据空间名称，确认列表和详情页展示更新。

## 5. 验收截图建议

如果效果好，建议截图：

- 数据空间列表，展示不同课程空间。
- 一个课程空间内多格式文件列表。
- PPTX/Word/PDF 混合资料后的课程问答。
- 含公式的回答。
- 个性化学习路径回答。
- 切换空间后仍能追问早先话题的回答。

如果效果不好，记录：

- 使用的数据空间名称。
- 上传文件格式和数量。
- 问题原文。
- 回答截图。
- 后端日志中对应时间段的错误。
