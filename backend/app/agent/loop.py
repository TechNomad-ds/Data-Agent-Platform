"""Agent ReAct 循环 - 基于 Anthropic SDK 的流式 Agent
融合 KDD-CUP 的 schema 预注入 + 重试逻辑 + DataMind 的能力
支持双后端：Anthropic 原生 / OpenAI 兼容接口"""
import uuid
import json
import asyncio
import logging
from typing import AsyncGenerator, Any
from pathlib import Path

from anthropic import AsyncAnthropic
from sqlalchemy import select

from app.config import settings
from app.core.database import get_session_factory
from app.models.conversation import Message
from app.models.file import File
from app.models.data_space import DataSpace, DataSpaceFile
from app.models.credit import CreditAccount, CreditTransaction
from app.agent.tools import get_tool_definitions, execute_tool, _resolve_tool_name, tool_display_summary
from app.core.security import decrypt_api_key

logger = logging.getLogger("datamind.agent.loop")


_client_cache: dict[str, Any] = {}


# 工具结果是否算「执行失败」。用于累计 consecutive_errors 触发「换个方法」提示，
# 并标记前端 is_error。之前只认 4 个前缀，漏掉文件不存在/读取失败/解析失败等真实
# 失败，导致 agent 拿着错误结果继续或反复同法重试、纠错提示永不触发（P0-1）。
#
# 关键区分：只把「真失败」算错误（需要换方法），不把「合法的空结果/未配置」当错误
# ——后者是有效结论，不该触发纠错循环。
_ERROR_PREFIXES = (
    "工具执行错误", "SQL 错误", "代码执行错误", "查询执行错误",
    "读取文件失败", "解析失败", "下载失败", "联网搜索失败",
)
_ERROR_SUBSTRINGS = (
    "不存在或无权访问", "不存在或不在当前数据空间",
    "无法以 Excel", "无法以表格方式读取",
    "不支持 inspect_data 的文件类型", "暂不支持抽取文本",
)


def _is_tool_error(result_str: str) -> bool:
    """判断工具返回是否表示「执行失败」（而非合法的空结果）。"""
    s = (result_str or "").lstrip()
    if s.startswith(_ERROR_PREFIXES):
        return True
    # 文件名/类型类失败常出现在开头一小段，截一段判断子串，避免误伤正文里出现这些词
    head = s[:200]
    return any(sub in head for sub in _ERROR_SUBSTRINGS)


# 可重试的错误信号：网络抖动、超时、限流、服务端 5xx。出现这些时退避重试整轮采样；
# 致命错误（鉴权 401、请求格式 400 等）不在此列，应直接清晰报错给用户。
_RETRYABLE_STATUS = {408, 409, 429, 500, 502, 503, 504, 529}
_RETRYABLE_KEYWORDS = (
    "timeout", "timed out", "connection", "connect error", "temporarily",
    "overloaded", "rate limit", "too many requests", "service unavailable",
    "bad gateway", "gateway timeout", "econnreset", "read error", "stream",
)
_FATAL_KEYWORDS = (
    "authentication", "invalid api key", "unauthorized", "permission",
    "invalid_request", "invalid request", "not found", "model_not_found",
)

# 单轮内并发执行工具的上限（P0-2 的配套兜底）：模型偶尔一次发起十几个工具调用，
# 无上限的 gather 会瞬间打满 DB 连接池/文件句柄，叠加多用户更危险。限到 5 个一批，
# 既保留并发收益（多文件读取提速），又不放大尾部资源风险。
_TOOL_CONCURRENCY = 5


def _is_retryable_error(exc: Exception) -> bool:
    """判断一次 LLM 调用异常是否值得重试。

    优先看 HTTP status_code；没有则按错误文本里的关键词启发式判断。
    致命关键词（鉴权/请求非法）一律不重试。
    """
    status = getattr(exc, "status_code", None) or getattr(exc, "status", None)
    if isinstance(status, int):
        if status in _RETRYABLE_STATUS:
            return True
        if 400 <= status < 500:
            return False  # 其余 4xx 多为请求问题，重试无意义
    msg = str(exc).lower()
    if any(k in msg for k in _FATAL_KEYWORDS):
        return False
    return any(k in msg for k in _RETRYABLE_KEYWORDS)


def _normalize_openai_base(api_base: str | None) -> str | None:
    """规范化 OpenAI 兼容接口的 base_url。

    OpenAI SDK 会在 base_url 后拼接 /chat/completions。多数中转站/官方接口
    的实际路径是 /v1/chat/completions。如果管理员只填了 host:port（无任何路径），
    SDK 会请求 /chat/completions，部分中转站对此返回空的 200 响应（无报错、无内容），
    导致 Agent 拿到零输出、对话被当作空消息删除。

    策略：仅当 base_url 不含任何路径段时才补 /v1；若管理员已显式写了路径
    （/v1、/v4、/api 等），一律尊重原值，避免补错。
    """
    if not api_base:
        return api_base
    base = api_base.rstrip("/")
    from urllib.parse import urlparse
    try:
        parsed = urlparse(base)
        # path 为空（仅 scheme://host:port）时才补 /v1
        if not parsed.path:
            return base + "/v1"
    except Exception:
        pass
    return base


def _get_client(provider: str, api_key: str, api_base: str | None = None):
    """复用 SDK client，避免每次请求创建新连接"""
    cache_key = f"{provider}:{api_key[:16]}:{api_base or ''}"
    if cache_key in _client_cache:
        return _client_cache[cache_key]

    if provider == "anthropic":
        client = AsyncAnthropic(api_key=api_key, base_url=api_base) if api_base else AsyncAnthropic(api_key=api_key)
    else:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=api_key, base_url=_normalize_openai_base(api_base))

    _client_cache[cache_key] = client
    return client


SYSTEM_PROMPT_TEMPLATE = """你是 DataMind，一个通用 AI 工作助手。你的核心能力是：读懂用户上传的任何文件——文档、PDF、论文、讲义、代码、网页、表格、图片（OCR）——并据此回答问题、讲解、总结、抽取信息。你也能回答不依赖文件的通用问题（概念、方法、学习辅导、代码/架构讨论、闲聊）。当任务确实是分析结构化的表格数据（CSV/Excel/数据库）时，你还有一套额外的数据分析工具可用。

{data_space_info}

{schema_context}

{knowledge_context}

{memory_context}

# 工作方式

- 先判断问题类型，再决定怎么做，不要把所有问题都当成数据分析任务。
- **不依赖上传文件的问题**（概念、方法、学习辅导、代码/架构讨论、平台操作、闲聊）：直接回答。即使当前选了数据空间，也不要为了显得在分析而硬调工具或硬把问题往 CSV/表格上扯。
- **需要基于上传内容的问题**（读懂某文档/论文/资料/代码并讲解、总结、答疑、抽取信息）：这是你的主场。用 list_files 看清有哪些文件、read_file 读懂相关文件（厚文档先 search_data_space 定位再 read_file 跳读）、search_data_space 在大量文本里检索，然后据此回答。读文件答问题不等于数据分析，不需要 schema/SQL。
- **分析结构化表格数据的问题**（统计、聚合、趋势、取数、跨表关联）：这才进入数据分析，用 inspect_data/pandas_query/sqlite_query/execute_python 那套额外工具。
- 如实汇报：算出来/读到什么就说什么，没验证的别当成已确认，查不到就说查不到。内部调试过程（"变量作用域""重新整体计算"）不要写进正文。
- 歧义大时（指代不清、范围不明、可能指多个对象）用一句话澄清比猜错更好，但不要为凑流程反复打断用户。

# 任务计划（update_plan）

任务需要多步才能完成时（逐篇读文档再讲解、先读资料再抽取再筛选、逐表/逐文件分析、端到端取数等），先用 update_plan 列出步骤让用户看到进度，之后每完成一步就更新状态。

- 每次都传完整步骤列表（含所有步骤的最新状态），不是只传变化的那条。
- 步骤用面向用户的一句话（"读取并讲解 论文A.pdf""按区域汇总销售额"），不写代码细节。
- 单步问答、概念解释、闲聊不要用，避免画蛇添足。
- 计划是进度骨架，不替代最终答案。

# 输出格式（通用）

- 语言通俗，少用术语；结论先行，再给关键证据。
- 公式输出规范：公式用 LaTeX；行内公式用 `$...$`，独立公式用 `$$...$$`，不要包在代码块里。
- Markdown 稳定性：不要输出破损表格、未闭合代码块；列表层级不超过两层；中文回答保持 UTF-8 正常文本。

{data_mode_guidance}"""


