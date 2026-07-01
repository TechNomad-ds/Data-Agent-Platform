# 重新设计 agent：去掉伪路由 + schema 预加载，回归「单一 agent + 工具自助」

## 背景与诊断

用户指出 `loop.py` 的 agent 设计过度工程化，三点直觉：
1. 不该分「数据分析 / 普通对话」，就是**一个 agent**，回答问题——可能有文件、可能没有。
2. 工具**全给 agent**，描述清楚每个干嘛的，让它自己选；不要做路由。
3. 不要**预加载 schema**，放进工具里，agent 想看自己探索。

核查现状（已确认）：
- **其实没有真正的工具路由**——所有工具每轮都全量给模型（`loop.py:1239`），唯一例外是迭代到上限强制收尾时清空。用户感觉到的「路由」实为两样东西：
  - 提示词里大段「先判断问题类型（不依赖文件/读文件/分析表格三分类）+ 何时用哪个工具」的说教（160+ 行，分裂成 `DATA_MODE_GUIDANCE` 120 行 / `GENERAL_MODE_GUIDANCE` 7 行）。
  - `_should_include_data_context`：用一堆关键词（"数据空间/文件/CSV/schema"…）猜本轮要不要灌 schema —— 脆弱的「伪路由」。
- **schema 预加载是真问题**（`_build_schema_context`，300 行）：每轮可能跑、最坏 5-10 秒、加载整个 DataFrame 进内存峰值可达数 GB、与 `inspect_data`/`list_files` 工具重复，且**让 system prompt 每轮变动、击穿 Claude prompt 缓存**。
- 已确认所有数据工具在无 space/空 space 时都自带兜底（返回「未选择数据空间」「当前数据空间为空」），不会报错——所以无需在提示词层面禁用工具。
- `list_files` 已输出「共 N 个文件（X 个 pdf、Y 个 csv…）+ 清单」，完全覆盖预加载的 data_space_info。
- `inspect_data` 已按需暴露 schema/列/样本/join 建议，完全覆盖 `_build_schema_context`。

用户两个决策：
- 文件存在性：**注入一行极简提示**（挂载 N 个文件 / 当前无文件），不靠关键词门控。
- knowledge.md：**当普通文件，提示词完全不提**（比赛遗留，真实场景不存在）。

## 目标

`loop.py` 回归：**一个通用 agent + 全量工具 + 工具描述自带用法 + 一行文件提示**。删掉伪路由、双套提示词、schema 预加载、knowledge 特殊处理。系统提示词从 160+ 行压到 ~50 行且**完全静态**（除一行文件计数），prompt 缓存稳定命中。

## 改动清单（全部在 `backend/app/agent/loop.py`，纯后端）

### 1. 重写系统提示词为单一静态模板
- 删除 `DATA_MODE_GUIDANCE`（175-294）、`GENERAL_MODE_GUIDANCE`（301-307）两个常量。
- `SYSTEM_PROMPT_TEMPLATE`（134-168）重写为一个 ~50 行的精简模板，只保留：
  - 角色：通用 AI 智能体，回答问题——可能要读用户上传的文件，也可能是纯知识/写作/闲聊。
  - **不预设模式**：不写「先判断是不是数据分析」三分类。改为一句：有需要就用工具看文件/查数据，没需要就直接答。
  - 保留真正有价值的「行为规范」（这些不是路由，是质量约束）：
    - 逐篇讲解/总结整篇文档必须 read_file 读到「全文已读完」，禁止读开头就概括（这是之前刚修的，保留精简版）。
    - 取数要查全/去重口径/读准字段/收尾自检（精简成 3-4 条）。
    - 如实汇报、歧义先澄清、update_plan 多步任务用、输出格式（LaTeX/Markdown）。
  - 占位符只留 `{file_notice}` 和 `{memory_context}`。删掉 `{data_space_info}`/`{schema_context}`/`{knowledge_context}`/`{data_mode_guidance}`。

### 2. 一行文件提示替代预加载
- 新增一个轻量 `_file_notice(data_space_id, user_id)`：只做一次 `COUNT` + 类型聚合，返回单行，例如：
  - 有文件：`【当前挂载了 4 个文件（4 个 pdf）。需要时用 list_files 看清单、read_file 读内容、inspect_data 看表结构。】`
  - 无文件：`【当前没有挂载文件。这是一次普通对话；若用户要分析文件，提示他在左侧选项目或拖文件上传。】`
- 不加载 DataFrame、不读列、不读 knowledge.md。一次 DB count，O(1) 级。

### 3. 删除预加载与伪路由代码
删除以下函数/常量（已确认仅被 prompt 组装路径引用，无外部依赖）：
- `_should_include_data_context`（368-381）
- `_DATA_CONTEXT_TRIGGERS`（337-356）、`_GENERAL_CONTEXT_HINTS`（360-365）
- `_build_schema_context`（580-874，~300 行）
- `_get_data_space_info`（455-531）、`_get_selected_space_notice`（383-453）
- `_get_knowledge_context`（922-936）
- `_rank_files_by_relevance`（533-578）、`_detect_joins_for_schema`（876-915）
- 注意：`_rank_files_by_relevance` 若被检索服务别处复用需先确认（grep 显示只在 `_build_schema_context` 内调用，安全）。

### 4. 简化 run() 的 prompt 组装（1156-1186）
替换为：
```python
file_notice = await self._file_notice(data_space_id, user_id)
memory_context = ...  # 保留现有 recall 逻辑
system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
    file_notice=file_notice,
    memory_context=memory_context,
)
```
- 删掉 `has_any_space`/`prefetch_data_detail`/双分支。
- prompt 缓存块逻辑（1188-1195）不变——现在缓存几乎总是命中（只有文件数变化时 file_notice 才变）。

### 5. 工具层不动
- 工具全量下发、dispatch 注册表、active_spaces 机制全部保留——它们本来就对，用户要的「全给 agent、自己选」现状已满足。
- 工具描述已自带用法说明（`【读文件核心工具】`/`【表格分析】` 等），无需改。

## 影响与权衡

- **正向**：提示词 160+→~50 行且静态；删 ~600 行预加载代码；消除每轮 5-10s / 数 GB 内存峰值；prompt 缓存稳定命中（省 token、降延迟）；逻辑大幅简化、易维护。
- **代价**：分析类任务首轮会多 1 次 `list_files`/`inspect_data` 往返（agent 自助探索）。这正是用户想要的取舍，且符合 codex/claude code 的「瘦 prompt + 自助工具」范式。
- **行为规范不丢**：读文档读全、取数自检这些**质量约束**精简保留（它们不是路由，删了会回归老 bug）。

## 验证

1. `python -c "import ast; ast.parse(...)"` + `import app.main` 校验语法/导入。
2. 重启后端，health 200，日志无异常。
3. 手测三类对话：
   - 纯知识问答（无项目）→ 直接答，不乱调工具。
   - 选了项目问「有哪些文件」→ agent 调 list_files 给完整清单。
   - 选了项目做数据分析 → agent 自助 inspect_data→sqlite_query/pandas_query。
   - 逐篇讲解 PDF → 仍读到「全文已读完」才总结（规范保留）。
4. 确认 prompt 缓存命中（观察 token usage 的 cache_read）。

## 不做

- 不动工具实现、不动 active_spaces、不动 context compaction、不动计费。
- 不删 `inspect_data`/`list_files` 等工具（它们正是预加载的按需替代）。
- 前端不动。
