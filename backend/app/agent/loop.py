"""Agent ReAct 循环 - 基于 Anthropic SDK 的流式 Agent
融合 KDD-CUP 的 schema 预注入 + 重试逻辑 + DataMind 的能力
支持双后端：Anthropic 原生 / OpenAI 兼容接口"""
import uuid
import json
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
from app.agent.tools import get_tool_definitions, execute_tool
from app.core.security import decrypt_api_key


_client_cache: dict[str, Any] = {}


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


SYSTEM_PROMPT_TEMPLATE = """你是 DataMind，一个专业的数据分析助手。你帮助用户理解、查询和分析他们的数据。

{data_space_info}

{schema_context}

{knowledge_context}

{memory_context}

## 工具选择策略

1. 数据结构已在上方预注入，无需再调用 inspect_data（除非需要更详细信息）
2. 表格数据优先用 pandas_query（支持多行代码）或 sqlite_query 直接操作，不依赖索引
3. pandas_query 适合单表分析，支持多行代码（赋值给 result 变量返回结果）
4. sqlite_query 适合跨表 JOIN、GROUP BY 等 SQL 擅长的操作
5. read_file 可读取任何文件（CSV/Excel/PDF/Word/代码/数据库都支持）
6. execute_python 适合需要复杂逻辑、循环、多步计算的场景
7. generate_chart 生成可视化图表，善用它让数据直观呈现
8. search_data_space 适合在大量文本中搜索相关内容
9. nl2sql 适合用户的自然语言问题直接转 SQL 查询
10. graph_search 搜索知识图谱中的实体和关系
11. graph_traverse 从实体出发发现多跳关系路径
12. graph_extract_from_text 从文本中抽取三元组构建知识图谱

## 第一步：判断任务意图（决定输出形态，非常重要）

回答前先判断用户要的是哪一类，两类的输出要求完全不同：

**A. 取数 / 列出 / 导出类**（问"列出…"、"有哪些…"、"…的记录是什么"、"满足条件的…"、
"show/list the …"、要某些行某些列的明确结果集）：
- 你的首要职责是给出**完整、准确**的结果集——该有多少行就给多少行，**绝不能只给前几行、样本或 Top-N 就收尾**。
- 必须把全部结果放进末尾的 ```answer 块（见下）。哪怕几百上千行也要完整列出。
- 如果结果非常大（上万行），说明任务本意可能是聚合，回头与用户确认口径，而不是擅自只截取一部分冒充答案。
- 这类任务图表是可选的点缀，**完整数据才是答案**。不要用"趋势解读 + 几个样本"替代完整结果。

**B. 分析 / 解读 / 洞察类**（问"怎么样"、"趋势如何"、"帮我分析"、"为什么"）：
- 先给结论，再用关键数字、表格、图表支撑，适度解读。
- 这类才适合摘要式表达和主动配图。

拿不准时，倾向于 A：先给全量结果，再补一段简短解读。漏数据比多给解读严重得多。

## 输出格式要求

1. **善用 Markdown 表格**：展示数据对比时用表格而不是纯文本
2. **关键数字加粗**：用 **粗体** 突出最重要的数字和发现
3. **图表按需生成**：当数据有趋势、分布、对比关系且属于分析类任务时，用 generate_chart 可视化；取数类任务不要用图表替代完整数据
4. **引用数据来源**：说明"根据 xxx.csv 的数据"或"从表 xxx 中查询到"
5. **语言通俗**：避免技术术语，用业务语言解释

## 取数准确性要求（直接决定答案对错）

1. **完整性**：列表型答案必须包含全部满足条件的行，不得省略、不得只取前 N 行。先用 COUNT 确认应有多少行，再核对你列出的行数是否一致。
2. **去重口径**：问"多少个/几家/按 X 分组计数"时，想清楚计的是**记录数**还是**去重后的实体数**。按公司/客户/城市等实体统计时，通常要先对实体主键 DISTINCT 去重，再计数；不要把多条明细记录当成多个实体。
3. **筛选口径**：当筛选条件来自视频/文档（如准入线、阈值、规则），先从中读准字段名、比较符、阈值和单位，再写 WHERE，宁可多读一遍也不要凭印象。
4. **列与口径对齐**：```answer 块里的列、聚合方式、单位要和问题完全一致。

## 最终答案块（数据查询任务必须遵守）

当用户的问题是要查一个确定的数据结果（计数、最值、某条记录的字段、满足条件的列表等）时，
你必须在回答的**最末尾**额外输出一个干净的结果块，格式如下：

```answer
列名1,列名2
值1,值2
值3,值4
```

规则：
- 用逗号分隔列，每行一条记录，第一行是列名。
- **只放最终答案本身**：恰好是问题所要求的那些行和列，不要掺入解释行、汇总行（如"总计"）、排名序号、单位后缀、emoji、千分位逗号。
- 行数要完整：如果答案是一个列表（比如"满足条件的所有公司"），就把**全部**满足条件的行都列出来，哪怕有几十上百行，不要只列前几行或省略。
- 数值就写原始数值（如 22101086925，不要写"约221亿"）。
- 如果问题要求分组计数，列名和聚合口径要和问题一致；除非明确要求去重，否则 COUNT 按行计数。
- 这个 ```answer 块是给系统精确核对用的，务必与你正文结论一致。

## 注意事项

- 数据空间里的每一个文件都是用户主动上传的，都有其用途。当用户问"有什么文件/数据"时，列出所有文件，不要遗漏任何一个
- 代码文件（.py/.sql/.r 等）也是数据空间的重要组成部分，可能包含数据处理逻辑或分析脚本
- 如果工具调用失败，立即换一种方法。例如 pandas_query 失败可以试 sqlite_query 或先用 read_file 看清数据再分析。读取文件内容一律用 read_file 工具（支持 CSV/Excel/PDF/Word/代码/数据库等所有格式），不要在 execute_python 里用 open() 读文件——沙箱出于安全禁止 open。不要把错误信息原样转述给用户，直接换方法解决
- 如果发现重要模式或用户偏好，用 save_memory 记住
- 用户没有指定分析维度时，主动从最有价值的角度切入

## 必须坚持到底（直接决定答案对错）

- **绝不轻易放弃**：在产出 ```answer 块之前，你的任务是把答案查全查准。如果某个字段/某条记录在当前数据源没找到，不要直接写"未知""视频未展示"就收尾——换数据源再找：相关字段可能在另一张表、另一个文件、或文档/视频的其他位置（电话、联系方式、识别码等常分散在不同字段卡或表里）。把所有可能的来源都查过，确实查不到才如实说明。
- **绝不向用户反问来代替查数**：本任务要的是数据结果，不是对话。不要问"你想看哪个省份/年份/维度吗？"这类问题；自己依据问题口径把结果算出来直接给。问题里的口径（字段、阈值、分组维度）以题面和视频/文档为准，不确定时按最直接的字面理解执行，不要停下来等用户澄清。
- **读准字段，不要张冠李戴**：当存在名字相近的多个字段/指标（如"在任基金数" vs "旗下基金总数"、"本日"vs"近一周"），先回到题面确认问题问的到底是哪一个，再取对应字段。取错相近字段是常见且致命的错误。
- **文档里的结构化数据用代码解析，不要手抄**：当 (实体, 数值) 这类成对数据被写在 Markdown/PDF 的叙述文字里（每段一条记录、可能有几十上百条），不要在 execute_python 里手敲硬编码列表——那样必然漏行或抄错。正确做法是用 read_file 取得全文后，在 execute_python / pandas_query 里用正则按统一模式批量抽取所有记录，再筛选排序。注意这类文档常埋"陷阱值"（"初步为 X，经核实后确认为 Y"），要取**最终确认值**，忽略被修正掉的初值。
- **表名查不到 ≠ 数据不存在**：当 knowledge.md 或视频/题面提到某个表（如 mf_xxx），但 sqlite_query 列不出这张表、inspect_data 也说不支持时，**绝不要据此判定"数据缺失"或"无此表"而放弃**。这类表的数据极可能以**同名的 .md / .pdf 文档**形式存在（如 mf_xxx.md、mf_xxx.pdf），只是没进 SQL 引擎。务必用 read_file 把该同名文档**完整读完**（注意分页，文件几百行就一直读到末尾），再从叙述文字里按统一模式正则抽取所需字段。同名相近的表/文档可能是干扰项，认准题面/knowledge.md 指定的那个名字。
- **同一份数据可能拆成两段**：一份文档里"档案信息段"（记录号↔名称/代码的映射）和"指标数值段"（记录号↔各项数值）可能分处不同位置，需按记录号/识别码把两段 JOIN 起来才能得到完整的 (名称, 数值) 行。读全文、两段都抽、再按键关联，不要只读前半段就下结论。
- **答案要落进 ```answer 块**：分析做到一半不要停。无论中间过程多长，最后一定要回到题面要求，输出与正文一致的 ```answer 块；没有这个块等于没回答。

## 没有数据空间时

如果用户没有选择数据空间，你仍然可以：
1. 回答数据分析方法论问题
2. 帮助用户规划分析思路
3. 解释统计概念
4. 建议用户创建数据空间并上传数据

## 错误恢复策略

当工具调用失败时，按以下优先级尝试替代方案：
1. pandas_query 失败 → 尝试 sqlite_query，或先用 read_file 看清数据结构再写表达式
2. sqlite_query 失败 → 尝试 pandas_query
3. read_file 失败 → 尝试 inspect_data 查看数据画像，或用 search_data_space 检索内容（切勿在 execute_python 里用 open 读文件，沙箱禁止）
4. search_data_space 失败 → 尝试 read_file 逐文件查找
5. 如果所有方法都失败，诚实告知用户并建议替代方案

## 代码执行约束（execute_python）

execute_python 是受限沙箱，仅用于对**已加载的数据**做计算：可用 pandas/numpy 等白名单库，可用预加载的 df_xxx 变量。禁止 open、import 非白名单模块（包括 sqlite3、os、sys 等）、exec/eval 等。
- 需要查数据库时不要在 execute_python 里 import sqlite3，直接用 sqlite_query 工具；需要文件内容时先用 read_file 获取。
- 嵌套 JSON（形如 records 数组包在外层对象里）已自动展平为标准 DataFrame，可直接按业务列名取数。
- 不要为"换种写法"反复重试被禁的操作；遇到沙箱限制就换用对应的专用工具（sqlite_query / read_file）。"""


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
        "pdf": "PDF文档", "docx": "Word文档",
        "png": "图片", "jpg": "图片", "jpeg": "图片", "gif": "图片", "bmp": "图片", "webp": "图片",
    }

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

            file_list = "\n".join(
                f"  - {f.filename} [{self._FILE_TYPE_LABELS.get(f.file_type, f.file_type)}] ({_format_size(f.file_size)})"
                for f in files
            )

            return f"""数据空间名称: {space.name}
描述: {space.description or '无'}
共 {len(files)} 个文件:
{file_list or '  (空)'}"""

    async def _build_schema_context(self, data_space_id: uuid.UUID | None, user_id: uuid.UUID) -> str:
        """预注入 schema + 质量信息。
        合并策略：已有 profile 的文件用 profile 数据，还没处理完的用实时加载兜底。
        保证所有文件都出现在 Agent 视野中。"""
        if not data_space_id:
            return ""

        try:
            from app.models.data_profile import DataProfile
            from app.agent.tools import _get_space_files, _load_df
            import pandas as pd
            import asyncio

            # 获取所有文件
            all_files = await _get_space_files(user_id, data_space_id)
            if not all_files:
                return ""

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


            lines = ["## 数据概览\n"]
            all_columns: dict[str, dict[str, set]] = {}
            MAX_SCHEMA_COLS = 30
            TABULAR_EXTS = {"csv", "tsv", "xlsx", "xls", "json", "jsonl", "parquet", "feather", "dta", "sav", "sas7bdat"}


            # 遍历所有文件
            for f in all_files[:15]:
                fid = str(f.id)
                profile = profile_map.get(fid)

                # 有 profile 且已就绪 → 用 profile 的丰富信息
                if profile and profile.status == "ready" and profile.profile_type == "tabular":
                    data = profile.profile_data or {}
                    row_count = data.get("row_count", "?")
                    col_count = data.get("column_count", "?")
                    columns = data.get("columns", [])

                    lines.append(f"### {f.filename}  rows={row_count}  cols={col_count}")
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
                        lines.append(f"    - {name} ({dtype}) unique={unique} ex=[{samples_str}]{extra}")
                        if name not in all_columns:
                            all_columns[name] = {}
                        all_columns[name][f.filename] = set(str(s) for s in samples)

                    if len(columns) > MAX_SCHEMA_COLS:
                        lines.append(f"    ...（还有 {len(columns) - MAX_SCHEMA_COLS} 列）")

                    quality = data.get("quality", {})
                    qp = []
                    if quality.get("duplicate_pct", 0) > 1: qp.append(f"重复率{quality['duplicate_pct']}%")
                    if quality.get("complete_pct", 100) < 95: qp.append(f"完整率{quality['complete_pct']}%")
                    if quality.get("outlier_columns"): qp.append(f"{len(quality['outlier_columns'])}列有异常值")
                    if quality.get("type_suggestions"): qp.append(f"{len(quality['type_suggestions'])}列可转类型")
                    if qp:
                        lines.append(f"    ⚠️ {', '.join(qp)}")
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
                            lines.append(f"### {f.filename}  rows={len(df)}  cols={len(df.columns)}")
                            for col in list(df.columns)[:MAX_SCHEMA_COLS]:
                                unique = int(df[col].nunique())
                                dtype = str(df[col].dtype)
                                samples = ", ".join(str(s)[:20] for s in df[col].dropna().unique()[:3])
                                lines.append(f"    - {col} ({dtype}) unique={unique} ex=[{samples}]")
                                if col not in all_columns:
                                    all_columns[col] = {}
                                all_columns[col][f.filename] = set(str(s) for s in df[col].dropna().unique()[:50].tolist())
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
                    lines.append("")

            # JOIN 检测
            joins = self._detect_joins_for_schema(all_columns)
            if joins:
                lines.append("### 潜在 JOIN 关系")
                lines.extend(joins)

            return "\n".join(lines)
        except Exception:
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
        """获取对话历史，转为 Anthropic 格式。
        恢复工具调用上下文摘要，让 Agent 在续对话时知道自己之前分析了什么。"""
        async with get_session_factory()() as db:
            result = await db.execute(
                select(Message)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.created_at)
            )
            messages = result.scalars().all()

            history = []
            for msg in messages:
                if msg.role == "user":
                    history.append({"role": "user", "content": msg.content})
                elif msg.role == "assistant":
                    content_parts = []
                    if msg.content:
                        content_parts.append(msg.content)
                    # 从 tool_calls (segments) 中提取工具调用摘要
                    if msg.tool_calls and isinstance(msg.tool_calls, list):
                        tool_summary = []
                        for seg in msg.tool_calls:
                            if isinstance(seg, dict) and seg.get("type") == "tools":
                                for ev in seg.get("events", []):
                                    if ev.get("type") == "tool_use":
                                        name = ev.get("name", "")
                                        input_str = json.dumps(ev.get("input", {}), ensure_ascii=False)[:100]
                                        tool_summary.append(f"[调用了 {name}: {input_str}]")
                        if tool_summary and not content_parts:
                            content_parts.append("\n".join(tool_summary))
                    if content_parts:
                        history.append({"role": "assistant", "content": "\n".join(content_parts)})

            return history

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

    async def run(
        self,
        conversation_id: uuid.UUID,
        user_id: uuid.UUID,
        data_space_id: uuid.UUID | None,
        model_id: str,
        user_message: str,
        is_admin: bool = False,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """执行 Agent 循环，流式返回事件"""
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

        # 构建系统提示（含文件列表 + schema 预注入 + knowledge.md + 记忆）
        data_space_info = await self._get_data_space_info(data_space_id, user_id)
        schema_context = await self._build_schema_context(data_space_id, user_id)
        knowledge_context = await self._get_knowledge_context(data_space_id, user_id)

        memory_context = ""
        try:
            from app.services.memory import recall
            memories = await recall(user_id, user_message, data_space_id=data_space_id)
            if memories:
                memory_lines = [f"- [{m['scope']}/{m['kind']}] {m['content']}" for m in memories]
                memory_context = "## 相关记忆\n" + "\n".join(memory_lines)
        except Exception:
            pass

        system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
            data_space_info=data_space_info,
            schema_context=schema_context,
            knowledge_context=knowledge_context,
            memory_context=memory_context,
        )

        # 构建 system 块（支持 prompt caching）
        system_blocks = []
        if settings.enable_prompt_caching:
            system_blocks = [
                {"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}
            ]
        else:
            system_blocks = system_prompt

        history = await self._get_conversation_history(conversation_id)
        messages = [*history[-20:], {"role": "user", "content": user_message}]

        tools = self._tools_to_anthropic_format()
        total_usage = {"input_tokens": 0, "output_tokens": 0}
        tool_calls_log = []
        consecutive_errors = 0

        yield {"type": "thinking", "content": "正在分析问题..."}

        # 撞步数上限前，预留一步强制收尾：注入一条指令让 Agent 用已有信息
        # 立即产出 ```answer 块，而不是悄无声息地耗尽步数、留下半截分析。
        # 在倒数第二步触发，给模型一整轮来组织最终答案。
        finalize_step = max(0, self.max_iterations - 1)
        finalize_injected = False

        for iteration in range(self.max_iterations):
            if self._abort_check():
                yield {"type": "text", "delta": "\n\n[已被用户中断]"}
                break

            # 接近上限时强制收尾：禁用工具 + 注入收尾指令，逼模型给最终答案。
            force_finalize = iteration >= finalize_step
            if force_finalize and not finalize_injected:
                messages.append({
                    "role": "user",
                    "content": "（系统提示）你已接近本次任务的步数上限，不能再调用工具了。"
                               "请立即基于你已经获取到的信息，直接给出最终答案，并务必在末尾输出与题面要求一致的 ```answer 块"
                               "（列名+全部数据行，CSV 格式）。如果某些信息仍不完整，就用现有最可靠的数据作答，不要再说"
                               "\"还需要进一步查询\"或留下空答案。",
                })
                finalize_injected = True

            try:
                full_text = ""
                reasoning_text = ""  # 推理模型的思考内容（DeepSeek 等需回传）
                tool_uses = []

                if active_backend == "anthropic":
                    # Anthropic SDK 流式调用
                    response_stream = client.messages.stream(
                        model=model_name,
                        max_tokens=settings.anthropic_max_tokens,
                        system=system_blocks,
                        messages=messages,
                        tools=[] if force_finalize else tools,
                    )
                    async with response_stream as stream:
                        async for event in stream:
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
                                    yield {"type": "text", "delta": event.delta.text}
                                elif event.delta.type == "input_json_delta":
                                    if tool_uses:
                                        tool_uses[-1]["input_json"] += event.delta.partial_json
                        final_message = await stream.get_final_message()
                        total_usage["input_tokens"] += final_message.usage.input_tokens
                        total_usage["output_tokens"] += final_message.usage.output_tokens

                else:
                    # OpenAI 兼容接口流式调用
                    openai_tools = get_tool_definitions()
                    oai_messages = [{"role": "system", "content": system_blocks if isinstance(system_blocks, str) else system_blocks[0]["text"]}] + messages
                    response = await client.chat.completions.create(
                        model=model_name,
                        messages=oai_messages,
                        tools=None if force_finalize else (openai_tools if openai_tools else None),
                        stream=True,
                    )
                    tool_calls_data = []
                    async for chunk in response:
                        delta = chunk.choices[0].delta if chunk.choices else None
                        if not delta:
                            continue
                        # 处理推理模型的 reasoning_content（如 DeepSeek）
                        reasoning = getattr(delta, 'reasoning_content', None)
                        if reasoning:
                            reasoning_text += reasoning
                            yield {"type": "thinking", "content": reasoning}
                        if delta.content:
                            full_text += delta.content
                            yield {"type": "text", "delta": delta.content}
                        if delta.tool_calls:
                            for tc in delta.tool_calls:
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

                # 没有工具调用 → Agent 完成
                if not tool_uses:
                    credits_used = max(1, self._calculate_credits(total_usage, credit_multiplier)) if charge_credits else 0
                    if charge_credits:
                        await self._deduct_credits(user_id, credits_used, model_name)
                    yield {
                        "type": "done",
                        "usage": total_usage,
                        "credits_used": credits_used,
                        "tool_calls_log": tool_calls_log,
                    }
                    return

                # 构建 assistant 消息（格式因后端而异）
                if active_backend == "anthropic":
                    assistant_content = []
                    if full_text:
                        assistant_content.append({"type": "text", "text": full_text})
                    for tu in tool_uses:
                        try:
                            input_data = json.loads(tu["input_json"]) if tu["input_json"] else {}
                        except json.JSONDecodeError:
                            input_data = {}
                        assistant_content.append({
                            "type": "tool_use",
                            "id": tu["id"],
                            "name": tu["name"],
                            "input": input_data,
                        })
                    messages.append({"role": "assistant", "content": assistant_content})
                else:
                    # OpenAI 格式
                    assistant_msg = {
                        "role": "assistant",
                        "content": full_text or None,
                        "tool_calls": [
                            {"id": tu["id"], "type": "function", "function": {"name": tu["name"], "arguments": tu["input_json"]}}
                            for tu in tool_uses
                        ],
                    }
                    # 推理模型（DeepSeek thinking 等）要求把 reasoning_content 原样回传，否则下一轮报 400
                    if reasoning_text:
                        assistant_msg["reasoning_content"] = reasoning_text
                    messages.append(assistant_msg)

                # 执行工具并收集结果
                tool_results = []
                for tu in tool_uses:
                    try:
                        tool_args = json.loads(tu["input_json"]) if tu["input_json"] else {}
                    except json.JSONDecodeError:
                        tool_args = {}

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
                    }

                    tool_result = await execute_tool(
                        tool_name=tu["name"],
                        arguments=tool_args,
                        user_id=user_id,
                        data_space_id=data_space_id,
                    )

                    result_str = str(tool_result)
                    is_error = result_str.startswith("工具执行错误") or result_str.startswith("SQL 错误")

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

                    # 脱敏：移除存储路径
                    display_result = result_str[:2000].replace(settings.storage_root, "[数据]")

                    yield {
                        "type": "tool_result",
                        "name": tu["name"],
                        "content": display_result,
                        "is_error": is_error,
                    }

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tu["id"],
                        "content": result_str,
                        "is_error": is_error,
                    })

                # 追加工具结果到消息（格式因后端而异）
                if active_backend == "anthropic":
                    messages.append({"role": "user", "content": tool_results})
                else:
                    for tr in tool_results:
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tr["tool_use_id"],
                            "content": tr["content"],
                        })

                # 重试逻辑：连续失败时注入提示（来自 KDD-CUP）
                if consecutive_errors >= 2:
                    messages.append({
                        "role": "user",
                        "content": "提示：已连续多次失败，请换一种方法尝试。减少探索步骤，直接用最简单的方式解决问题。",
                    })
                    consecutive_errors = 0

            except Exception as e:
                yield {"type": "error", "message": f"Agent 执行出错: {str(e)}"}
                return

        # 达到最大迭代次数
        credits_used = max(1, self._calculate_credits(total_usage, credit_multiplier)) if charge_credits else 0
        if charge_credits:
            await self._deduct_credits(user_id, credits_used, model_name)
        yield {"type": "text", "delta": "\n\n[已达到最大执行步数，自动停止]"}
        yield {"type": "done", "usage": total_usage, "credits_used": credits_used, "tool_calls_log": tool_calls_log}

    def _calculate_credits(self, usage: dict, multiplier: float = 1.0) -> int:
        return 1