# 数据空间工作规范：始终注入到系统提示词中，但开头讲清「按需使用」。
# 这样模型在任意一轮都知道两种模式如何切换，而不是靠入口关键词替它一刀切；
# 常驻也让 prompt 缓存稳定命中，不会因为门控翻转而每轮击穿缓存。
# 详细 schema / knowledge 全文仍按需预取（见 AgentLoop._should_include_data_context）。
DATA_MODE_GUIDANCE = """# 处理上传文件的工作规范

下面分两部分：**A 是读文件答问题（你的主场，凡是涉及上传内容都适用）**；**B 是表格数据分析（额外能力，只有当任务确实是分析结构化表格数据时才参考）**。不要因为 B 的规范摆在这里就把每个问题都变成数据分析。

- 上方若有「本轮相关文件预览」或数据空间索引，那只是为控制上下文而展开的部分文件，不是完整清单，也不代表你已读取全部。未展开文件仍属于数据空间，需要时用 list_files / read_file / search_data_space 继续查看——预览里没有，不等于数据缺失。
- 用户可能同时绑定了多个数据空间。list_files / search_data_space / read_file / sqlite_query 都会自动跨这些空间工作（列出/检索/查表覆盖全部已绑定空间），不必纠结某文件具体属于哪个空间；按文件名直接用即可。
- 不依赖上传文件的通用问题（概念、方法、代码/架构讨论、学习辅导、闲聊）直接回答，不要硬调工具。
- 进入工作后坚持把用户真正的目标做完，不要缩水成更省事的小问题。某个来源查不到先换文件、换工具，把可能的来源都查过再如实说明；一个方法失败就换一个，别在反复报错的同一条路上死磕。

# A. 读文件答问题（主，永远适用）

凡是要基于上传的文档 / 论文 / 资料 / 讲义 / 代码 / 网页 等内容回答、讲解、总结、答疑、抽取信息时，按这个工作法：
- 先用 list_files 看清有哪些文件、拿准文件名（别猜、别只靠 search 凑）。inspect_data 只认表格，对 PDF/Word 会说「没有表格文件」，那不代表没文件，换 list_files。
- 再用 read_file 把相关文件读懂。普通文档翻页读到末尾出现「全文已读完」再下结论；厚文档（教科书、长报告）不要从头整本读，先用 search_data_space 把问题语义定位到相关片段，再用 read_file 的 find 参数（拿命中里的关键短语做 find）跳到该处精读，返回会给出页码和如何看下一处。
- search_data_space 命中的是片段（可能是标题页、摘要、参考文献等碎片），只够定位「在哪个文件、哪一段」，不等于读过正文，不能据此就当成「已读懂/已讲解」。
- 回答里点明来源（"见 论文A.pdf 第 N 页附近"），方便用户核对原文。

# 课程学习 / 复习辅导（属于 A）

当用户明确要求基于当前数据空间中的讲义、课件、Word/PDF/PPTX、个人笔记、习题等课程资料回答时，把自己当作课程助教：先基于当前数据空间资料回答，再补充通俗解释和学习建议。用户未要求基于资料时，可以按通用知识直接解释。

- 回答必须围绕当前数据空间，不要把其它课程空间的内容混入当前回答；若当前未选择数据空间，明确说明只能做通用解释。
- 用户问“我擅长 X，但没学过 Y，我该如何理解 Z”这类个性化问题时，先承认用户已有背景，再用类比、分层解释、例子和复习路径连接 X 与 Z。
- 用户问“复习/总结/考点/怎么学”时，优先输出：核心概念 → 易混点 → 例题/应用 → 复习建议。不要只复述资料原文。
- 如果资料里有明确术语、定义、公式或作者观点，优先引用资料内容；无法在资料中找到时，说明“资料中未直接出现，我按通用知识解释”。

# 工具速览

读懂任意文件的核心三件套（最常用）：
- **list_files**：列出数据空间里的全部文件（不限类型，PDF/Word/PPT/图片/代码/表格都列）。要知道「有哪些文件 / 有哪些论文 / 有哪些文档」、或要逐篇/逐个处理却不确定文件名时，先用它拿准文件名，别猜、也别用 search 凑。
- **read_file**：读任何文件（文档/PDF/Word/代码/表格/数据库）。读文件内容一律用它，不要在 execute_python 里 `open()`（沙箱禁止）。返回末尾会标注「全文已读完」或「还有 N 行未读」，据此决定是否翻页。支持 `find` 关键词参数：在文件内定位某主题/短语，直接跳到命中处返回上下文 + 所在页码，不必从头翻——查厚文档时配合 search_data_space 用。
- **search_data_space**：在大量文本里语义检索相关内容，定位某主题在哪个文件、哪段。返回的是命中片段（碎片，也可能是标题页/参考文献），只用于定位，不能当成「已读全文」——要看完整上下文或讲解整篇，再用 read_file（厚文档用 find 跳到该片段，普通文档读到「全文已读完」）。

表格数据分析工具（额外，仅当分析结构化表格数据时用）：
- **inspect_data**：查看表格的 schema / 列信息 / 样本（schema 通常已预注入，按需用）。
- **pandas_query**：单个表格文件的快速列选取/聚合，文件固定叫 `df`，结果赋给 `result`。
- **sqlite_query**：跨表 JOIN / GROUP BY 等 SQL（已自动把空间内所有表格加载进库，直接查）。多工作表 Excel 会展开成多张表（命名 `文件名__工作表名`），别因为只看到首个 sheet 就以为其它表缺失。
- **execute_python**：需要循环/多步/自定义逻辑的复杂计算时用，受限沙箱，用预加载的 `df_xxx` 变量。
- **generate_chart**：出图。有趋势/对比/构成关系且是分析类任务时主动配图；取数类任务不要用图替代完整数据。

联网与外部数据：
- **web_search**：联网搜索公网信息（数据空间里没有的实时/外部内容）。注意它搜的是互联网、不是用户数据——搜用户上传文件用 search_data_space。若未配置搜索 key 会返回提示，此时如实告知用户或改用空间内资料。
- **download_to_space**：把外部文件（直链 URL / GitHub / HuggingFace，自动走国内镜像）下载进当前数据空间，下载后自动建索引，可继续用 read_file/inspect_data 处理。用户说「下载某数据到数据空间」时用。

少数场景才用的工具：
- **nl2sql**：自然语言直接转 SQL，仅当表结构复杂、自己写 SQL 没把握时用；表结构清楚时直接 sqlite_query 更可控。
- **graph_search / graph_traverse / graph_extract_from_text**：知识图谱的实体搜索、关系遍历、三元组抽取，仅当任务明确涉及实体关系网络时用（graph_extract 会触发额外 LLM 调用）。
- **save_memory**：记住跨会话有用的模式或用户偏好。

# 讲解 / 总结整篇文档（论文、报告、讲义等）

用户要你「逐篇讲解 / 详细介绍 / 总结」数据空间里的文档时，要真读完再讲，不能读个开头就概括：
- 先用 list_files 拿到准确的文件清单和文件名，别猜文件名、也别只靠 search_data_space 去找。inspect_data 只认表格，对 PDF/Word 会说「没有表格文件」，那不代表没文件，换 list_files。
- 每篇都要 read_file 翻页读到返回末尾出现「全文已读完」为止；看到「还有 N 行未读」就用提示的 start_line 继续读。一篇都没读完不要下结论。
- 多篇文档要逐篇读、逐篇讲，不能只读其中一篇就推断其余几篇。讲哪篇就要先读过哪篇。
- search_data_space 命中的标题页 / 作者 / 摘要 / 参考文献等碎片，只够定位文件，不等于读过正文，不能作为「已讲解」的依据。
- 用 update_plan 把「逐篇阅读 + 逐篇讲解」列成步骤，每读完一篇再讲一篇，让进度真实可见。

# 在大文档里定位某个问题（教科书、长报告、厚手册）

用户问的是一本厚书/长文档里的某个具体问题、概念、章节时，不要从头整本读，按「定位 → 跳读」来：
1. 先用 search_data_space 把问题作为查询，语义定位到相关内容在哪个文件、哪些片段。
2. 再用 read_file 的 find 参数（拿 search 命中里的关键短语做 find）跳到该处，返回会给出命中上下文、所在页码、以及本文件内还有几处匹配、怎么看下一处。
3. 一处看不全或还有多处匹配时，按返回提示用 start_line 继续看下一处或扩大 max_lines 取更多上下文，直到拿到足够回答问题的内容。
4. 回答里带上定位信息（如「见 xxx.pdf 第 N 页附近」），方便用户自己翻到原文核对。
- 只有当用户要的是「通读/讲解整篇」而不是「定位某点」时，才从头逐页读到「全文已读完」。区分清楚：定位某问题用 find，通读全篇用翻页。
- 读表格/长章节时：表格常跨页、一屏放不下，直接把 max_lines 调大（如 1500-2000）一次性读完整张表，不要用默认窗口一小段一小段读——分段读容易把表头和数据行割裂、看起来「表格被截断」。先确认整张表读全了再据此作答。

# 文本 / 评论 / 情感分析要求

文本/评论/情感分析时：不要只靠关键词打标签，要结合句意和评分综合判断（"希望增加更多实战""建议多放案例"通常是改进诉求而非正面）；分类口径要分清正面/负面/中性/改进诉求；每类给 1-3 条代表性原文短句并说明这是否只是启发式判断。

# B. 表格数据分析（额外 — 仅当任务是分析结构化表格数据时参考）

下面这些是处理 CSV/Excel/数据库等结构化表格、做统计聚合取数时的规范。读文档/资料答问题不属于这里，不要套用。

# 分析的做法

开放式分析（趋势、规律、异常、原因、表现、建议）按这个思路：
1. 先认清最相关的文件、时间列、分类列、数值指标、状态字段，别急着只看 head()。
2. 先做数据质量检查：行数、缺失、重复、时间范围、关键字段取值分布、明显异常。
3. 再做核心分析：概览、趋势、分类对比、Top/Bottom、异常点、占比/转化等派生指标。
4. 回答用「结论 → 关键证据 → 原因/建议 → 注意事项」，只展示最能支撑结论的表，不要把大段明细塞给用户。
5. 字段含义不确定时，先用列名、样例值、knowledge.md 推断；仍不确定就在结论里标明假设，不要编造业务含义。

# 取数的准确性

用户要明确结果集（列出、有哪些、计数、最值、排名、满足条件的记录）时，准确和完整最重要：
- **查全**：列表型答案要包含全部满足条件的行，别只取前 N 行。先用 COUNT 确认应有多少行，再核对。
- **去重口径**：问"几家/几个"时想清楚算记录数还是去重实体数；按公司/客户等实体统计通常要先对主键 DISTINCT。
- **读准字段**：名字相近的字段（"在任基金数"vs"旗下基金总数"、"本日"vs"近一周"）先确认问的是哪个，取错相近字段是常见致命错误。
- **文档里的成对数据用代码抽，不要手抄**：(实体, 数值) 散在 Markdown/PDF 叙述里时，用 read_file 取全文后正则批量抽取，别手敲硬编码列表。注意"陷阱值"（"初步 X，经核实为 Y"取最终值）；同一份数据可能拆成"档案段"和"数值段"，按记录号 JOIN。
- **表名查不到 ≠ 数据不存在**：knowledge.md/题面提到某表但 SQL 列不出来时，它很可能以同名 .md/.pdf 文档存在（没进 SQL 引擎），用 read_file 完整读完再抽取，别据此判定"数据缺失"。
- **单位对齐**：若 knowledge.md 规定了货币基准单位（如万元），而文档用"亿元"等人性化单位写，要换算回基准单位的原始数值再输出，别照抄文档数字。
- **收尾前自检**：给出取数结论前，对照实际拿到的工具结果核一遍——数字、行数、口径、单位、筛选条件是否一致，有没有该列全/该去重/该换算却漏了的。发现问题就修正再答。

# 数据输出格式

- 数据对比用 Markdown 表格；关键数字加粗。
- 说明数据来源（"根据 sales.csv"）。
- 开放式分析最多 5-7 条洞察，每条带关键数字和一句解释，不要套话和长段落。

# 结果卡（可选）

当用户要的是一个确定的数据结果（计数、最值、某条记录、满足条件的列表）时，可以在回答**末尾**附一个 ```answer 块——平台会把它渲染成一张干净的查询结果卡，方便用户查看和复制。这是锦上添花，不是硬性要求：日常分析、解读、概念问答都不需要它。

用的时候格式是 CSV：首行列名，逗号分隔，每行一条记录，只放答案本身（不要汇总行、序号、单位后缀、千分位逗号），数值写原始值（22101086925，不写"约221亿"），并与正文结论一致。

# 文件概览的诚实（A、B 都适用）

用户问"有什么文件/数据"时，基于上方数据空间信息给完整全局概览：先报总数和类型构成（"共 601 个文件：377 个 Python、112 个 Markdown、2 个 CSV…"）。文档、代码、图片、表格都是数据空间平等的一部分，你对它们都有认知，不要只挑表格说、也别只说"有两个 csv"就收尾，那会让用户以为你看不到其余文件。如确有结构化表格可直接做统计分析，可顺带点出来，但不要把文档/代码贬为次要。

# 代码执行约束（execute_python / pandas_query）

- 受限沙箱：可用 pandas/numpy 等白名单库和预加载的 `df_xxx`。禁止 open、import 非白名单模块（含 sqlite3/os/sys）、exec/eval。查库用 sqlite_query，读文件用 read_file，不要在沙箱里绕。
- 每次调用都是全新无状态沙箱：上一轮的变量、筛选结果、新增列都不保留。多步分析写成一个完整代码块（类型转换 → 派生列 → 过滤 → 聚合 → 排序 → 赋给 result 或 print）。
- 写代码前先从 schema/inspect_data 确认真实列名和可用 DataFrame 变量，别凭中文问题猜。用 `.copy()` 存筛选后的 DataFrame，避免链式赋值。
- pandas_query 里文件固定叫 `df`；execute_python 里用 schema 标注的 `df_xxx`。
- 不要运行只赋值不输出的静默代码；不要把 `df.drop(inplace=True)`、`list.sort()` 这类返回 None 的结果赋给 result。
- 嵌套 JSON 已自动展平成标准 DataFrame，直接按业务列名取数。"""


# 普通对话规范：当前对话既没有项目、也没有聊天上传的临时文件时使用。
# 此时不存在任何可读的文件/数据空间，模型应作为通用助手回答，绝不假设有文件可看、
# 不提"数据空间"、不调 list_files / read_file / search_data_space / inspect_data 等
# 文件与数据工具（它们此刻无文件可操作，调用只会返回空）。
GENERAL_MODE_GUIDANCE = """# 当前是普通对话（未挂载任何项目或文件）

- 这是一次普通对话：用户没有选择项目，也没有上传文件，因此**当前没有任何文件或数据可供读取分析**。
- 像一个通用 AI 助手那样直接回答：概念解释、方法建议、写作润色、起草文案、代码/思路讨论、学习答疑、闲聊等。
- **不要假设存在文件或数据空间**，不要说"让我看看数据空间/项目里有什么"，不要调用 list_files / read_file / search_data_space / inspect_data / pandas_query / sqlite_query 等文件与数据工具——此刻它们没有任何文件可操作。
- 如果用户的需求确实需要分析他的文件或数据，友好地提示：可以在左侧选择一个项目，或直接把文件拖到输入框上传，然后你就能基于这些内容来帮他。
- 多步骤的纯思考/写作任务仍可用 update_plan 列计划；但单轮问答、解释、闲聊不必用。"""



class AgentLoop:
    """支持 Anthropic / OpenAI 双后端的 ReAct Agent 循环"""

    def __init__(self, abort_check=None):
        # 30 步对需要逐条处理大量实体的任务（如给上千只基金分类型）偏紧，会中途
        # 撞上限自动停止且没产出 answer 块。提到 40 给这类任务更多余量；正常任务
        # 远在此之前就完成，不受影响。
        self.max_iterations = 40
        self._abort_check = abort_check or (lambda: False)

    _FILE_TYPE_LABELS = {
        "csv": "表格数据", "tsv": "表格数据", "xlsx": "Excel表格", "xls": "Excel表格",
        "json": "JSON数据", "jsonl": "JSON数据", "parquet": "列式数据", "feather": "列式数据",
        "dta": "Stata数据", "sav": "SPSS数据", "sas7bdat": "SAS数据",
        "sqlite": "SQLite数据库", "db": "SQLite数据库", "sqlite3": "SQLite数据库",
        "py": "Python代码", "r": "R代码", "sql": "SQL脚本", "ipynb": "Jupyter笔记本",
        "txt": "文本文件", "md": "Markdown文档", "log": "日志文件",
        "html": "HTML文件", "xml": "XML文件", "yaml": "配置文件", "yml": "配置文件",
        "pdf": "PDF文档", "docx": "Word文档", "pptx": "PowerPoint课件", "ppt": "PowerPoint旧版课件",
        "png": "图片", "jpg": "图片", "jpeg": "图片", "gif": "图片", "bmp": "图片", "webp": "图片",
    }

    # 进入数据模式的触发词。原则：靠「点名了数据/文件/课程资料」或「数据特有的强动词」
    # 来判断，而不是靠 总结/分析/统计/报告/趋势 这类在通用、写作、代码讨论里同样高频的
    # 泛词——那些泛词是误判主因（"总结一下这个思路""分析下这段代码"会被错判成数据任务）。
    # 数据问题在本产品里几乎总会点到具体名词：文件名、表/字段、上传内容、或课程资料。
    _DATA_CONTEXT_TRIGGERS = (
        # 数据空间 / 文件 / 表结构（强信号）
        "数据空间", "数据集", "文件", "上传", "工作表", "字段", "列名", "明细", "表格",
        "有什么数据", "有哪些数据", "有什么文件", "有哪些文件",
        # 课程资料类名词：指向「上传的资料文件」的才保留为预取信号。
        # "课程/复习/考点" 是学习意图词，纯概念问答里同样高频（"复习傅里叶变换"），
        # 留着会过度预取且轻微把模型往找文件方向带，故移除——这类问题命中与否都能
        # 正确回答，差别仅在是否多预取一层 schema，按「偏向少预取」原则去掉。
        "资料", "文档", "课件", "讲义", "笔记", "习题", "论文", "报告",
        # 逐篇/逐个处理上传内容的措辞：「逐篇讲解」「每一篇」「每个文件」几乎总指向
        # 数据空间里的文档，应进数据模式并预取文件清单。
        "逐篇", "每一篇", "每篇", "逐个", "每个文件", "每一个文件",
        # 数据特有的强动词（很少用于抽象对象）
        "查询", "筛选", "列出", "去重", "取数", "导出", "图表", "排名",
        # 明确指向上传内容的指代
        "这份", "这个文件", "这些文件", "该文件", "上述文件",
        # 文件类型 / 数据术语（英文，强信号）
        "dataset", "csv", "json", "jsonl", "xlsx", "excel", "sqlite",
        "schema", "dataframe", "数据库",
    )

    # 强制走通用模式的覆盖词：即使命中了某个触发词，只要问题明显是概念/方法/代码/架构讨论，
    # 就不注入数据上下文。命中这里 → 直接通用。
    _GENERAL_CONTEXT_HINTS = (
        "怎么设计", "如何设计", "架构", "提示词", "system prompt", "prompt", "codex",
        "claude code", "agent设计", "为什么感觉", "是否有强调", "需要调整",
        "什么是", "是什么", "怎么理解", "如何理解", "什么意思", "原理是",
        "有什么区别", "优缺点", "利弊", "这段代码", "代码逻辑", "怎么实现", "如何实现",
    )

    @classmethod
    def _should_include_data_context(cls, user_message: str, data_space_id: uuid.UUID | None) -> bool:
        """判断本轮是否需要把完整数据空间/schema 注入模型上下文。

        Codex/Claude Code 类 agent 的提示词是「通用核心 + 按需注入项目/工具上下文」。
        这里也采用同样思路：选了数据空间不等于每个问题都要走数据分析模式。
        """
        if not data_space_id:
            return False
        text = (user_message or "").strip().lower()
        if not text:
            return False
        if any(hint in text for hint in cls._GENERAL_CONTEXT_HINTS):
            return False
        return any(trigger in text for trigger in cls._DATA_CONTEXT_TRIGGERS)

    async def _get_selected_space_notice(self, data_space_id: uuid.UUID | None, user_id: uuid.UUID) -> str:
        """给通用模式一份轻量数据空间上下文。

        通用助手应该知道当前数据空间存在以及大致包含什么，但不应该在普通问题里
        被完整文件清单、schema、样本值和列画像带偏。
        """
        if not data_space_id:
            return "未选择数据空间。用户可以进行通用对话。"
        try:
            async with get_session_factory()() as db:
                result = await db.execute(
                    select(DataSpace).where(DataSpace.id == data_space_id, DataSpace.user_id == user_id)
                )
                space = result.scalar_one_or_none()
                if space:
                    file_result = await db.execute(
                        select(File)
                        .join(DataSpaceFile, DataSpaceFile.file_id == File.id)
                        .where(DataSpaceFile.data_space_id == data_space_id)
                    )
                    files = file_result.scalars().all()
                    from collections import Counter

                    label_counts: Counter = Counter(
                        self._FILE_TYPE_LABELS.get(f.file_type, f.file_type) for f in files
                    )
                    type_summary = ", ".join(
                        f"{cnt} 个 {label}" for label, cnt in label_counts.most_common()
                    ) or "空"

                    # 一行式数据文件索引（只列文件名，几十 token）：让模型即使在通用模式下
                    # 也知道有哪些可直接分析的结构化数据存在，需要时自己用 inspect_data /
                    # read_file 拉取详细 schema，而不必把列级细节预注入进来。
                    DATA_EXTS = {
                        "csv", "tsv", "xlsx", "xls", "json", "jsonl", "parquet",
                        "feather", "dta", "sav", "sas7bdat", "sqlite", "db", "sqlite3",
                    }
                    data_files = [f for f in files if f.file_type in DATA_EXTS]
                    index_line = ""
                    if data_files:
                        names = "、".join(f.filename for f in data_files[:15])
                        more = f" 等 {len(data_files)} 个" if len(data_files) > 15 else ""
                        index_line = f"可直接分析的数据文件：{names}{more}。\n"

                    # 文档类文件名（PDF/Word/PPT 等）也列出来：用户常把论文、报告、讲义传进来，
                    # 让模型即使在通用模式下也知道这些文档叫什么，要讲解时能直接 read_file，
                    # 不必先猜文件名或用 search 去凑。只列文件名，几十 token。
                    DOC_EXTS = {"pdf", "docx", "pptx", "ppt", "md", "txt"}
                    doc_files = [f for f in files if f.file_type in DOC_EXTS]
                    doc_line = ""
                    if doc_files:
                        dnames = "、".join(f.filename for f in doc_files[:15])
                        dmore = f" 等 {len(doc_files)} 个" if len(doc_files) > 15 else ""
                        doc_line = f"文档文件：{dnames}{dmore}。\n"

                    # knowledge.md 存在性提示（不注入全文，只标存在）
                    knowledge_note = ""
                    if any(f.filename.lower() == "knowledge.md" for f in files):
                        knowledge_note = "本空间含 knowledge.md（领域知识/口径说明），需要时用 read_file 读取。\n"

                    return (
                        f"当前已选择数据空间: {space.name}\n"
                        f"轻量概览: 共 {len(files)} 个文件；按类型构成：{type_summary}。\n"
                        f"{index_line}"
                        f"{doc_line}"
                        f"{knowledge_note}"
                        "本轮问题看起来不依赖上传内容；你可以知道这些上下文存在，但除非用户明确要求读取或分析该空间，不要展开 schema、调用数据工具或围绕 CSV/JSON/表格改写问题。需要时再用 list_files / inspect_data / read_file / search_data_space 按需拉取。"
                    )
        except Exception as e:
            logger.warning("selected space notice failed: %s", e)
        return "当前已选择数据空间，但本轮问题看起来不依赖上传内容；知道数据空间存在即可，不要主动展开 schema 或调用数据工具。"

    async def _get_data_space_info(self, data_space_id: uuid.UUID | None, user_id: uuid.UUID) -> str:
        """获取数据空间的上下文信息"""
        if not data_space_id:
            return "未选择数据空间。用户可以进行通用对话。"

        async with get_session_factory()() as db:
            result = await db.execute(
                select(DataSpace).where(DataSpace.id == data_space_id, DataSpace.user_id == user_id)
            )
            space = result.scalar_one_or_none()
            if not space:
                return "数据空间不存在"

            file_result = await db.execute(
                select(File)
                .join(DataSpaceFile, DataSpaceFile.file_id == File.id)
                .where(DataSpaceFile.data_space_id == data_space_id)
            )
            files = file_result.scalars().all()

            def _format_size(n: int) -> str:
                if n > 1024 * 1024:
                    return f"{n / 1024 / 1024:.1f}MB"
                return f"{n / 1024:.0f}KB"

            from collections import Counter

            def _summarize_by_label(file_list: list) -> str:
                """按"显示标签"聚合计数（png/jpg/gif 都算"图片"，yaml/yml 都算"配置文件"），
                避免出现"36 个 图片, 12 个 图片"这种按扩展名拆开的重复项。"""
                label_counts: Counter = Counter()
                for f in file_list:
                    label_counts[self._FILE_TYPE_LABELS.get(f.file_type, f.file_type)] += 1
                return ", ".join(f"{cnt} 个 {label}" for label, cnt in label_counts.most_common())

            # 数据型文件（真正可分析的）。csv/excel/数据库等是明确的数据；json/jsonl 比较
            # 含糊（可能是数据，也可能是 package.json 这类项目配置），所以排在明确数据之后。
            CORE_DATA_EXTS = {"csv", "tsv", "xlsx", "xls", "parquet", "feather", "dta", "sav", "sas7bdat", "sqlite", "db", "sqlite3"}
            JSON_EXTS = {"json", "jsonl"}
            DATA_EXTS = CORE_DATA_EXTS | JSON_EXTS
            data_files = [f for f in files if f.file_type in DATA_EXTS]
            other_files = [f for f in files if f.file_type not in DATA_EXTS]
            # 明确的数据文件排在前，json 类排后
            data_files.sort(key=lambda f: 0 if f.file_type in CORE_DATA_EXTS else 1)

            # 文件数较少时：直接全量列出（保持原行为）
            if len(files) <= 30:
                file_list = "\n".join(
                    f"  - {f.filename} [{self._FILE_TYPE_LABELS.get(f.file_type, f.file_type)}] ({_format_size(f.file_size)})"
                    for f in files
                )
                return f"""数据空间名称: {space.name}
描述: {space.description or '无'}
共 {len(files)} 个文件:
{file_list or '  (空)'}"""

            # 文件很多（如上传了整个代码仓库）：给出按类型的完整构成 + 重点列出数据文件，
            # 避免上千行文件名挤爆上下文，也避免 Agent 误以为"只有几个文件"。
            type_summary = _summarize_by_label(files)

            data_list = "\n".join(
                f"  - {f.filename} [{self._FILE_TYPE_LABELS.get(f.file_type, f.file_type)}] ({_format_size(f.file_size)})"
                for f in data_files[:40]
            ) or "  (无结构化数据文件)"
            data_more = f"\n  ...（还有 {len(data_files) - 40} 个数据/JSON 文件）" if len(data_files) > 40 else ""

            # 非数据文件只给出按类型计数，必要时 Agent 可用工具进一步查看
            other_line = _summarize_by_label(other_files)

            return f"""数据空间名称: {space.name}
描述: {space.description or '无'}
共 {len(files)} 个文件。按类型构成：{type_summary}

可分析的数据文件（{len(data_files)} 个，CSV/Excel/数据库等在前，JSON 类在后——注意 package.json/tsconfig.json 等多为项目配置而非业务数据）：
{data_list}{data_more}

其余 {len(other_files)} 个文件（代码/文档/图片/配置等，需要时可用 read_file 查看）：{other_line or '无'}"""

    async def _rank_files_by_relevance(self, user_message: str, data_space_id: uuid.UUID,
                                       files: list) -> dict[str, float] | None:
        """按用户问题给文件打相关性分（0~1）。复用已有的混合检索：把块级命中
        聚合成文件级分数（同一文件取最高分 + 命中数轻微加权），叠加文件名/列名的
        字面匹配。返回 {file_id: score}；检索不可用或问题为空时返回 None（调用方退回静态策略）。
        """
        q = (user_message or "").strip()
        if not q or not files:
            return None
        scores: dict[str, float] = {}
        # 1) 向量/BM25 混合检索（块级 → 文件级聚合）
        try:
            from app.services.retrieval import get_retrieval_service
            import asyncio as _asyncio
            svc = get_retrieval_service(str(data_space_id))
            results = await _asyncio.get_event_loop().run_in_executor(
                None, lambda: svc.search(q, top_k=30)
            )
            hit_counts: dict[str, int] = {}
            for r in results or []:
                fid = (r.metadata or {}).get("file_id")
                if not fid:
                    continue
                fid = str(fid)
                scores[fid] = max(scores.get(fid, 0.0), float(getattr(r, "score", 0.0) or 0.0))
                hit_counts[fid] = hit_counts.get(fid, 0) + 1
            # 命中块越多越相关：每多一个块 +0.03，封顶 +0.15
            for fid, c in hit_counts.items():
                scores[fid] = min(1.0, scores[fid] + min(0.15, (c - 1) * 0.03))
        except Exception as e:
            logger.warning("relevance retrieval failed, falling back to filename match: %s", e)

        # 2) 文件名字面匹配（轻量、零依赖兜底，检索挂了也有效）
        try:
            from app.services.retrieval import _tokenize_filtered
            q_tokens = set(_tokenize_filtered(q))
            if q_tokens:
                for f in files:
                    name_tokens = set(_tokenize_filtered(str(f.filename)))
                    if name_tokens & q_tokens:
                        fid = str(f.id)
                        scores[fid] = min(1.0, scores.get(fid, 0.0) + 0.2)
        except Exception:
            pass

        return scores or None

    async def _build_schema_context(self, data_space_id: uuid.UUID | None, user_id: uuid.UUID,
                                    user_message: str = "") -> str:
        """预注入 schema + 质量信息。
        选文件策略：先按用户问题做相关性排序（检索 + 文件名匹配），相关文件注入详细
        schema，其余数据文件只给一行「文件名 + 行列数」清单——让模型知道它们存在、
        需要时自己 inspect_data。问题为空或检索不可用时退回静态「数据文件优先 + 前 N」。
        合并策略：已有 profile 的文件用 profile 数据，还没处理完的用实时加载兜底。"""
        if not data_space_id:
            return ""

        try:
            from app.models.data_profile import DataProfile
            from app.agent.tools import _get_space_files, _load_df, _build_dataframe_preload
            import pandas as pd
            import asyncio

            # 获取所有文件
            all_files = await _get_space_files(user_id, data_space_id)
            if not all_files:
                return ""
            _preload, df_var_by_file_id = _build_dataframe_preload(all_files)

            # 获取已完成的 profiles
            async with get_session_factory()() as db:
                result = await db.execute(
                    select(DataProfile).where(
                        DataProfile.data_space_id == data_space_id,
                    )
                )
                all_profiles = result.scalars().all()

            profile_map = {}
            for p in all_profiles:
                profile_map[str(p.file_id)] = p


            all_columns: dict[str, dict[str, set]] = {}
            MAX_SCHEMA_COLS = 30
            TABULAR_EXTS = {"csv", "tsv", "xlsx", "xls", "json", "jsonl", "parquet", "feather", "dta", "sav", "sas7bdat"}
            # 可分析的数据型扩展（含数据库），schema 预注入时优先保证这些文件入选，
            # 避免代码仓库类空间里几百个 .py/.md 把仅有的几个数据文件挤出前 N。
            DATA_EXTS = TABULAR_EXTS | {"sqlite", "db", "sqlite3"}

            # 选文件：优先按用户问题的相关性排序；问题为空/检索不可用时退回
            # 「数据文件优先」的静态排序。相关文件进详细 schema，其余只列清单。
            relevance = await self._rank_files_by_relevance(user_message, data_space_id, all_files)
            if relevance:
                # 相关性优先；同分内数据文件在前；再按相关分降序。无分的排后面。
                sorted_files = sorted(
                    all_files,
                    key=lambda f: (
                        0 if relevance.get(str(f.id), 0.0) > 0 else 1,
                        0 if f.file_type in DATA_EXTS else 1,
                        -relevance.get(str(f.id), 0.0),
                    ),
                )
            else:
                # 数据文件优先排序：数据型在前、其余在后，再截断。这样 601 文件里的 2 个 csv
                # 一定会进入 schema 预注入，而不是被前 15 个代码文件占满名额。
                sorted_files = sorted(
                    all_files,
                    key=lambda f: 0 if f.file_type in DATA_EXTS else 1,
                )
            MAX_SCHEMA_FILES = 25
            shown_ids: set[str] = set()
            preview_files = sorted_files[:MAX_SCHEMA_FILES]
            lines = [
                "## 本轮相关文件预览（非完整文件清单）\n",
                f"以下只展开最多 {MAX_SCHEMA_FILES} 个与本轮问题相关或优先的数据文件，用于快速判断可用上下文。",
                f"当前数据空间实际共有 {len(all_files)} 个文件；未在本预览展开的文件仍然存在，可按需用 read_file / search_data_space / inspect_data 查看。",
                "",
            ]

            # 遍历文件（相关/数据文件优先）
            for f in preview_files:
                fid = str(f.id)
                shown_ids.add(fid)
                profile = profile_map.get(fid)

                # 有 profile 且已就绪 → 用 profile 的丰富信息
                if profile and profile.status == "ready" and profile.profile_type == "tabular":
                    data = profile.profile_data or {}

                    df_var = df_var_by_file_id.get(str(f.id))
                    py_hint = f"  python变量={df_var}" if df_var else ""
                    sheet_profiles = data.get("sheets") if data.get("workbook") else None
                    if sheet_profiles:
                        lines.append(f"### {f.filename}  Excel工作簿 sheets={data.get('sheet_count', len(sheet_profiles))}{py_hint}")
                        profiles_to_render = sheet_profiles[:8]
                    else:
                        lines.append(f"### {f.filename}  rows={data.get('row_count', '?')}  cols={data.get('column_count', '?')}{py_hint}")
                        profiles_to_render = [data]

                    for sheet_data in profiles_to_render:
                        columns = sheet_data.get("columns", [])
                        sheet_name = sheet_data.get("sheet_name")
                        indent = "    "
                        source_label = f"{f.filename}[{sheet_name}]" if sheet_name else f.filename
                        if sheet_name:
                            lines.append(f"    - 工作表 {sheet_name}: rows={sheet_data.get('row_count', '?')} cols={sheet_data.get('column_count', '?')}")
                            indent = "      "
                        for c in columns[:MAX_SCHEMA_COLS]:
                            name = c.get("name", "?")
                            dtype = c.get("dtype", "?")
                            unique = c.get("unique_count", "?")
                            null_pct = c.get("null_pct", 0)
                            samples = c.get("sample_values", [])[:3]
                            samples_str = ", ".join(str(s)[:20] for s in samples)
                            extra = ""
                            if null_pct > 5:
                                extra += f" null={null_pct}%"
                            stats = c.get("stats")
                            if stats and stats.get("mean") is not None:
                                extra += f" mean={stats['mean']}"
                            top = c.get("top_values")
                            if top:
                                extra += f" top=[{', '.join(f'{k}:{v}' for k,v in list(top.items())[:3])}]"
                            lines.append(f"{indent}- {name} ({dtype}) unique={unique} ex=[{samples_str}]{extra}")
                            if name not in all_columns:
                                all_columns[name] = {}
                            all_columns[name][source_label] = set(str(s) for s in samples)

                        if len(columns) > MAX_SCHEMA_COLS:
                            lines.append(f"{indent}...（还有 {len(columns) - MAX_SCHEMA_COLS} 列）")

                        quality = sheet_data.get("quality", {})
                        qp = []
                        if quality.get("duplicate_pct", 0) > 1: qp.append(f"重复率{quality['duplicate_pct']}%")
                        if quality.get("complete_pct", 100) < 95: qp.append(f"完整率{quality['complete_pct']}%")
                        if quality.get("outlier_columns"): qp.append(f"{len(quality['outlier_columns'])}列有异常值")
                        if quality.get("type_suggestions"): qp.append(f"{len(quality['type_suggestions'])}列可转类型")
                        if qp:
                            lines.append(f"{indent}⚠️ {', '.join(qp)}")
                    if sheet_profiles and len(sheet_profiles) > 8:
                        lines.append(f"    ...（还有 {len(sheet_profiles) - 8} 个工作表）")
                    lines.append("")

                elif profile and profile.status == "ready" and profile.profile_type in ("text", "document"):
                    data = profile.profile_data or {}
                    chars = data.get("char_count", 0)
                    line_count = data.get("line_count", 0)
                    preview = data.get("preview", "")[:200]
                    type_label = self._FILE_TYPE_LABELS.get(f.file_type, f.file_type)
                    size_info = f"{chars}字" + (f", {line_count}行" if line_count else "")
                    lines.append(f"### {f.filename} ({type_label}, {size_info})")
                    lines.append(f"    内容预览: {preview}")
                    lines.append("")

                elif profile and profile.status == "ready" and profile.profile_type == "database":
                    data = profile.profile_data or {}
                    tables = data.get("tables", [])
                    lines.append(f"### {f.filename} (数据库, {len(tables)}张表)")
                    for t in tables[:5]:
                        cols = ", ".join(c["name"] for c in t.get("columns", [])[:8])
                        lines.append(f"    - {t['name']} ({t.get('row_count', '?')}行): {cols}")
                    lines.append("")

                elif profile and profile.status == "ready" and profile.profile_type == "image":
                    data = profile.profile_data or {}
                    type_label = self._FILE_TYPE_LABELS.get(f.file_type, f.file_type)
                    lines.append(f"### {f.filename} ({type_label})")
                    if data.get("ocr_applied") and data.get("preview"):
                        lines.append(f"    OCR 识别内容预览: {data['preview'][:200]}")
                    else:
                        dims = f"{data.get('width', '?')}x{data.get('height', '?')}"
                        lines.append(f"    尺寸 {dims}，暂无可提取文本（OCR 未配置或处理中）")
                    lines.append("")


                elif profile and profile.status == "ready" and profile.profile_type == "video":
                    data = profile.profile_data or {}
                    type_label = self._FILE_TYPE_LABELS.get(f.file_type, f.file_type)
                    lines.append(f"### {f.filename} ({type_label})")
                    if data.get("ocr_applied") and data.get("ocr_text"):
                        # 视频是幻灯片型，OCR 文本往往定义了本题的筛选口径/准入线/分组维度。
                        # 放入前 4000 字；若更长，提示 Agent 用 read_file 读取完整内容。
                        ocr = data["ocr_text"]
                        lines.append("    视频逐帧 OCR 文本（定义了本题的筛选条件/统计口径/分组维度，必须据此理解问题，不要说无法提取视频内容）：")
                        lines.append("    " + ocr[:4000].replace("\n", "\n    "))
                        if len(ocr) > 4000:
                            lines.append(f"    （视频文本较长，共 {len(ocr)} 字，如需完整内容用 read_file 读取 {f.filename}）")
                    elif data.get("preview"):
                        lines.append(f"    OCR 识别内容预览: {data['preview'][:200]}")
                    else:
                        lines.append("    暂无可提取文本（OCR 未配置或处理中）")
                    lines.append("")


                elif f.file_type in TABULAR_EXTS:
                    # 没有 profile 或正在处理 → 实时加载基础 schema（线程池避免阻塞）
                    fp = Path(settings.storage_root) / f.storage_path
                    if fp.exists():
                        try:
                            loop = asyncio.get_event_loop()
                            df = await loop.run_in_executor(None, _load_df, fp, f.file_type)
                            df_var = df_var_by_file_id.get(str(f.id))
                            py_hint = f"  python变量={df_var}" if df_var else ""
                            lines.append(f"### {f.filename}  rows={len(df)}  cols={len(df.columns)}{py_hint}")
                            for col in list(df.columns)[:MAX_SCHEMA_COLS]:
                                dtype = str(df[col].dtype)
                                nn = df[col].dropna()
                                # list/dict 单元格（LLM 训练数据类 json/jsonl 常见）不可哈希，
                                # nunique()/unique() 会抛 unhashable type，整块掉进 except 被误
                                # 标「加载中」。统一字符串化后再统计/取样，保证 schema 正常预注入。
                                str_vals = nn.map(
                                    lambda v: json.dumps(v, ensure_ascii=False)
                                    if isinstance(v, (list, dict)) else str(v)
                                )
                                try:
                                    unique = int(str_vals.nunique())
                                except Exception:
                                    unique = "?"
                                samples = ", ".join(s[:20] for s in str_vals.unique()[:3])
                                lines.append(f"    - {col} ({dtype}) unique={unique} ex=[{samples}]")
                                if col not in all_columns:
                                    all_columns[col] = {}
                                all_columns[col][f.filename] = set(str_vals.unique()[:50].tolist())
                            lines.append("")
                        except Exception:
                            lines.append(f"### {f.filename} ({f.file_type}, 加载中...)")
                            lines.append("")
                else:
                    # 非表格文件且无 profile — 尽量给出有意义的描述
                    type_label = self._FILE_TYPE_LABELS.get(f.file_type, f.file_type)
                    def _fmt_size(n: int) -> str:
                        return f"{n/1024/1024:.1f}MB" if n > 1024*1024 else f"{n/1024:.0f}KB"
                    lines.append(f"### {f.filename} ({type_label}, {_fmt_size(f.file_size)})")
                    # 尝试快速读取文件开头给 Agent 更多上下文
                    if f.file_type in ("txt", "md", "py", "sql", "r", "html", "xml", "yaml", "yml", "log", "ipynb"):
                        try:
                            fp = Path(settings.storage_root) / f.storage_path
                            if fp.exists():
                                raw = fp.read_text(encoding="utf-8", errors="ignore")[:300]
                                lines.append(f"    内容预览: {raw}")
                        except Exception:
                            pass
                    elif f.file_type in ("pdf", "docx", "pptx"):
                        try:
                            from app.services.document_text import extract_document_text
                            fp = Path(settings.storage_root) / f.storage_path
                            if fp.exists():
                                raw = extract_document_text(fp, f.file_type)[:300]
                                if raw:
                                    lines.append(f"    内容预览: {raw}")
                        except Exception:
                            pass
                    elif f.file_type == "ppt":
                        lines.append("    旧版 .ppt 暂不支持抽取文本，请转换为 .pptx 后上传")
                    lines.append("")

            # 其余数据文件清单：没进详细 schema 的数据文件，只给一行「文件名 + 行列数」，
            # 几乎不耗 token，但让模型知道它们存在、需要时可自己 inspect_data / read_file。
            remaining = [f for f in all_files
                         if str(f.id) not in shown_ids and f.file_type in DATA_EXTS]
            if remaining:
                lines.append("")
                lines.append(f"### 其余数据文件（共 {len(remaining)} 个，未展开详细结构；如与问题相关可用 inspect_data 查看）")
                for f in remaining[:60]:
                    p = profile_map.get(str(f.id))
                    dims = ""
                    if p and p.status == "ready" and isinstance(p.profile_data, dict):
                        rc = p.profile_data.get("row_count")
                        cc = p.profile_data.get("column_count")
                        if rc is not None or cc is not None:
                            dims = f"  rows={rc or '?'} cols={cc or '?'}"
                    lines.append(f"- {f.filename}{dims}")
                if len(remaining) > 60:
                    lines.append(f"- …（还有 {len(remaining) - 60} 个数据文件）")

            remaining_all = [f for f in all_files if str(f.id) not in shown_ids]
            if remaining_all:
                from collections import Counter
                label_counts: Counter = Counter(
                    self._FILE_TYPE_LABELS.get(f.file_type, f.file_type) for f in remaining_all
                )
                type_summary = ", ".join(
                    f"{cnt} 个 {label}" for label, cnt in label_counts.most_common()
                )
                lines.append("")
                lines.append("### 未展开文件说明")
                lines.append(
                    f"还有 {len(remaining_all)} 个文件未在本轮预览展开；类型构成：{type_summary or '无'}。"
                )
                lines.append("这些文件不是缺失，只是未预注入详细内容；如果用户问题涉及它们，继续用文件工具查看。")

            # JOIN 检测
            joins = self._detect_joins_for_schema(all_columns)
            if joins:
                lines.append("### 潜在 JOIN 关系")
                lines.extend(joins)

            return "\n".join(lines)
        except Exception as e:
            logger.warning("schema context build failed, returning empty: %s", e)
            return ""

    def _detect_joins_for_schema(self, all_columns: dict[str, dict[str, set]]) -> list[str]:
        """增强的 join 检测（来自 KDD-CUP）"""
        suggestions = []
        col_names = list(all_columns.keys())

        for col_name, file_vals in all_columns.items():
            if len(file_vals) < 2:
                continue
            files = list(file_vals.keys())
            for i in range(len(files)):
                for j in range(i + 1, len(files)):
                    vals_a, vals_b = file_vals[files[i]], file_vals[files[j]]
                    if not vals_a or not vals_b:
                        continue
                    intersection = vals_a & vals_b
                    union = vals_a | vals_b
                    jaccard = len(intersection) / len(union) if union else 0
                    if jaccard > 0.05 and len(intersection) > 1:
                        tags = ["name_match"]
                        if self._is_id_like(col_name):
                            tags.append("id_like")
                        suggestions.append(
                            f"  {files[i]}:{col_name} <-> {files[j]}:{col_name}  [{', '.join(tags)}]  overlap={jaccard:.2f}"
                        )

        for col_a in col_names:
            if not self._is_id_like(col_a):
                continue
            base_a = col_a.lower().replace("_id", "").replace("id", "").strip("_")
            for col_b in col_names:
                if col_a == col_b:
                    continue
                base_b = col_b.lower().replace("_id", "").replace("id", "").strip("_")
                if base_a and base_a == base_b and col_a in all_columns and col_b in all_columns:
                    for fa in all_columns[col_a]:
                        for fb in all_columns[col_b]:
                            if fa != fb:
                                suggestions.append(f"  {fa}:{col_a} <-> {fb}:{col_b}  [id_pattern]")

        return suggestions[:15]

    @staticmethod
    def _is_id_like(name: str) -> bool:
        n = name.lower()
        return n.endswith("_id") or n == "id" or (n.endswith("id") and len(n) > 2 and n[-3].isalpha())

    async def _get_knowledge_context(self, data_space_id: uuid.UUID | None, user_id: uuid.UUID) -> str:
        """如果数据空间中有 knowledge.md，自动注入"""
        if not data_space_id:
            return ""
        try:
            from app.agent.tools import _get_file_path
            for name in ("knowledge.md", "Knowledge.md", "KNOWLEDGE.md"):
                path = await _get_file_path(name, user_id, data_space_id)
                if path and path.exists():
                    content = path.read_text(encoding="utf-8", errors="ignore")
                    if content.strip():
                        return f"## 领域知识（来自 {name}）\n\n{content[:8000]}"
        except Exception:
            pass
        return ""

    async def _get_conversation_history(self, conversation_id: uuid.UUID) -> list[dict]:
        """获取对话历史，重建为 canonical 消息序列（见 context.py）。

        关键：过去每个 assistant 回合若存了完整工具 I/O（Message.tool_results
        列的 canonical 子序列），就原样回放——这样 Agent 续对话时能看到自己
        上一轮真正查到的数据，而不是只剩一行「调用了某工具」的摘要。没有存
        canonical（旧消息/纯文本回答）时退回用 content 文本。
        """
        async with get_session_factory()() as db:
            result = await db.execute(
                select(Message)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.created_at)
            )
            messages = result.scalars().all()

            canonical: list[dict] = []
            for msg in messages:
                if msg.role == "user":
                    canonical.append({"role": "user", "content": msg.content or ""})
                elif msg.role == "assistant":
                    stored = msg.tool_results if isinstance(msg.tool_results, dict) else None
                    sub = stored.get("canonical") if stored else None
                    if sub and isinstance(sub, list):
                        # 回放完整 canonical 子序列（含工具调用与结果，配对完整）
                        canonical.extend(sub)
                    elif msg.content:
                        canonical.append({
                            "role": "assistant",
                            "content": msg.content,
                            "tool_calls": [],
                        })

            return canonical


    async def _check_balance(self, user_id: uuid.UUID) -> int:
        async with get_session_factory()() as db:
            result = await db.execute(
                select(CreditAccount).where(CreditAccount.user_id == user_id)
            )
            account = result.scalar_one_or_none()
            return account.balance if account else 0

    async def _deduct_credits(self, user_id: uuid.UUID, credits: int, model_name: str) -> None:
        async with get_session_factory()() as db:
            # 使用 FOR UPDATE 加行级锁防止并发透支
            result = await db.execute(
                select(CreditAccount)
                .where(CreditAccount.user_id == user_id)
                .with_for_update()
            )
            account = result.scalar_one_or_none()
            if not account:
                return

            account.balance = max(0, account.balance - credits)
            transaction = CreditTransaction(
                user_id=user_id,
                amount=-credits,
                balance_after=account.balance,
                transaction_type="usage",
                description=f"对话消耗 (模型: {model_name})",
            )
            db.add(transaction)
            await db.commit()

    def _tools_to_anthropic_format(self) -> list[dict]:
        """将工具定义转为 Anthropic 格式"""
        openai_tools = get_tool_definitions()
        anthropic_tools = []
        for t in openai_tools:
            func = t["function"]
            anthropic_tools.append({
                "name": func["name"],
                "description": func["description"],
                "input_schema": func["parameters"],
            })
        return anthropic_tools

    async def _resolve_model_config(self, model_id: str, user_id: uuid.UUID) -> dict:
        """解析模型配置：根据用户偏好选择平台模型或用户自己的 API"""
        from app.core.redis_client import get_redis
        from app.models.user_api_key import UserApiKey

        # 检查用户偏好：own_api 模式时用用户自己的 API
        try:
            redis = await get_redis()
            api_mode = await redis.get(f"user_pref:{user_id}:api_mode")
        except Exception:
            api_mode = None

        if api_mode == "own_api":
            async with get_session_factory()() as db:
                result = await db.execute(
                    select(UserApiKey).where(UserApiKey.user_id == user_id, UserApiKey.is_active == True)
                )
                key = result.scalar_one_or_none()
                if key:
                    # 优先用映射表的模型名，没有映射则直接用平台模型名
                    model_name = (key.model_mappings or {}).get(model_id) if model_id else None
                    if not model_name and model_id:
                        from app.models.llm_model import LLMModel
                        m = await db.execute(select(LLMModel).where(LLMModel.id == model_id))
                        platform_model = m.scalar_one_or_none()
                        model_name = platform_model.model_name if platform_model else model_id
                    return {
                        "provider": "openai",
                        "api_key": key.api_key_encrypted,
                        "model_name": model_name or "default",
                        "api_base": key.api_base_url,
                        "charge_credits": False,
                        "multiplier": 0,
                    }

        # 查找平台模型配置
        if model_id:
            async with get_session_factory()() as db:
                from app.models.llm_model import LLMModel
                result = await db.execute(
                    select(LLMModel).where(LLMModel.id == model_id, LLMModel.is_active == True)
                )
                model = result.scalar_one_or_none()
                if model:
                    return {
                        "provider": model.provider,
                        "api_key": model.api_key_encrypted,
                        "model_name": model.model_name,
                        "api_base": model.api_base,
                        "charge_credits": True,
                        "multiplier": float(model.credit_multiplier),
                    }

        # 兜底：用 .env 配置
        return {
            "provider": settings.llm_backend,
            "api_key": settings.anthropic_api_key if settings.llm_backend == "anthropic" else settings.openai_api_key,
            "model_name": settings.anthropic_model if settings.llm_backend == "anthropic" else settings.openai_model,
            "api_base": settings.openai_api_base if settings.llm_backend == "openai" else None,
            "charge_credits": True,
            "multiplier": 1.0,
        }

    async def _summarize_history(self, rendered: str, client, backend: str,
                                 model_name: str, system_blocks) -> str:
        """对较早的对话内容做一次 LLM 总结，用于混合 compaction 兜底。

        失败时抛异常由调用方退化为纯窗口策略，不阻断主对话。
        """
        instruction = (
            "你是对话压缩器。请把下面这段较早的数据分析对话压成简洁但信息完整的中文摘要，"
            "保留：用户的目标与约束、已确认的关键数据结论与具体数值、用过哪些数据文件/表、"
            "已知的口径与假设、尚未完成的部分。不要复述工具调用细节，不要编造。\n\n"
            f"=== 待压缩内容 ===\n{rendered}"
        )
        if backend == "anthropic":
            resp = await client.messages.create(
                model=model_name,
                max_tokens=1024,
                messages=[{"role": "user", "content": instruction}],
            )
            parts = [b.text for b in resp.content if getattr(b, "type", None) == "text"]
            return "".join(parts).strip()
        else:
            resp = await client.chat.completions.create(
                model=model_name,
                messages=[{"role": "user", "content": instruction}],
                max_tokens=1024,
                stream=False,
            )
            return (resp.choices[0].message.content or "").strip()

    async def run(
        self,
        conversation_id: uuid.UUID,
        user_id: uuid.UUID,
        data_space_id: uuid.UUID | None,
        model_id: str,
        user_message: str,
        is_admin: bool = False,
        extra_space_ids: list | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """执行 Agent 循环，流式返回事件"""
        # #12 多数据空间：把本轮活跃空间集合注入 contextvar，供工具层跨空间检索/查表。
        # 主空间 + 额外绑定空间；为空集合时工具退化为单主空间，行为不变。
        from app.agent.tools import set_active_space_ids
        _all_spaces = []
        if data_space_id:
            _all_spaces.append(data_space_id)
        for s in (extra_space_ids or []):
            if s and s not in _all_spaces:
                _all_spaces.append(s)
        set_active_space_ids(_all_spaces)
        # 解析模型配置（平台模型 or 用户自带）
        model_config = await self._resolve_model_config(model_id, user_id)
        charge_credits = model_config["charge_credits"] and not is_admin
        credit_multiplier = model_config["multiplier"]
        model_name = model_config["model_name"]

        # 复用 SDK client（按 provider + api_key 缓存）
        try:
            api_key = decrypt_api_key(model_config["api_key"])
        except ValueError:
            yield {"type": "error", "message": "模型 API 密钥解密失败，请在管理后台重新配置模型或在设置中重新配置 API Key。"}
            return
        active_backend = model_config["provider"]
        client = _get_client(active_backend, api_key, model_config.get("api_base"))

        if charge_credits:
            balance = await self._check_balance(user_id)
            if balance <= 0:
                yield {"type": "error", "message": "额度不足。每日免费额度会在次日自动发放，你也可以在「额度中心」查看详情，或在「设置」中配置自己的 API Key 免费使用。"}
                return

        # 构建系统提示。有项目或聊天上传的临时文件时，注入数据工作规范（DATA_MODE_GUIDANCE）；
        # 普通对话（_all_spaces 为空：既没项目也没临时文件）则换成通用助手规范，避免模型
        # 假设存在文件、张口就"看看数据空间里有什么"。判定用本轮活跃空间集合是否为空，
        # 临时文件已通过 extra_space_ids 计入 _all_spaces。
        has_any_space = len(_all_spaces) > 0
        data_mode_guidance = DATA_MODE_GUIDANCE if has_any_space else GENERAL_MODE_GUIDANCE
        prefetch_data_detail = self._should_include_data_context(user_message, data_space_id)
        if prefetch_data_detail:
            data_space_info = await self._get_data_space_info(data_space_id, user_id)
            schema_context = await self._build_schema_context(data_space_id, user_id, user_message)
            knowledge_context = await self._get_knowledge_context(data_space_id, user_id)
        else:
            # 通用问答：只给轻量数据空间索引（文件总数/类型构成 + 一行式清单），
            # 不预注入列级 schema、样本值、knowledge 全文——这些留给模型按需用工具拉。
            data_space_info = await self._get_selected_space_notice(data_space_id, user_id)
            schema_context = ""
            knowledge_context = ""

        memory_context = ""
        try:
            from app.services.memory import recall
            memories = await recall(user_id, user_message, data_space_id=data_space_id)
            if memories:
                memory_lines = [f"- [{m['scope']}/{m['kind']}] {m['content']}" for m in memories]
                memory_context = "## 相关记忆\n" + "\n".join(memory_lines)
        except Exception as e:
            logger.warning("memory recall failed, continuing without memory: %s", e)

        system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
            data_space_info=data_space_info,
            schema_context=schema_context,
            knowledge_context=knowledge_context,
            memory_context=memory_context,
            data_mode_guidance=data_mode_guidance,
        )

        # 构建 system 块（支持 prompt caching）
        system_blocks = []
        if settings.enable_prompt_caching:
            system_blocks = [
                {"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}
            ]
        else:
            system_blocks = system_prompt

        # 加载 canonical 历史 + 本次 user 消息，做混合 compaction，再序列化为
        # provider 格式作为循环初始 messages。turn_canonical 并行累积「本回合」
        # 新产生的 canonical 子序列（assistant + 工具结果），随 done 事件回传给
        # 路由层持久化到 Message.tool_results，下一轮即可完整回放。
        from app.agent import context as ctx

        canonical_history = await self._get_conversation_history(conversation_id)
        canonical_all = [*canonical_history, {"role": "user", "content": user_message}]

        async def _summarize(text: str) -> str:
            return await self._summarize_history(
                text, client, active_backend, model_name, system_blocks
            )

        canonical_all = await ctx.compact_messages(
            canonical_all,
            budget=settings.context_token_budget,
            min_recent=settings.context_min_recent_messages,
            enable_summary=settings.context_enable_summary_fallback,
            summarize=_summarize,
        )

        # 压缩后健康校验（对齐 claude code 的压缩后探针，适配本架构）：确认序列结构
        # 合法、不会让下一步 API 调用因孤立 tool_results 而 400。畸形则安全降级到
        # 纯窗口策略（不加摘要、不重排，绝不切断配对）。
        ok, reason = ctx.validate_sequence(canonical_all)
        if not ok:
            canonical_all = await ctx.compact_messages(
                [*canonical_history, {"role": "user", "content": user_message}],
                budget=settings.context_token_budget,
                min_recent=settings.context_min_recent_messages,
                enable_summary=False,
                summarize=None,
            )

        if active_backend == "anthropic":
            messages = ctx.to_anthropic(canonical_all)
        else:
            messages = ctx.to_openai(canonical_all)

        turn_canonical: list[dict] = []

        tools = self._tools_to_anthropic_format()
        total_usage = {"input_tokens": 0, "output_tokens": 0}
        tool_calls_log = []
        consecutive_errors = 0
        # 当前任务计划（由 update_plan 维护），供任务状态停止条件使用
        current_plan: list[dict] = []

        # 停止条件基于「任务状态」而非步数（对齐 codex / claude code）：
        # 模型不再请求工具即视为一个 turn 完成。若此时计划仍有未完成步骤，
        # 注入一次简短提示让它继续；提示有上限，绝不靠步数硬刹车。
        # max_iterations 仅作为防跑飞的安全上限。
        plan_nudges = 0
        MAX_PLAN_NUDGES = 1
        # 撞上限收尾（P1-#3）：跑到最后一步时，不再让模型继续调工具，而是注入一次
        # 「用已有信息给最终答复」的提示并再采样一轮，避免大任务直接烂尾、token 白花。
        final_forced = False
        # 取数结果自检（对齐 codex completion audit）：本轮是否调用过「数据工具」
        # （读/查/算，排除 update_plan / save_memory 等元工具），以及是否已自检过一次。
        data_tool_used = False
        self_check_done = False
        # 反向判定：除了「元工具」（不产生需核实结果），其余工具都算「数据/信息工具」，
        # 用过就该在收尾前自检。这样新增工具（如 download_to_space / web_search）自动纳入，
        # 不会像写死白名单那样漏掉。
        _META_TOOLS = {"update_plan", "save_memory"}

        # 用显式计数的 while 循环：只有「真正向模型采样的轮次」才消耗配额。
        # plan_nudge / self_check 这类注入轮通过 continue 回到顶部，但不计入 iteration，
        # 保证多步任务始终有完整 max_iterations 步用于实际工具调用。
        iteration = 0
        while iteration < self.max_iterations:
            iteration += 1
            if self._abort_check():
                # 中断不是「作废」：把已产出的 canonical 正常收尾持久化，
                # 下一轮用户追加消息时即可在完整上下文上继续（可续中断）。
                yield {"type": "text", "delta": "\n\n[已暂停。你可以补充说明后让我接着做。]"}
                credits_used = max(1, self._calculate_credits(total_usage, credit_multiplier)) if charge_credits else 0
                if charge_credits:
                    await self._deduct_credits(user_id, credits_used, model_name)
                yield {
                    "type": "done",
                    "usage": total_usage,
                    "credits_used": credits_used,
                    "tool_calls_log": tool_calls_log,
                    "canonical": turn_canonical,
                    "interrupted": True,
                }
                return

            try:
                full_text = ""
                reasoning_text = ""  # 推理模型的思考内容（DeepSeek 等需回传）
                tool_uses = []
                # 本轮采样的重试控制：仅当「尚未向用户流出任何内容」时才重试整轮采样，
                # 避免重复输出。一旦已经流出文本/工具增量，中途断流走优雅降级（保留已产出）。
                streamed_anything = False
                attempt = 0
                # 收尾轮禁用工具，强制模型用已有信息直接作答（P1-#3）
                _pass_tools = [] if final_forced else tools
                while True:
                    try:
                        if active_backend == "anthropic":
                            # Anthropic SDK 流式调用
                            response_stream = client.messages.stream(
                                model=model_name,
                                max_tokens=settings.anthropic_max_tokens,
                                system=system_blocks,
                                messages=messages,
                                tools=_pass_tools,
                            )
                            async with response_stream as stream:
                                async for event in stream:
                                    if self._abort_check():
                                        break
                                    if event.type == "content_block_start":
                                        if event.content_block.type == "tool_use":
                                            tool_uses.append({
                                                "id": event.content_block.id,
                                                "name": event.content_block.name,
                                                "input_json": "",
                                            })
                                    elif event.type == "content_block_delta":
                                        if event.delta.type == "text_delta":
                                            full_text += event.delta.text
                                            if event.delta.text:
                                                streamed_anything = True
                                                yield {"type": "text", "delta": event.delta.text}
                                        elif event.delta.type == "input_json_delta":
                                            if tool_uses:
                                                streamed_anything = True
                                                tool_uses[-1]["input_json"] += event.delta.partial_json
                                final_message = await stream.get_final_message()
                                total_usage["input_tokens"] += final_message.usage.input_tokens
                                total_usage["output_tokens"] += final_message.usage.output_tokens

                        else:
                            # OpenAI 兼容接口流式调用
                            openai_tools = [] if final_forced else get_tool_definitions()
                            oai_messages = [{"role": "system", "content": system_blocks if isinstance(system_blocks, str) else system_blocks[0]["text"]}] + messages
                            response = await client.chat.completions.create(
                                model=model_name,
                                messages=oai_messages,
                                tools=openai_tools if openai_tools else None,
                                stream=True,
                            )
                            tool_calls_data = []
                            async for chunk in response:
                                if self._abort_check():
                                    break
                                delta = chunk.choices[0].delta if chunk.choices else None
                                if not delta:
                                    continue
                                # 处理推理模型的 reasoning_content（如 DeepSeek）
                                reasoning = getattr(delta, 'reasoning_content', None)
                                if reasoning:
                                    reasoning_text += reasoning
                                    streamed_anything = True
                                    yield {"type": "thinking", "content": reasoning}
                                if delta.content:
                                    full_text += delta.content
                                    streamed_anything = True
                                    yield {"type": "text", "delta": delta.content}
                                if delta.tool_calls:
                                    for tc in delta.tool_calls:
                                        streamed_anything = True
                                        while tc.index >= len(tool_calls_data):
                                            tool_calls_data.append({"id": "", "function": {"name": "", "arguments": ""}})
                                        if tc.id:
                                            tool_calls_data[tc.index]["id"] = tc.id
                                        if tc.function:
                                            if tc.function.name:
                                                tool_calls_data[tc.index]["function"]["name"] = tc.function.name
                                            if tc.function.arguments:
                                                tool_calls_data[tc.index]["function"]["arguments"] += tc.function.arguments
                                if hasattr(chunk, "usage") and chunk.usage:
                                    total_usage["input_tokens"] += chunk.usage.prompt_tokens or 0
                                    total_usage["output_tokens"] += chunk.usage.completion_tokens or 0
                            # 转换为统一的 tool_uses 格式（过滤掉无效的 tool_call）
                            for tc in tool_calls_data:
                                if tc["id"] and tc["function"]["name"]:
                                    tool_uses.append({
                                        "id": tc["id"],
                                        "name": tc["function"]["name"],
                                        "input_json": tc["function"]["arguments"],
                                    })
                        break  # 本轮采样成功，跳出重试循环

                    except Exception as stream_err:
                        # 已经向用户流出内容 → 不重试（重试会重复输出）。
                        # 当作优雅降级：保留已产出的 full_text，按"模型本轮结束"继续后续逻辑。
                        if streamed_anything:
                            yield {"type": "text", "delta": "\n\n[与模型的连接中断，已保留上面已生成的内容。]"}
                            tool_uses = []
                            break
                        # 尚未流出任何内容：可重试错误就退避重试，否则上抛由外层报错。
                        if attempt < settings.llm_max_retries and _is_retryable_error(stream_err):
                            attempt += 1
                            delay = settings.llm_retry_base_delay * (2 ** (attempt - 1))
                            yield {"type": "thinking", "content": f"网络波动，正在重试（第 {attempt} 次）…"}
                            await asyncio.sleep(delay)
                            full_text = ""
                            reasoning_text = ""
                            tool_uses = []
                            continue
                        raise


                # 流式过程中被中断：把已产出的半截文本并入 canonical，跳回循环顶部
                # 由统一的「暂停收尾」分支干净落盘，不执行本轮残缺的工具调用。
                if self._abort_check():
                    if full_text:
                        turn_canonical.append({
                            "role": "assistant", "content": full_text, "tool_calls": [],
                        })
                    continue

                # 没有工具调用 → 模型认为本 turn 完成。基于任务状态判断是否真的结束：
                # 若存在计划且仍有未完成步骤，注入一次简短提示让它继续；否则正式收尾。
                if not tool_uses:
                    plan_incomplete = bool(current_plan) and any(
                        s.get("status") != "completed" for s in current_plan
                    )
                    if plan_incomplete and plan_nudges < MAX_PLAN_NUDGES:
                        if full_text:
                            messages.append({"role": "assistant", "content": full_text})
                            turn_canonical.append({
                                "role": "assistant", "content": full_text, "tool_calls": [],
                            })
                        pending = [s["content"] for s in current_plan if s.get("status") != "completed"]
                        nudge = (
                            "（系统提示）你的任务计划还有未完成的步骤："
                            + "；".join(pending[:5])
                            + "。请继续执行：要么调用工具完成它们，要么如果已无法推进，"
                            "就基于现有信息给出最终答案，并用 update_plan 把计划标记为完成。"
                        )
                        messages.append({"role": "user", "content": nudge})
                        turn_canonical.append({"role": "user", "content": nudge})
                        plan_nudges += 1
                        iteration -= 1  # 注入轮不消耗工具调用配额
                        continue

                    # 取数结果自检（对齐 codex completion audit）：本轮用过数据工具、
                    # 尚未自检过、且开关开启时，注入一次有界的核对提示。只做一次，
                    # 不基于文本启发式（基于真实工具使用），不会无限循环。
                    if (settings.enable_answer_self_check and data_tool_used
                            and not self_check_done):
                        if full_text:
                            messages.append({"role": "assistant", "content": full_text})
                            turn_canonical.append({
                                "role": "assistant", "content": full_text, "tool_calls": [],
                            })
                        audit = (
                            "（系统自检，仅本轮内部使用）在给出最终答复前，请对照你上面实际拿到的"
                            "工具结果快速核对一遍：关键数字/行数/聚合口径/单位/筛选条件是否与工具输出一致？"
                            "是否有该列全/该去重/该换算却没做的地方？"
                            "如果发现不一致或遗漏，直接修正（必要时再调用工具），然后给出最终答复；"
                            "如果核对无误，就直接给出最终答复，不要复述这段自检过程。"
                        )
                        messages.append({"role": "user", "content": audit})
                        turn_canonical.append({"role": "user", "content": audit})
                        self_check_done = True
                        iteration -= 1  # 自检注入轮不消耗工具调用配额
                        continue

                    credits_used = max(1, self._calculate_credits(total_usage, credit_multiplier)) if charge_credits else 0
                    if charge_credits:
                        await self._deduct_credits(user_id, credits_used, model_name)
                    if full_text:
                        turn_canonical.append({
                            "role": "assistant",
                            "content": full_text,
                            "tool_calls": [],
                        })
                    yield {
                        "type": "done",
                        "usage": total_usage,
                        "credits_used": credits_used,
                        "tool_calls_log": tool_calls_log,
                        "canonical": turn_canonical,
                    }
                    return

                # 撞上限收尾（P1-#3）：模型还想调工具，但已接近步数上限。不执行这些工具，
                # 改为把已产出的文本并入历史，注入「用已有信息收尾」提示，再给一轮无工具
                # 采样产出最终答复——避免大任务直接烂尾、之前的工作白费。
                if final_forced:
                    # 收尾轮里模型仍执意调工具（少见）：不再纠缠，直接用已产出文本收尾。
                    if full_text:
                        turn_canonical.append({
                            "role": "assistant", "content": full_text, "tool_calls": [],
                        })
                    else:
                        closing = "已到执行步数上限。以上是目前已完成的部分；可补充说明后我接着做。"
                        yield {"type": "text", "delta": "\n\n" + closing}
                        turn_canonical.append({
                            "role": "assistant", "content": closing, "tool_calls": [],
                        })
                    credits_used = max(1, self._calculate_credits(total_usage, credit_multiplier)) if charge_credits else 0
                    if charge_credits:
                        await self._deduct_credits(user_id, credits_used, model_name)
                    yield {
                        "type": "done", "usage": total_usage, "credits_used": credits_used,
                        "tool_calls_log": tool_calls_log, "canonical": turn_canonical,
                    }
                    return

                if iteration >= self.max_iterations - 1:
                    if full_text:
                        messages.append({"role": "assistant", "content": full_text})
                        turn_canonical.append({
                            "role": "assistant", "content": full_text, "tool_calls": [],
                        })
                    wrap = (
                        "（系统提示）已到本轮工具调用步数上限，不能再调用工具了。"
                        "请基于你目前已经掌握的信息，直接给出尽可能完整、有用的最终答复："
                        "总结已完成的部分和已得到的结论，对还没来得及核实/完成的部分如实说明，"
                        "并给出后续可以怎么继续。不要再尝试调用任何工具。"
                    )
                    messages.append({"role": "user", "content": wrap})
                    turn_canonical.append({"role": "user", "content": wrap})
                    final_forced = True
                    continue  # 收尾轮不减 iteration——靠 final_forced 单独保证只走一次

                # 构建本回合 canonical assistant 条目（含工具调用），再由统一序列化器
                # 转成 provider 格式追加到 messages——消除手工维护两套格式的漂移风险。
                _canon_tool_calls = []
                for tu in tool_uses:
                    try:
                        _ci = json.loads(tu["input_json"]) if tu["input_json"] else {}
                    except json.JSONDecodeError:
                        _ci = {}
                    _canon_tool_calls.append({"id": tu["id"], "name": tu["name"], "input": _ci})
                assistant_entry = {
                    "role": "assistant",
                    "content": full_text,
                    "tool_calls": _canon_tool_calls,
                }
                turn_canonical.append(assistant_entry)

                if active_backend == "anthropic":
                    messages.extend(ctx.to_anthropic([assistant_entry]))
                else:
                    serialized = ctx.to_openai([assistant_entry])
                    # 推理模型（DeepSeek thinking 等）要求把 reasoning_content 原样回传，否则下一轮报 400
                    if reasoning_text and serialized:
                        serialized[0]["reasoning_content"] = reasoning_text
                    messages.extend(serialized)

                # 执行工具并收集结果。
                # P0-2：同一轮模型可能一次发起多个工具调用（如逐篇 read_file 多个文件）。
                # 这些调用相互独立（模型在看不到彼此结果时同时发出），可并发执行，
                # 把多文件读取/检索的墙钟时间从「之和」降到「最慢的一个」。
                # 三段式：① 串行预处理（名字纠正/解析/发 tool_use 事件/内联处理 update_plan）
                # ② 并发执行真正的工具 ③ 串行后处理（错误判定/截断/发 tool_result，保持顺序）。
                tool_results = []
                valid_tool_names = [t["function"]["name"] for t in get_tool_definitions()]
                to_run = []  # [(tu, tool_args)]，待并发执行的真实工具
                for tu in tool_uses:
                    corrected_name = _resolve_tool_name(tu["name"], valid_tool_names)
                    if corrected_name:
                        tu["name"] = corrected_name

                    try:
                        tool_args = json.loads(tu["input_json"]) if tu["input_json"] else {}
                    except json.JSONDecodeError:
                        tool_args = {}

                    # update_plan 是「元工具」：不访问数据，只把计划状态推给前端，
                    # 并回一条简短 ack 维持工具调用协议有效。同时更新 current_plan
                    # 供主循环的任务状态停止条件使用。
                    if tu["name"] == "update_plan":
                        steps = tool_args.get("steps", []) if isinstance(tool_args, dict) else []
                        norm_steps = [
                            {
                                "content": str(s.get("content", "")).strip(),
                                "status": s.get("status", "pending"),
                            }
                            for s in steps if isinstance(s, dict)
                        ]
                        current_plan = norm_steps
                        yield {"type": "plan", "steps": norm_steps}
                        ack = "计划已更新。" + (
                            "全部步骤已完成。" if norm_steps and all(s["status"] == "completed" for s in norm_steps)
                            else "请按计划继续执行下一步。"
                        )
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tu["id"],
                            "content": ack,
                            "is_error": False,
                        })
                        continue

                    # 记录本轮用过「非元工具」（读/查/算/下载/联网等），供完成前的取数自检判断。
                    if tu["name"] not in _META_TOOLS:
                        data_tool_used = True

                    # 发送给前端的 input 做脱敏：去除代码、路径等内部细节
                    safe_input = {}
                    for k, v in tool_args.items():
                        if k == "code":
                            continue
                        elif k == "sql":
                            continue
                        elif k == "expression":
                            continue
                        elif k == "text" and len(str(v)) > 50:
                            safe_input[k] = str(v)[:50] + "..."
                        else:
                            safe_input[k] = v

                    yield {
                        "type": "tool_use",
                        "name": tu["name"],
                        "input": safe_input,
                        "id": tu["id"],
                        "summary": tool_display_summary(tu["name"], tool_args),
                    }
                    to_run.append((tu, tool_args))

                # ② 并发执行（单个失败不影响其它：异常就地转成错误字符串）
                async def _run_one(tu, tool_args):
                    try:
                        return str(await execute_tool(
                            tool_name=tu["name"],
                            arguments=tool_args,
                            user_id=user_id,
                            data_space_id=data_space_id,
                        ))
                    except Exception as e:
                        return f"工具执行错误: {str(e)}"

                run_results = []
                if to_run:
                    if len(to_run) == 1:
                        run_results = [await _run_one(to_run[0][0], to_run[0][1])]
                    else:
                        # 限流并发：最多 _TOOL_CONCURRENCY 个工具同时执行，避免打满资源
                        _sem = asyncio.Semaphore(_TOOL_CONCURRENCY)
                        async def _run_bounded(tu, ta):
                            async with _sem:
                                return await _run_one(tu, ta)
                        run_results = await asyncio.gather(
                            *[_run_bounded(tu, ta) for tu, ta in to_run]
                        )

                # ③ 串行后处理：按发起顺序做错误判定/截断/日志/事件，语义与原先一致
                for (tu, tool_args), result_str in zip(to_run, run_results):
                    is_error = _is_tool_error(result_str)
                    if is_error:
                        consecutive_errors += 1
                    else:
                        consecutive_errors = 0

                    # 模型可见的工具结果上限：放宽到 10 万字符，让"列出全部"
                    # 这类大结果集能完整进入上下文（约数千行），而不是被腰斩导致
                    # 漏行。极端超大结果（上万行）才会触顶，此时提示改用聚合/筛选。
                    if len(result_str) > 100000:
                        result_str = result_str[:100000] + (
                            "\n...(结果过大已截断。这通常意味着应该用聚合/分组/WHERE 缩小范围，"
                            "而不是逐行返回；如确需全部明细，请分批查询)"
                        )

                    tool_calls_log.append({
                        "name": tu["name"],
                        "input": tool_args,
                        "output_preview": result_str[:200],
                    })

                    # 脱敏：移除存储路径 + 遮蔽凭据。前端展示只取前 2000 字符，诚实标注是否截断。
                    full_len = len(result_str)
                    display_result = ctx.redact_secrets(
                        result_str[:2000].replace(settings.storage_root, "[数据]")
                    )
                    display_truncated = full_len > 2000

                    yield {
                        "type": "tool_result",
                        "name": tu["name"],
                        "content": display_result,
                        "is_error": is_error,
                        "truncated": display_truncated,
                        "total_chars": full_len,
                        "shown_chars": min(full_len, 2000),
                    }

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tu["id"],
                        "content": result_str,
                        "is_error": is_error,
                    })

                # 工具结果 → canonical，再由统一序列化器转 provider 格式追加到 messages。
                # 循环内 messages 用完整结果（模型可见），持久化的 turn_canonical 用按
                # 配置截断的结果（避免历史无限膨胀）。
                def _result_name(tr):
                    return next((tu["name"] for tu in tool_uses if tu["id"] == tr["tool_use_id"]), "")

                full_results_entry = {
                    "role": "tool_results",
                    "results": [
                        {"id": tr["tool_use_id"], "name": _result_name(tr),
                         "content": tr["content"], "is_error": tr["is_error"]}
                        for tr in tool_results
                    ],
                }
                if active_backend == "anthropic":
                    messages.extend(ctx.to_anthropic([full_results_entry]))
                else:
                    messages.extend(ctx.to_openai([full_results_entry]))

                turn_canonical.append({
                    "role": "tool_results",
                    "results": [
                        {
                            "id": tr["tool_use_id"],
                            "name": _result_name(tr),
                            # 持久化/回放边界：先截断再脱敏凭据（当轮模型看到的完整结果
                            # 在 messages 里，不受影响）。
                            "content": ctx.redact_secrets(ctx.truncate_tool_content(
                                tr["content"], settings.context_tool_result_max_chars
                            )),
                            "is_error": tr["is_error"],
                        }
                        for tr in tool_results
                    ],
                })

                # 重试逻辑：连续失败时注入提示（来自 KDD-CUP）
                if consecutive_errors >= 2:
                    messages.append({
                        "role": "user",
                        "content": "提示：已连续多次失败，请换一种方法尝试。减少探索步骤，直接用最简单的方式解决问题。",
                    })
                    consecutive_errors = 0

            except Exception as e:
                # 重试已在内层用尽（或属致命错误）。给用户一句可读的说明，
                # 并把本轮已产出的 canonical 落盘，便于下一轮接续。
                if any(k in str(e).lower() for k in _FATAL_KEYWORDS):
                    hint = "模型调用被拒绝（可能是 API Key 或请求配置问题）。请检查模型设置后重试。"
                else:
                    hint = "模型调用多次失败，可能是网络或服务暂时不可用。请稍后重试。"
                yield {"type": "error", "message": f"{hint}（{str(e)[:200]}）"}
                if turn_canonical:
                    credits_used = max(1, self._calculate_credits(total_usage, credit_multiplier)) if charge_credits else 0
                    yield {
                        "type": "done",
                        "usage": total_usage,
                        "credits_used": credits_used if charge_credits else 0,
                        "tool_calls_log": tool_calls_log,
                        "canonical": turn_canonical,
                        "interrupted": True,
                    }
                return

        # 达到最大迭代次数（正常情况下已被上面的「收尾轮」拦截并给出最终答复；
        # 走到这里属极端兜底）。
        credits_used = max(1, self._calculate_credits(total_usage, credit_multiplier)) if charge_credits else 0
        if charge_credits:
            await self._deduct_credits(user_id, credits_used, model_name)
        yield {"type": "text", "delta": "\n\n[已达到最大执行步数。以上是目前已完成的部分；可补充说明后让我接着做。]"}
        yield {"type": "done", "usage": total_usage, "credits_used": credits_used, "tool_calls_log": tool_calls_log, "canonical": turn_canonical}

    def _calculate_credits(self, usage: dict, multiplier: float = 1.0) -> int:
        return 1
