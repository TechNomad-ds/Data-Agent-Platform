"""Agent 工具定义与执行 - 融合 DataMind + KDD-CUP 能力"""
import uuid
import json
import ast
import os
import re
from pathlib import Path
from typing import Any

import pandas as pd
import numpy as np
from sqlalchemy import select

from app.config import settings
from app.core.database import get_session_factory
from app.models.file import File
from app.models.data_space import DataSpaceFile


def get_tool_definitions() -> list[dict]:
    """返回 OpenAI 格式的工具定义列表"""
    return [
        {
            "type": "function",
            "function": {
                "name": "search_data_space",
                "description": "【读文件核心工具】在当前数据空间的大量文本里语义检索相关内容，定位某主题/问题在哪个文件、哪一段。适合在厚文档、多文档里先定位再精读。返回的是命中片段（碎片），只用于定位，不能当成已读全文——定位到后用 read_file（厚文档配 find 跳读）看完整上下文。不要用它替代表格聚合计算。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "搜索查询内容"},
                        "top_k": {"type": "integer", "description": "返回结果数量", "default": 5},
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "【读文件核心工具】读懂数据空间里的任意文件——文档、PDF、论文、讲义、Word、PPT、代码、图片(OCR)、表格、数据库。要基于上传内容讲解/总结/答疑/抽取信息时，这是主力工具。返回末尾会标注是否已读到文件结尾——逐篇讲解/总结整篇文档时，必须翻页读到出现“已读到文件结尾”再下结论，不要只读开头一页就概括全文。对很厚的文档（教科书、长报告），不要从头整本读：先用 search_data_space 语义定位到相关内容，再用本工具的 find 参数跳到该处精读，返回会给出所在页码和如何看下一处匹配。（表格的统计聚合用 pandas_query/sqlite_query，不用本工具。）",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "filename": {"type": "string", "description": "文件名"},
                        "find": {"type": "string", "description": "可选：在文件内按关键词/短语定位（大小写不敏感），跳到第一处匹配并返回其上下文窗口，而不是从头读。适合在厚文档里定位某个主题/章节。用 search_data_space 命中的原文短语做 find 效果最好。"},
                        "start_line": {"type": "integer", "description": "起始行号（从0开始）。文件未读完时，用上次返回的结尾行号继续读；配合 find 时，从该行之后查找下一处匹配。", "default": 0},
                        "max_lines": {"type": "integer", "description": "最大读取行数（find 模式下为匹配处上下文窗口大小）。默认 800；表格/长章节想一次读完可调到更大（如 2000）。", "default": 800},
                    },
                    "required": ["filename"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "list_files",
                "description": "【读文件核心工具】列出当前数据空间里的全部文件（文件名、类型、大小），不限类型——PDF、Word、PPT、图片、代码、表格都会列出。需要知道“有哪些文件 / 有哪些论文 / 有哪些文档”、或要逐篇/逐个处理文件却不确定文件名时，先用它拿到准确文件名，不要猜文件名，也不要用 search_data_space 去凑。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "ext": {"type": "string", "description": "可选：只列某一类扩展名（如 pdf、docx、csv），不传则列全部"},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "inspect_data",
                "description": "【表格分析】查看结构化数据文件(CSV/Excel/JSON)的 schema、列信息、样本数据、execute_python 可用 DataFrame 变量名和跨文件 join 建议。字段或变量名不确定时先用它。注意：只认表格，对 PDF/Word/文档无效——看文档用 read_file，列全部文件用 list_files。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "filename": {"type": "string", "description": "文件名（留空则检查所有文件）"},
                    },
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "pandas_query",
                "description": "【表格分析】对单个 CSV/Excel/JSON 文件执行 pandas 查询。该文件已加载为 df 变量。适合单表探索、清洗、分组、趋势、统计。每次调用都是无状态沙箱，上一轮变量/新增列不会保留；多步分析必须在同一个 expression 里完成，并赋值给 result 或 print 输出。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "filename": {"type": "string", "description": "数据文件名"},
                        "expression": {"type": "string", "description": "pandas 表达式或多行代码，例如 df.describe()，或先创建日期/时长派生列再 groupby，最后把结果赋给 result 或让最后一行成为表达式"},
                    },
                    "required": ["filename", "expression"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "sqlite_query",
                "description": "【表格分析】对数据空间中的所有表格数据执行 SQL 查询（已自动把空间内所有表格加载进库，直接查即可，无需先导入）。适合多表 JOIN、过滤、计数、GROUP BY、排序。表名通常为文件名（去扩展名，小写，下划线替换空格）；多工作表 Excel 会展开为 文件名__工作表名。只支持 SELECT/WITH 查询。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "sql": {"type": "string", "description": "SQL 查询语句（只支持 SELECT/WITH）"},
                    },
                    "required": ["sql"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "execute_python",
                "description": "【表格分析】执行 Python 代码进行复杂数据分析。适合多文件联合计算、复杂派生指标、循环、统计摘要。数据空间中的 CSV/Excel/JSON 已预加载为 DataFrame 变量，具体变量名见 schema 或 inspect_data 输出。每次调用都是无状态沙箱，上一轮变量/新增列不会保留；多步分析必须在同一个 code 里完成，并赋值给 result 或 print 输出。可用库：pandas(pd)、numpy(np)、json、math、statistics",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "code": {"type": "string", "description": "要执行的 Python 代码"},
                    },
                    "required": ["code"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "generate_chart",
                "description": "生成可视化图表。返回图表 JSON 规格，前端会自动渲染",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "chart_type": {"type": "string", "enum": ["bar", "line", "pie", "scatter", "heatmap"], "description": "图表类型"},
                        "title": {"type": "string", "description": "图表标题"},
                        "data": {"type": "object", "description": "图表数据。bar/line: {x:[], y:[]}; pie: {items:[{name,value}]}; scatter: {points:[[x,y]]}; heatmap: {x_labels:[], y_labels:[], values:[[row,col,val]]}"},
                        "x_label": {"type": "string", "description": "X轴标签"},
                        "y_label": {"type": "string", "description": "Y轴标签"},
                    },
                    "required": ["chart_type", "data"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "save_memory",
                "description": "保存重要发现或用户偏好到记忆系统，以便后续对话中使用",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "content": {"type": "string", "description": "要记住的内容"},
                        "kind": {"type": "string", "enum": ["fact", "preference", "workflow", "summary"], "description": "记忆类型"},
                        "scope": {"type": "string", "enum": ["session", "space", "global"], "description": "记忆范围"},
                    },
                    "required": ["content"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "nl2sql",
                "description": "【少数场景】用自然语言描述查询内容，自动生成 SQL 并执行。仅当表结构复杂、自己写 SQL 没把握时用；表结构清楚时直接用 sqlite_query 更可控、能看到实际查询。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "question": {"type": "string", "description": "自然语言问题，如'哪个客户消费最多'"},
                    },
                    "required": ["question"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "kb_reindex_file",
                "description": "重新索引数据空间中的指定文件（重新分段和嵌入向量）。用于文件更新后刷新索引",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "filename": {"type": "string", "description": "要重新索引的文件名"},
                    },
                    "required": ["filename"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "graph_search",
                "description": "【少数场景】在知识图谱中搜索实体，返回匹配节点及连接度。仅当任务明确涉及实体关系网络时用；普通查表/读文档不要用。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "搜索关键词"},
                        "top_k": {"type": "integer", "description": "返回结果数量", "default": 5},
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "graph_traverse",
                "description": "【少数场景】从指定实体出发，遍历知识图谱中的关系路径，可发现多跳关系。仅当任务明确涉及实体关系网络时用。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "entity": {"type": "string", "description": "起始实体名称"},
                        "max_hops": {"type": "integer", "description": "最大遍历跳数", "default": 2},
                    },
                    "required": ["entity"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "graph_extract_from_text",
                "description": "【少数场景】从文本中用 LLM 抽取实体关系三元组并存入知识图谱（会触发额外 LLM 调用）。仅当明确要构建实体关系网络时用。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "要抽取三元组的文本内容"},
                        "max_triples": {"type": "integer", "description": "最多抽取的三元组数量", "default": 30},
                    },
                    "required": ["text"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "update_plan",
                "description": (
                    "维护一个面向用户可见的任务计划清单。当任务需要多个步骤"
                    "（如逐表分析、多文件汇总、列出大量记录、端到端取数）时，"
                    "在开始时调用它列出步骤，随后每完成一步就再次调用更新状态。"
                    "简单的单步问答、概念解释、闲聊不要使用。"
                    "每次调用都要传入完整的步骤列表（含所有步骤的最新状态），"
                    "而不是只传变化的那一条。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "steps": {
                            "type": "array",
                            "description": "完整的步骤列表，按执行顺序排列",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "content": {"type": "string", "description": "这一步要做什么（一句话，面向用户）"},
                                    "status": {
                                        "type": "string",
                                        "enum": ["pending", "in_progress", "completed"],
                                        "description": "步骤状态：未开始 / 进行中 / 已完成",
                                    },
                                },
                                "required": ["content", "status"],
                            },
                        },
                    },
                    "required": ["steps"],
                },
            },
        },
    ]


async def _get_file_path(filename: str, user_id: uuid.UUID, data_space_id: uuid.UUID | None) -> Path | None:
    async with get_session_factory()() as db:
        query = select(File).where(File.user_id == user_id, File.filename == filename)
        if data_space_id:
            query = (
                select(File)
                .join(DataSpaceFile, DataSpaceFile.file_id == File.id)
                .where(File.user_id == user_id, File.filename == filename, DataSpaceFile.data_space_id == data_space_id)
            )
        # 同一空间内可能存在同名文件（如 zip 解压出多份 package.json / incident_records.csv），
        # 此时不能用 scalar_one_or_none()——它在多行时会抛 MultipleResultsFound，导致
        # read_file / pandas_query / sqlite_query 全部失败。取第一个匹配即可。
        result = await db.execute(query)
        file = result.scalars().first()
        if not file:
            return None
        return Path(settings.storage_root) / file.storage_path


async def _get_space_files(user_id: uuid.UUID, data_space_id: uuid.UUID) -> list:
    async with get_session_factory()() as db:
        result = await db.execute(
            select(File).join(DataSpaceFile, DataSpaceFile.file_id == File.id)
            .where(DataSpaceFile.data_space_id == data_space_id, File.user_id == user_id)
        )
        return result.scalars().all()


async def _get_profile_ocr_text(filename: str, user_id: uuid.UUID, data_space_id: uuid.UUID | None) -> str | None:
    """从 DataProfile 取该文件的 OCR 全文（read_file 回退用）。"""
    if not data_space_id:
        return None
    from app.models.data_profile import DataProfile
    async with get_session_factory()() as db:
        result = await db.execute(
            select(DataProfile)
            .join(File, File.id == DataProfile.file_id)
            .where(
                File.filename == filename,
                File.user_id == user_id,
                DataProfile.data_space_id == data_space_id,
            )
        )
        # 同名文件可能匹配多个 profile，取第一个即可（避免 MultipleResultsFound）
        profile = result.scalars().first()
        if not profile:
            return None
        return (profile.profile_data or {}).get("ocr_text")


def _load_df(file_path: Path, ext: str) -> pd.DataFrame:
    from app.services.file_loader import load_dataframe
    return load_dataframe(file_path, ext)


def _col_describe(series) -> str:
    """生成一列的描述行，对含 list/dict 等不可哈希值的列安全降级。

    LLM 训练数据常见的 json/jsonl（messages/tools/golden_answers 等嵌套数组）
    会把 list/dict 放进单元格。pandas 的 nunique() 要对值做哈希去重，遇到
    list 直接抛 unhashable type，导致整个 inspect_data 失败、模型误判数据缺失。
    这里：先按 dtype 取非空数；唯一值用可哈希值直接算，不可哈希时按 repr 字符串去重；
    示例值统一截断，list/dict 用紧凑 JSON 片段展示。"""
    non_null = int(series.notna().sum())
    total = len(series)
    nn = series.dropna()
    try:
        unique = int(nn.nunique())
    except TypeError:
        # 含不可哈希值（list/dict）：按字符串化去重
        try:
            unique = int(nn.map(lambda v: json.dumps(v, ensure_ascii=False, sort_keys=True)
                                 if isinstance(v, (list, dict)) else str(v)).nunique())
        except Exception:
            unique = "?"

    sample_val = "N/A"
    if non_null > 0:
        raw = nn.iloc[0]
        if isinstance(raw, (list, dict)):
            try:
                sample_val = json.dumps(raw, ensure_ascii=False)[:80]
            except Exception:
                sample_val = str(raw)[:80]
        else:
            sample_val = str(raw)[:50]
    return f"  - {series.name}: {series.dtype} ({non_null}/{total} 非空, {unique} 唯一值, 示例: {sample_val})"


def _df_preview(df: pd.DataFrame, n: int = 5, cell_chars: int = 60) -> str:
    """前 N 行预览，硬截断每个单元格，避免长文本列（instruction/output/全文）
    把单次 inspect 输出撑到几十万字符、污染上下文预算。

    不依赖 pandas 的 display.max_colwidth：它对宽 object 列、list/dict 单元格的
    截断在不同版本下不可靠（实测一篇 4 万字论文的列仍会整列刷出）。这里在渲染前
    把每个单元格字符串化并截断，从根上限制输出体量。"""
    head = df.head(n).copy()

    def _trunc(v):
        if isinstance(v, (list, dict)):
            try:
                s = json.dumps(v, ensure_ascii=False)
            except Exception:
                s = str(v)
        else:
            s = str(v)
        return s[:cell_chars] + "…" if len(s) > cell_chars else s

    for col in head.columns:
        head[col] = head[col].map(_trunc)
    with pd.option_context("display.max_colwidth", cell_chars + 4, "display.width", 200):
        return head.to_string()


DATAFRAME_FILE_KINDS = {
    "csv": "csv",
    "xlsx": "excel",
    "xls": "excel",
    "json": "json",
}


def _safe_dataframe_var_base(filename: str) -> str:
    stem = filename.rsplit(".", 1)[0].lower()
    base = re.sub(r"\W+", "_", stem).strip("_")
    if not base:
        base = "data"
    if base[0].isdigit():
        base = "file_" + base
    return base


def _safe_dataframe_var_part(value: str, fallback: str = "sheet") -> str:
    part = re.sub(r"\W+", "_", value.lower()).strip("_")
    if not part:
        part = fallback
    if part[0].isdigit():
        part = f"{fallback}_{part}"
    return part


def _build_dataframe_preload(files: list) -> tuple[dict[str, tuple], dict[str, str]]:
    """生成 execute_python 预加载变量，避免同名/复杂文件名导致覆盖或不可读。"""
    preload: dict[str, tuple] = {}
    file_id_to_var: dict[str, str] = {}
    used: dict[str, int] = {}

    sorted_files = sorted(files, key=lambda f: (f.filename.lower(), str(getattr(f, "id", ""))))
    for f in sorted_files:
        full_path = Path(settings.storage_root) / f.storage_path
        ext = f.filename.rsplit(".", 1)[-1].lower()
        kind = DATAFRAME_FILE_KINDS.get(ext)
        if not kind:
            continue
        base = _safe_dataframe_var_base(f.filename)
        vars_for_file = []
        if ext in ("xlsx", "xls"):
            try:
                from app.services.file_loader import load_excel_sheets
                sheet_names = list(load_excel_sheets(full_path, nrows=1).keys())
            except Exception:
                sheet_names = []
            for index, sheet_name in enumerate(sheet_names, start=1):
                sheet_part = _safe_dataframe_var_part(sheet_name, f"sheet{index}")
                candidate = f"{base}__{sheet_part}" if len(sheet_names) > 1 else base
                used[candidate] = used.get(candidate, 0) + 1
                suffix = "" if used[candidate] == 1 else f"_{used[candidate]}"
                var = f"df_{candidate}{suffix}"
                preload[var] = (kind, str(full_path), sheet_name)
                vars_for_file.append(var)
        else:
            used[base] = used.get(base, 0) + 1
            suffix = "" if used[base] == 1 else f"_{used[base]}"
            var = f"df_{base}{suffix}"
            preload[var] = (kind, str(full_path))
            vars_for_file.append(var)

        if vars_for_file:
            file_id_to_var[str(getattr(f, "id", f.filename))] = ", ".join(vars_for_file)

    return preload, file_id_to_var


def _resolve_tool_name(name: str, valid_names) -> str | None:
    """把模型拼错的工具名纠正到最接近的合法工具名。

    策略（从严到松）：
    1. 归一化（小写、去空格/连字符）后精确命中；
    2. 一个合法名是输入的子串、或输入是合法名的子串（如 read_fil ⊂ read_file，
       searchearch_data_space ⊃ search_data_space）；
    3. 编辑距离最近，且距离 <= 阈值（按长度自适应，最多 2/3 长度）。
    返回纠正后的合法名，无法判定时返回 None（避免误纠正成无关工具）。
    """
    valid = list(valid_names)

    def norm(s: str) -> str:
        return s.lower().replace("_", "").replace("-", "").replace(" ", "")

    target = norm(name)
    if not target:
        return None

    norm_map = {norm(v): v for v in valid}
    # 1. 归一化精确命中
    if target in norm_map:
        return norm_map[target]

    # 2. 子串包含（双向）
    contains = [
        v for v in valid
        if norm(v) in target or target in norm(v)
    ]
    if len(contains) == 1:
        return contains[0]

    # 3. 编辑距离
    def lev(a: str, b: str) -> int:
        prev = list(range(len(b) + 1))
        for i, ca in enumerate(a, 1):
            cur = [i]
            for j, cb in enumerate(b, 1):
                cur.append(min(
                    prev[j] + 1,
                    cur[j - 1] + 1,
                    prev[j - 1] + (ca != cb),
                ))
            prev = cur
        return prev[-1]

    best, best_d = None, None
    for v in valid:
        d = lev(target, norm(v))
        if best_d is None or d < best_d:
            best, best_d = v, d
    if best is not None and best_d is not None:
        threshold = max(2, len(norm(best)) // 3)
        if best_d <= threshold:
            return best
    return None


_SUMMARY_BUILDERS = {
    "search_data_space": lambda a: f"正在检索：{str(a.get('query', '')).strip()[:40]}" if a.get("query") else "正在检索数据空间",
    "read_file": lambda a: f"正在读取文件 {a.get('filename', '')}".strip() if a.get("filename") else "正在读取文件",
    "inspect_data": lambda a: f"正在分析数据结构：{a.get('filename')}" if a.get("filename") else "正在分析所有数据的结构",
    "pandas_query": lambda a: f"正在用 pandas 分析 {a.get('filename', '数据')}".strip(),
    "sqlite_query": lambda a: "正在执行 SQL 查询",
    "execute_python": lambda a: "正在运行计算",
    "generate_chart": lambda a: f"正在生成图表：{a.get('title')}" if a.get("title") else "正在生成图表",
    "save_memory": lambda a: "正在记录要点",
    "nl2sql": lambda a: f"正在把问题转成查询：{str(a.get('question', '')).strip()[:40]}" if a.get("question") else "正在把问题转成查询",
    "kb_reindex_file": lambda a: f"正在更新文件索引：{a.get('filename', '')}".strip(),
    "graph_search": lambda a: f"正在搜索知识图谱：{str(a.get('query', '')).strip()[:40]}" if a.get("query") else "正在搜索知识图谱",
    "graph_traverse": lambda a: f"正在遍历实体关系：{a.get('entity', '')}".strip(),
    "graph_extract_from_text": lambda a: "正在抽取知识三元组",
    "update_plan": lambda a: "正在更新任务计划",
}


def tool_display_summary(tool_name: str, arguments: dict[str, Any]) -> str:
    """生成给终端用户看的「人话进度」描述（权威来源在后端）。

    刻意不泄露代码 / SQL / 表达式等内部细节，只说明"在干什么"。
    """
    builder = _SUMMARY_BUILDERS.get(tool_name)
    if builder:
        try:
            text = builder(arguments or {})
            if text:
                return text
        except Exception:
            pass
    return f"正在执行 {tool_name}"


async def execute_tool(tool_name: str, arguments: dict[str, Any], user_id: uuid.UUID, data_space_id: uuid.UUID | None) -> str:
    try:
        handlers = {
            "search_data_space": _tool_search,
            "read_file": _tool_read_file,
            "list_files": _tool_list_files,
            "inspect_data": _tool_inspect_data,
            "pandas_query": _tool_pandas_query,
            "sqlite_query": _tool_sqlite_query,
            "execute_python": _tool_execute_python,
            "generate_chart": lambda a, u, d: _tool_generate_chart(a),
            "save_memory": _tool_save_memory,
            "nl2sql": _tool_nl2sql,
            "kb_reindex_file": _tool_kb_reindex,
            "graph_search": _tool_graph_search,
            "graph_traverse": _tool_graph_traverse,
            "graph_extract_from_text": _tool_graph_extract,
        }
        handler = handlers.get(tool_name)
        if not handler:
            # 模型（尤其小参数量模型）常拼错工具名（如 reade_file / read_fil /
            # searchearch_data_space），严格匹配会直接浪费一整步。这里做一次
            # 容错纠正：归一化后精确命中，否则取编辑距离最近且足够相似的工具名。
            corrected = _resolve_tool_name(tool_name, handlers.keys())
            if corrected:
                handler = handlers[corrected]
                tool_name = corrected
            else:
                return f"未知工具: {tool_name}（可用工具: {', '.join(handlers.keys())}）"
        result = handler(arguments, user_id, data_space_id)
        if hasattr(result, "__await__"):
            return await result
        return result
    except Exception as e:
        return f"工具执行错误: {str(e)}"


async def _tool_search(args: dict, user_id: uuid.UUID, data_space_id: uuid.UUID | None) -> str:
    query = args.get("query", "")
    top_k = args.get("top_k", 5)
    if not data_space_id:
        return "未选择数据空间，无法搜索"

    from app.services.retrieval import get_retrieval_service
    svc = get_retrieval_service(str(data_space_id))
    # 向量检索含 ONNX 推理（同步阻塞），丢到线程池避免冻结事件循环
    import asyncio
    results = await asyncio.get_running_loop().run_in_executor(
        None, lambda: svc.search(query, top_k=top_k)
    )

    if results:
        output = []
        for r in results:
            meta = r.metadata
            filename = meta.get("filename", "?")
            # 片段放宽到整块（约 800 字）：300 字常把命中处的关键句切断，定位信号不足。
            snippet = r.text[:800]
            if len(r.text) > 800:
                snippet += "…"
            output.append(f"[{filename}] (得分: {r.score:.3f}, 来源: {r.source})\n{snippet}")
        guide = (
            "\n\n（以上是语义定位结果，只是文件里的相关片段。要看某条命中的完整上下文，"
            "用 read_file(该文件, find=\"片段里的关键短语\") 跳到该处精读——返回会给出所在页码和如何看下一处；"
            "不要为此从头整本读文件。）"
        )
        return "\n\n---\n\n".join(output) + guide

    # 回退到关键词搜索
    files = await _get_space_files(user_id, data_space_id)
    keyword_results = []
    for file in files:
        file_path = Path(settings.storage_root) / file.storage_path
        if not file_path.exists() or file.file_type not in ("txt", "md", "csv", "json", "py", "sql"):
            continue
        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
            for i, line in enumerate(content.split("\n")):
                if query.lower() in line.lower():
                    keyword_results.append(f"[{file.filename}:行{i+1}] {line.strip()[:200]}")
                    if len(keyword_results) >= top_k:
                        break
        except Exception:
            continue
        if len(keyword_results) >= top_k:
            break
    return "\n\n".join(keyword_results) if keyword_results else f"未找到与 '{query}' 相关的内容"


async def _tool_list_files(args: dict, user_id: uuid.UUID, data_space_id: uuid.UUID | None) -> str:
    """列出数据空间里的全部文件（不限类型）。

    inspect_data 只认表格、search_data_space 只给片段，二者都无法回答「这里有哪些
    文件 / 有哪些论文」。缺这个入口时模型只能猜文件名或靠 search 凑——本工具补齐
    这条干净路径：拿到准确文件名后再 read_file。"""
    if not data_space_id:
        return "未选择数据空间，无法列出文件。"
    files = await _get_space_files(user_id, data_space_id)
    if not files:
        return "当前数据空间为空，没有任何文件。"

    ext_filter = (args.get("ext") or "").strip().lstrip(".").lower()
    if ext_filter:
        files = [f for f in files if (f.file_type or "").lower() == ext_filter]
        if not files:
            return f"数据空间里没有 .{ext_filter} 文件。"

    def _fmt_size(n: int) -> str:
        n = n or 0
        if n > 1024 * 1024:
            return f"{n / 1024 / 1024:.1f}MB"
        return f"{n / 1024:.0f}KB"

    from collections import Counter
    type_counts = Counter((f.file_type or "?").lower() for f in files)
    type_summary = "、".join(f"{cnt} 个 {ext}" for ext, cnt in type_counts.most_common())

    files_sorted = sorted(files, key=lambda f: ((f.file_type or "").lower(), f.filename.lower()))
    lines = [
        f"{i+1}. {f.filename}  [{(f.file_type or '?').lower()}, {_fmt_size(f.file_size)}]"
        for i, f in enumerate(files_sorted)
    ]
    header = f"数据空间共 {len(files)} 个文件（{type_summary}）："
    return header + "\n" + "\n".join(lines)


def _read_footer(start_line: int, shown: int, total: int) -> str:
    """文本/文档分页阅读的结尾信号：明确告诉模型读完没、还剩多少行。

    没有这条信号时，模型会把读到的一页当成全文，开头读一页就概括整篇——
    这正是「讲解论文没读全就开讲」的根因，所以每次分页读都要带上。"""
    end = start_line + shown
    if end >= total:
        return f"\n---\n[已读到文件结尾：共 {total} 行，本次第 {start_line+1}-{total} 行，全文已读完]"
    remaining = total - end
    return (
        f"\n---\n[未读完：共 {total} 行，本次第 {start_line+1}-{end} 行，"
        f"后面还有 {remaining} 行未读。如需讲解/总结整篇，请用 start_line={end} 继续读到出现“全文已读完”为止。]"
    )


import re as _re_tools

_PAGE_MARKER_RE = _re_tools.compile(r"---\s*第\s*(\d+)\s*页\s*---")


def _page_at_line(lines: list[str], line_idx: int) -> int | None:
    """从某行向前回溯最近的 `--- 第 N 页 ---` 标记，推断该行所在页码。

    read_file 重建 PDF/PPTX 文本时会插入这种页标记（见 PDF/Word/PPT 分支）。
    纯文本/无标记的文档回溯不到，返回 None（只报行号，不假造页码）。"""
    for i in range(min(line_idx, len(lines) - 1), -1, -1):
        m = _PAGE_MARKER_RE.search(lines[i])
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                return None
    return None


def _find_in_lines(lines: list[str], needle: str, from_line: int) -> list[int]:
    """大小写不敏感地在 lines[from_line:] 里找 needle，返回命中行号（升序）。

    PDF 经 fitz 抽取后，一个视觉句子常被切成多行，多词短语极少落在同一行，
    所以单行整串匹配在 PDF 上几乎必然落空。这里用三级递进策略，匹配模型贴近
    用户/search 的真实用法（"把这些词附近的地方找出来"），而非要求一字不差同行：

    1) 单行整串：needle 原样落在某一行（最精确，纯文本/短词常命中）。
    2) 跨行整串：把相邻几行拼起来仍含 needle（应对 PDF 把短语拦腰切断）。
    3) 多词共现：needle 拆成词，找"这些词都出现在邻近窗口内"的起点
       （应对 "Figure 3.2 integer registers" 这类词散落在不同行的情况）。
    一旦某级有命中就返回该级结果，不再降级，保证更精确的优先。"""
    start = max(from_line, 0)
    low = [ln.lower() for ln in lines]
    nlow = needle.lower().strip()
    if not nlow:
        return []

    # 1) 单行整串
    exact = [i for i in range(start, len(low)) if nlow in low[i]]
    if exact:
        return exact

    # 2) 跨行整串：滑动拼接相邻 JOIN_SPAN 行（去掉行内多余空白后再找）
    JOIN_SPAN = 3
    import re as _re
    def _norm(s: str) -> str:
        return _re.sub(r"\s+", " ", s)
    def _dedup_adjacent(idxs: list[int], gap: int) -> list[int]:
        """合并相邻命中：间距 <= gap 视为同一处，只保留起点。
        跨行/共现匹配里同一段文字会在连续多个起点命中，不去重会把一处误报成多处。"""
        if not idxs:
            return idxs
        out = [idxs[0]]
        for x in idxs[1:]:
            if x - out[-1] > gap:
                out.append(x)
        return out
    nnorm = _norm(nlow)
    cross = []
    for i in range(start, len(low)):
        joined = _norm(" ".join(low[i:i + JOIN_SPAN]))
        if nnorm in joined:
            cross.append(i)
    if cross:
        return _dedup_adjacent(cross, JOIN_SPAN)

    # 3) 多词共现：所有词都落在 [i, i+CO_SPAN) 窗口内，返回窗口起点
    words = [w for w in _re.split(r"\s+", nnorm) if len(w) >= 2]
    if len(words) >= 2:
        CO_SPAN = 6
        co = []
        n = len(low)
        for i in range(start, n):
            window_text = " ".join(low[i:min(i + CO_SPAN, n)])
            if all(w in window_text for w in words):
                co.append(i)
        if co:
            return _dedup_adjacent(co, CO_SPAN)

    return []


def _render_find(filename: str, label: str, lines: list[str], needle: str,
                 from_line: int, window: int) -> str:
    """find 模式的统一渲染：定位关键词 → 返回命中处上下文窗口 + 页码 + 下一处导航。

    定位用「文本锚定」而非脆弱的字符偏移：search 索引基于拍平文本的 char 偏移，
    与 read_file 重建的带页标记排布对不上，直接拿偏移跳会错位，所以这里在
    read_file 自己的行表示里现找 needle，稳。"""
    total = len(lines)
    hits = _find_in_lines(lines, needle, from_line)
    if not hits:
        scope = "" if from_line <= 0 else f"（从第 {from_line+1} 行起）"
        return (
            f"文件: {filename} ({label}, 共 {total} 行)\n---\n"
            f"在文件内{scope}未找到 “{needle}”。提示：PDF 文本常被切成多行，"
            f"过长或拼凑的短语（如把图号和标题连在一起）很难命中。"
            f"改用更短、更可能原样出现的关键词重试——优先用单个专有名词/术语"
            f"（如 “integer registers”、“%rax”、“Figure 3.2” 三者分别试），"
            f"而不是一长串。仍找不到就不带 find 从该位置翻页通读。"
        )
    hit = hits[0]
    # 命中行居中开窗，受 window 约束
    half = max(window // 2, 1)
    win_start = max(hit - half, 0)
    win_end = min(win_start + window, total)
    selected = lines[win_start:win_end]
    page = _page_at_line(lines, hit)
    page_str = f"，约在第 {page} 页" if page is not None else ""
    head = (
        f"文件: {filename} ({label}, 共 {total} 行)\n"
        f"定位 “{needle}”：命中第 {hit+1} 行{page_str}，"
        f"显示上下文第 {win_start+1}-{win_end} 行\n---\n"
    )
    body = "\n".join(selected)
    # 导航 footer：还有多少处匹配、怎么看下一处、怎么扩展上下文
    later = [h for h in hits if h > hit]
    if later:
        nav = (
            f"\n---\n[本文件内 “{needle}” 共匹配 {len(hits)} 处，这是第 1 处（第 {hit+1} 行{page_str}）。"
            f"看下一处：read_file(filename, find=\"{needle}\", start_line={hit+1})；"
            f"想要这一处更多上下文：read_file(filename, start_line={win_start}, max_lines=更大值)。]"
        )
    else:
        nav = (
            f"\n---\n[本文件内 “{needle}” 只匹配这 1 处（第 {hit+1} 行{page_str}）。"
            f"想要更多上下文：read_file(filename, start_line={win_start}, max_lines=更大值)。]"
        )
    return head + body + nav


async def _tool_read_file(args: dict, user_id: uuid.UUID, data_space_id: uuid.UUID | None) -> str:
    filename = args.get("filename", "")
    start_line = args.get("start_line", 0)
    max_lines = args.get("max_lines", 800)
    find = (args.get("find") or "").strip()
    file_path = await _get_file_path(filename, user_id, data_space_id)
    if not file_path or not file_path.exists():
        return f"文件 '{filename}' 不存在或无权访问"

    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    try:
        # 表格文件：用 pandas 加载后输出为可读文本
        if ext in ("csv", "tsv", "xlsx", "xls", "json", "jsonl", "parquet", "feather", "dta", "sav", "sas7bdat"):
            if find:
                return (
                    f"文件 '{filename}' 是表格文件，find 关键词定位用于文档/文本。"
                    "要在表格里按条件找记录，请用 pandas_query / sqlite_query（WHERE/字符串包含），更准更全。"
                )
            if ext in ("xlsx", "xls"):
                from app.services.file_loader import load_excel_sheets
                sheets = load_excel_sheets(file_path)
                if not sheets:
                    return f"文件 '{filename}' 暂时无法以 Excel 工作簿方式读取"
                parts = [f"文件: {filename} (Excel 工作簿, {len(sheets)} 个工作表)"]
                for sheet_name, sheet_df in sheets.items():
                    total_rows = len(sheet_df)
                    end = min(start_line + max_lines, total_rows)
                    page = sheet_df.iloc[start_line:end]
                    parts.append(
                        f"\n## 工作表: {sheet_name} ({total_rows} 行, {len(sheet_df.columns)} 列，显示第 {start_line+1}-{end} 行)\n"
                        f"列: {', '.join(f'{c}({sheet_df[c].dtype})' for c in sheet_df.columns)}\n---\n"
                        f"{page.to_string()}"
                    )
                return "\n".join(parts)

            df = _load_df(file_path, ext)
            if df.empty:
                return f"文件 '{filename}' 暂时无法以表格方式读取，请尝试用 execute_python 工具直接处理此文件"
            total_rows = len(df)
            end = min(start_line + max_lines, total_rows)
            page = df.iloc[start_line:end]
            header = f"文件: {filename} ({total_rows} 行, {len(df.columns)} 列，显示第 {start_line+1}-{end} 行)\n"
            header += f"列: {', '.join(f'{c}({df[c].dtype})' for c in df.columns)}\n---\n"
            return header + page.to_string()

        # PDF 文件
        if ext == "pdf":
            try:
                import fitz
                doc = fitz.open(str(file_path))
                pages = []
                for i, page in enumerate(doc):
                    pages.append(f"--- 第 {i+1} 页 ---\n{page.get_text()}")
                doc.close()
                content = "\n".join(pages)
                # fitz 抽到的文本极少（扫描件/图片型 PDF）→ 回退到 OCR 全文
                if len(content.strip()) < 50:
                    ocr_text = await _get_profile_ocr_text(filename, user_id, data_space_id)
                    if ocr_text:
                        lines = ocr_text.split("\n")
                        if find:
                            return _render_find(filename, "PDF/OCR", lines, find, start_line, max_lines)
                        selected = lines[start_line:start_line + max_lines]
                        return f"文件: {filename} (PDF/OCR, {len(lines)} 行，显示第 {start_line+1}-{start_line+len(selected)} 行)\n---\n" + "\n".join(selected) + _read_footer(start_line, len(selected), len(lines))
                lines = content.split("\n")
                if find:
                    return _render_find(filename, "PDF", lines, find, start_line, max_lines)
                selected = lines[start_line:start_line + max_lines]
                return f"文件: {filename} (PDF, {len(lines)} 行，显示第 {start_line+1}-{start_line+len(selected)} 行)\n---\n" + "\n".join(selected) + _read_footer(start_line, len(selected), len(lines))
            except ImportError:
                pass

        # 图片 / 视频文件：返回 OCR 提取的文本（若有）
        if ext in ("png", "jpg", "jpeg", "gif", "bmp", "webp", "mp4", "mov", "avi", "mkv", "webm"):
            ocr_text = await _get_profile_ocr_text(filename, user_id, data_space_id)
            kind = "视频/逐帧OCR" if ext in ("mp4", "mov", "avi", "mkv", "webm") else "图片/OCR"
            if ocr_text:
                lines = ocr_text.split("\n")
                if find:
                    return _render_find(filename, kind, lines, find, start_line, max_lines)
                selected = lines[start_line:start_line + max_lines]
                return f"文件: {filename} ({kind}, {len(lines)} 行，显示第 {start_line+1}-{start_line+len(selected)} 行)\n---\n" + "\n".join(selected) + _read_footer(start_line, len(selected), len(lines))
            return f"'{filename}' 暂无可提取的文本（OCR 未配置或仍在处理中）"


        # Word / PowerPoint 文件
        if ext in ("docx", "pptx"):
            try:
                from app.services.document_text import extract_document_text
                content = extract_document_text(file_path, ext)
                lines = content.split("\n")
                label = "PowerPoint" if ext == "pptx" else "Word"
                if find:
                    return _render_find(filename, label, lines, find, start_line, max_lines)
                selected = lines[start_line:start_line + max_lines]
                return f"文件: {filename} ({label}, {len(lines)} 行，显示第 {start_line+1}-{start_line+len(selected)} 行)\n---\n" + "\n".join(selected) + _read_footer(start_line, len(selected), len(lines))
            except ImportError:
                pass

        if ext == "ppt":
            return f"文件 '{filename}' 是旧版 .ppt，暂不支持抽取文本。请转换为 .pptx 后上传。"

        # SQLite 数据库
        if ext in ("sqlite", "db", "sqlite3"):
            import sqlite3
            conn = sqlite3.connect(str(file_path))
            try:
                cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
                tables = [r[0] for r in cursor.fetchall()]
                output = [f"文件: {filename} (SQLite 数据库, {len(tables)} 个表)"]
                for t in tables[:5]:
                    count = conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
                    info = conn.execute(f'PRAGMA table_info("{t}")').fetchall()
                    cols = ", ".join(f"{r[1]}({r[2]})" for r in info)
                    output.append(f"\n表 {t} ({count} 行): {cols}")
                    sample = conn.execute(f'SELECT * FROM "{t}" LIMIT 5').fetchall()
                    if sample:
                        col_names = [r[1] for r in info]
                        output.append(pd.DataFrame(sample, columns=col_names).to_string())
                return "\n".join(output)
            finally:
                conn.close()

        # 文本文件：检测编码后读取
        from app.services.preprocessing import _detect_encoding
        encoding = _detect_encoding(file_path)
        content = file_path.read_text(encoding=encoding, errors="ignore")
        lines = content.split("\n")
        if find:
            return _render_find(filename, "文本", lines, find, start_line, max_lines)
        selected = lines[start_line:start_line + max_lines]
        return f"文件: {filename} (共 {len(lines)} 行，显示第 {start_line+1}-{start_line+len(selected)} 行)\n---\n" + "\n".join(selected) + _read_footer(start_line, len(selected), len(lines))
    except Exception as e:
        return f"读取文件失败: {str(e)}"


async def _tool_inspect_data(args: dict, user_id: uuid.UUID, data_space_id: uuid.UUID | None) -> str:
    filename = args.get("filename", "")
    if not data_space_id:
        return "未选择数据空间"

    files = await _get_space_files(user_id, data_space_id)
    _preload, df_var_by_file_id = _build_dataframe_preload(files)

    if filename:
        matches = [f for f in files if f.filename == filename]
        file_obj = matches[0] if matches else None
        if file_obj:
            file_path = Path(settings.storage_root) / file_obj.storage_path
        else:
            file_path = await _get_file_path(filename, user_id, data_space_id)
        if not file_path or not file_path.exists():
            return f"文件 '{filename}' 不存在"
        ext = filename.rsplit(".", 1)[-1].lower()
        if ext not in ("csv", "tsv", "xlsx", "xls", "json", "jsonl", "parquet", "feather", "dta", "sav", "sas7bdat"):
            return f"不支持 inspect_data 的文件类型: {ext}"
        try:
            if ext in ("xlsx", "xls"):
                from app.services.file_loader import load_excel_sheets
                sheets = load_excel_sheets(file_path)
                if not sheets:
                    return f"解析失败: Excel 工作簿没有可读取的工作表"
                info = [f"文件: {filename}", f"Excel 工作簿: {len(sheets)} 个工作表"]
                var_hint = df_var_by_file_id.get(str(file_obj.id)) if file_obj else None
                if var_hint:
                    info.append(
                        f"execute_python 专用变量: {var_hint}"
                        "（每个工作表一个变量；pandas_query 中该文件默认只读第一个工作表）"
                    )
                for sheet_name, df in sheets.items():
                    info.append(f"\n## 工作表: {sheet_name}")
                    info.append(f"行数: {len(df)}")
                    info.append(f"列数: {len(df.columns)}")
                    info.append("列信息:")
                    for col in df.columns:
                        info.append(_col_describe(df[col]))
                    info.append(f"\n前5行:\n{_df_preview(df)}")
                return "\n".join(info)

            df = _load_df(file_path, ext)
            info = [f"文件: {filename}", f"行数: {len(df)}", f"列数: {len(df.columns)}", "\n列信息:"]
            if file_obj and str(file_obj.id) in df_var_by_file_id:
                info.insert(
                    1,
                    f"execute_python 专用变量: {df_var_by_file_id[str(file_obj.id)]}"
                    "（仅 execute_python 使用；pandas_query 中该文件固定叫 df）",
                )
            for col in df.columns:
                info.append(_col_describe(df[col]))
            info.append(f"\n前5行:\n{_df_preview(df)}")
            return "\n".join(info)
        except Exception as e:
            return f"解析失败: {str(e)}"

    tabular = [f for f in files if f.file_type in ("csv", "tsv", "xlsx", "xls", "json", "jsonl", "parquet", "feather", "dta", "sav", "sas7bdat")]
    if not tabular:
        # 没有表格文件不等于「没有文件」。数据空间里常是 PDF/Word/PPT 等文档（论文、
        # 报告、讲义），inspect_data 不解析它们，但要明确告诉模型这些文件存在、叫什么，
        # 引导去 list_files/read_file，而不是回个死胡同让模型去猜文件名。
        non_tabular = [f for f in files if f not in tabular]
        if not non_tabular:
            return "当前数据空间为空，没有任何文件。"
        from collections import Counter
        type_counts = Counter((f.file_type or "?").lower() for f in non_tabular)
        type_summary = "、".join(f"{cnt} 个 {ext}" for ext, cnt in type_counts.most_common())
        names = "\n".join(
            f"  - {f.filename} [{(f.file_type or '?').lower()}]"
            for f in sorted(non_tabular, key=lambda x: x.filename.lower())
        )
        return (
            f"数据空间里没有可做表格分析的结构化文件，但有 {len(non_tabular)} 个其它文件"
            f"（{type_summary}）：\n{names}\n"
            "这些是文档/非表格文件，inspect_data 不解析它们。要查看或讲解其内容，"
            "用 read_file 逐个读取（必要时翻页读到「全文已读完」）；想要完整文件清单用 list_files。"
        )

    output = []
    all_columns: dict[str, dict[str, set]] = {}
    for f in tabular:
        fp = Path(settings.storage_root) / f.storage_path
        if not fp.exists():
            continue
        try:
            var_hint = df_var_by_file_id.get(str(f.id))
            if f.file_type in ("xlsx", "xls"):
                from app.services.file_loader import load_excel_sheets
                sheets = load_excel_sheets(fp)
                header = f"## {f.filename} (Excel 工作簿, {len(sheets)} 个工作表)"
                if var_hint:
                    header += f"\nexecute_python 专用变量: {var_hint}（每个工作表一个变量）"
                output.append(header)
                for sheet_name, df in sheets.items():
                    output.append(
                        f"### 工作表: {sheet_name} ({len(df)} 行, {len(df.columns)} 列)\n"
                        + "列: "
                        + ", ".join(f"{c}({df[c].dtype})" for c in df.columns)
                    )
                    source_name = f"{f.filename}[{sheet_name}]"
                    for col in df.columns:
                        if col not in all_columns:
                            all_columns[col] = {}
                        all_columns[col][source_name] = set(df[col].dropna().astype(str).head(500).tolist())
            else:
                df = _load_df(fp, f.file_type)
                header = f"## {f.filename} ({len(df)} 行, {len(df.columns)} 列)"
                if var_hint:
                    header += f"\nexecute_python 专用变量: {var_hint}（仅 execute_python 使用；pandas_query 中单文件固定叫 df）"
                output.append(header + "\n列: " + ", ".join(f"{c}({df[c].dtype})" for c in df.columns))
                for col in df.columns:
                    if col not in all_columns:
                        all_columns[col] = {}
                    all_columns[col][f.filename] = set(df[col].dropna().astype(str).head(500).tolist())
        except Exception:
            continue

    joins = _detect_joins(all_columns)
    if joins:
        output.append("\n## 自动检测的 Join 关系\n" + "\n".join(joins))
    return "\n\n".join(output)


def _detect_joins(all_columns: dict[str, dict[str, set]]) -> list[str]:
    """增强的 join 检测（融合 KDD-CUP 的 ID-like + link_to 模式）"""
    suggestions = []
    col_names = list(all_columns.keys())

    # 1. 同名列跨文件 Jaccard 检测
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
                    if _is_id_like(col_name):
                        tags.append("id_like")
                    suggestions.append(
                        f"  - {files[i]}.{col_name} <-> {files[j]}.{col_name} [{', '.join(tags)}] (Jaccard: {jaccard:.2f})"
                    )

    # 2. ID-like 模式匹配（customer_id <-> id, user_id <-> user_key）
    for col_a in col_names:
        if not _is_id_like(col_a):
            continue
        base_a = col_a.lower().replace("_id", "").replace("_key", "").replace("id", "").strip("_")
        if not base_a:
            continue
        for col_b in col_names:
            if col_a == col_b:
                continue
            base_b = col_b.lower().replace("_id", "").replace("_key", "").replace("id", "").strip("_")
            if base_a == base_b and col_a in all_columns and col_b in all_columns:
                for fa in all_columns[col_a]:
                    for fb in all_columns[col_b]:
                        if fa != fb:
                            suggestions.append(f"  - {fa}.{col_a} <-> {fb}.{col_b} [id_pattern]")

    # 3. link_to_X 模式（Airtable 风格）
    for col_name in col_names:
        lower = col_name.lower()
        if lower.startswith("link_to_"):
            target_base = lower[8:]
            for other_col in col_names:
                other_lower = other_col.lower()
                if other_lower in (target_base, f"{target_base}_id", f"{target_base}id"):
                    if col_name in all_columns and other_col in all_columns:
                        for fa in all_columns[col_name]:
                            for fb in all_columns[other_col]:
                                if fa != fb:
                                    suggestions.append(f"  - {fa}.{col_name} <-> {fb}.{other_col} [link_to]")

    return suggestions[:15]


def _is_id_like(name: str) -> bool:
    n = name.lower()
    return n.endswith("_id") or n.endswith("_key") or n == "id" or (n.endswith("id") and len(n) > 2 and n[-3].isalpha())


STATELESS_TOOL_HINT = (
    "提示：pandas_query / execute_python 每次调用都是全新的无状态沙箱；"
    "下一次调用不会保留本次创建的变量、筛选后的 DataFrame 或新增列。"
    "请在同一个代码块里完成读取、日期转换、派生列、聚合计算，并把最终结果赋给 result 或 print 输出。"
)


def _append_analysis_error_hint(error: str, available_vars: list[str] | None = None) -> str:
    hints = [error, STATELESS_TOOL_HINT]
    if available_vars:
        hints.append("当前可用的预加载 DataFrame 变量：" + ", ".join(sorted(available_vars)))
    if "KeyError" in error:
        hints.append(
            "KeyError 通常表示列名不存在，或派生列是在上一次工具调用里创建后丢失。"
            "请先用 inspect_data/read_file 确认真实列名；如果 month、week、duration 等是派生列，"
            "必须在同一次代码块内从原始列重新创建，例如："
            "df['month'] = pd.to_datetime(df['opened_at'], errors='coerce').dt.to_period('M').astype(str)。"
        )
    if "NameError" in error:
        hints.append(
            "NameError 通常表示 DataFrame 变量名写错或使用了上一轮工具调用中的临时变量。"
            "请查看 schema 或先调用 inspect_data，使用其中标注的 execute_python 变量名；"
            "不要假设文件 incident_records.csv 一定对应某个未确认的变量名。"
        )
    return "\n".join(hints)


def _has_explicit_result_assignment(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = []
            if isinstance(node, ast.Assign):
                targets = list(node.targets)
            else:
                targets = [node.target]
            if any(isinstance(target, ast.Name) and target.id == "result" for target in targets):
                return True
    return False


def _capture_trailing_expression(code: str) -> str:
    """把最后一行裸表达式转成 result = <expr>，模拟 notebook 的可见输出。"""
    try:
        tree = ast.parse(code, mode="exec")
    except SyntaxError:
        return code
    if not tree.body or _has_explicit_result_assignment(tree):
        return code
    last = tree.body[-1]
    if not isinstance(last, ast.Expr):
        return code
    tree.body[-1] = ast.copy_location(ast.Assign(
        targets=[ast.Name(id="result", ctx=ast.Store())],
        value=last.value,
    ), last)
    ast.fix_missing_locations(tree)
    try:
        return ast.unparse(tree)
    except Exception:
        return code


def _normalize_pandas_query_df_name(code: str) -> str:
    """pandas_query 单文件环境只有 df；把模型误用的 df_xxx 自动映射回 df。"""
    try:
        tree = ast.parse(code, mode="exec")
    except SyntaxError:
        return code

    class _DfAliasRewriter(ast.NodeTransformer):
        def visit_Name(self, node: ast.Name):
            if node.id.startswith("df_") or node.id == "ldf":
                return ast.copy_location(ast.Name(id="df", ctx=node.ctx), node)
            return node

    tree = _DfAliasRewriter().visit(tree)
    ast.fix_missing_locations(tree)
    try:
        return ast.unparse(tree)
    except Exception:
        return code


PANDAS_QUERY_DERIVED_PREAMBLE = r"""
# Auto-derived convenience columns for repeated daily analysis.
# pandas_query is stateless, so recreate common date/time fields on every call.
try:
    _date_cols = [
        c for c in df.columns
        if any(k in str(c).lower() for k in ("date", "time", "_at", "_on", "opened", "closed", "created", "updated"))
    ]
    for _c in _date_cols:
        _dt = pd.to_datetime(df[_c], errors="coerce")
        if _dt.notna().any():
            df[f"{_c}_dt"] = _dt
    _base_date_col = None
    for _candidate in ("opened_at", "created_at", "date", "time", "sys_created_on", "sys_updated_on"):
        if f"{_candidate}_dt" in df.columns:
            _base_date_col = f"{_candidate}_dt"
            break
        if _candidate in df.columns:
            _base_date_col = _candidate
            break
    if _base_date_col is not None:
        _base_dt = pd.to_datetime(df[_base_date_col], errors="coerce")
        if "month" not in df.columns:
            df["month"] = _base_dt.dt.to_period("M").astype(str)
        if "week" not in df.columns:
            df["week"] = _base_dt.dt.isocalendar().week.astype("Int64")
        if "day_of_week" not in df.columns:
            df["day_of_week"] = _base_dt.dt.day_name()
    if "duration_hours" not in df.columns and "opened_at_dt" in df.columns and "closed_at_dt" in df.columns:
        df["duration_hours"] = (df["closed_at_dt"] - df["opened_at_dt"]).dt.total_seconds() / 3600
except Exception:
    pass
"""


async def _tool_pandas_query(args: dict, user_id: uuid.UUID, data_space_id: uuid.UUID | None) -> str:
    filename = args.get("filename", "")
    expression = args.get("expression", "")

    file_path = await _get_file_path(filename, user_id, data_space_id)
    if not file_path or not file_path.exists():
        return f"文件 '{filename}' 不存在或无权访问"

    ext = filename.rsplit(".", 1)[-1].lower()
    kind = {"csv": "csv", "xlsx": "excel", "xls": "excel", "json": "json"}.get(ext)
    if not kind:
        return f"pandas_query 暂不支持 .{ext} 文件，请用 read_file 或 execute_python 工具"
    if ext in ("xlsx", "xls"):
        try:
            from app.services.file_loader import load_excel_sheets
            sheet_names = list(load_excel_sheets(file_path, nrows=1).keys())
        except Exception:
            sheet_names = []
        if len(sheet_names) > 1:
            return (
                f"查询执行错误: '{filename}' 是多工作表 Excel（{', '.join(sheet_names)}）。"
                "pandas_query 为避免静默只读第一个工作表，已停止执行。"
                "请先用 inspect_data 查看每个工作表对应的 execute_python 变量，"
                "或用 sqlite_query 查询自动展开后的 SQL 表。"
            )

    # 把表达式包装成给 result 赋值，交给隔离沙箱执行（df 已在子进程内预加载）
    from app.agent.sandbox import run_in_sandbox
    # 单表达式优先；多行代码则自动捕获最后一行裸表达式，减少静默执行。
    code = expression
    try:
        ast.parse(expression, mode="eval")
        code = f"result = ({expression})"
    except SyntaxError:
        code = _capture_trailing_expression(expression)
    code = _normalize_pandas_query_df_name(code)
    code = PANDAS_QUERY_DERIVED_PREAMBLE + "\n" + code

    preload = {"df": (kind, str(file_path))}
    r = run_in_sandbox(code, preload=preload,
                       cpu_seconds=10, wall_timeout=30)
    if not r.get("ok"):
        return "查询执行错误: " + _append_analysis_error_hint(r.get("error", "查询执行失败"), ["df"])
    if r.get("result") is not None:
        out = r["result"]
        # DataFrame.to_string 可能很长。放宽到 6 万字符，让"列出全部"类结果完整返回；
        # 仍超限才截断并提示改用聚合。
        if len(out) > 60000:
            return out[:60000] + "\n...(结果过大已截断，建议用聚合/筛选缩小范围或分批查询)"
        return out
    if r.get("stdout"):
        return r["stdout"][:60000]
    return (
        "查询执行错误: 本次 pandas_query 没有产生可见输出。"
        "请在同一个 expression 里把最终表格/指标赋给 result，或让最后一行成为要返回的表达式。\n"
        + STATELESS_TOOL_HINT
    )


async def _tool_sqlite_query(args: dict, user_id: uuid.UUID, data_space_id: uuid.UUID | None) -> str:
    sql = args.get("sql", "")
    if not data_space_id:
        return "未选择数据空间"

    from app.services.sqlite_engine import load_space_to_sqlite, execute_query, list_tables
    db_path = await load_space_to_sqlite(data_space_id, user_id)

    if sql.strip().upper().startswith("SHOW") or sql.strip() == "":
        tables = list_tables(db_path)
        output = "数据库中的表:\n"
        for t in tables:
            cols = ", ".join(f"{c['name']}({c['type']})" for c in t["columns"])
            output += f"  - {t['name']} ({t['row_count']} 行): {cols}\n"
        return output

    result = execute_query(db_path, sql)
    if "error" in result:
        return f"SQL 错误: {result['error']}"

    if not result["rows"]:
        return "查询返回空结果"

    df = pd.DataFrame(result["rows"])
    output = f"返回 {result['row_count']} 行"
    if result.get("truncated"):
        output += "（结果较大，已截断至前 10000 行；如需完整数据请用更精确的 WHERE/聚合缩小范围，或分批查询）"
    # 强制输出全部行（默认 to_string 超过 display.max_rows 会省略中间行），
    # 否则列表型答案会被显示截断，导致 recall 偏低。
    output += f"\n{df.to_string(max_rows=None)}"
    return output


async def _tool_execute_python(args: dict, user_id: uuid.UUID, data_space_id: uuid.UUID | None) -> str:
    code = _capture_trailing_expression(args.get("code", ""))

    # 收集数据空间文件，按文件名生成 df_xxx 变量供子进程预加载
    preload = {}
    if data_space_id:
        files = await _get_space_files(user_id, data_space_id)
        preload, _filename_to_var = _build_dataframe_preload(files)
    if not preload:
        return (
            "代码执行错误: 当前数据空间没有可预加载为 DataFrame 的 CSV/Excel/JSON 文件。"
            "如需分析其它格式，请先用 read_file 查看内容，或使用 sqlite_query/专用工具。"
        )

    # 交给加固沙箱：静态检查 + 隔离子进程 + 资源限额 + 文件路径守卫
    from app.agent.sandbox import run_in_sandbox
    r = run_in_sandbox(code, preload=preload, cpu_seconds=10, wall_timeout=30)

    if not r.get("ok"):
        return "代码执行错误: " + _append_analysis_error_hint(
            r.get("error", "未知错误"),
            list(preload.keys()),
        )

    parts = []
    stdout_text = r.get("stdout") or ""
    if len(stdout_text) > 60000:
        stdout_text = stdout_text[:60000] + "\n...(输出过大已截断，建议用聚合/筛选缩小范围)"
    if stdout_text:
        parts.append(f"输出:\n{stdout_text}")
    if r.get("result") is not None:
        parts.append(f"result = {r['result'][:60000]}")
    stderr_text = r.get("stderr") or ""
    if stderr_text:
        parts.append(f"警告:\n{stderr_text[:2000]}")
    if not parts:
        parts.append(
            "代码执行错误: 本次 execute_python 没有产生可见输出。"
            "请把最终表格/指标赋给 result，或用 print 输出关键结果。\n"
            + STATELESS_TOOL_HINT
        )
    return "\n".join(parts)[:120000]


def _tool_generate_chart(args: dict) -> str:
    # 模型有时把 data 当 JSON 字符串传（尤其是 OpenAI 兼容模型），统一解析成对象
    data = args.get("data", {})
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except (json.JSONDecodeError, TypeError):
            pass
    chart_spec = {
        "chart_type": args.get("chart_type", "bar"),
        "title": args.get("title", ""),
        "data": data,
        "x_label": args.get("x_label", ""),
        "y_label": args.get("y_label", ""),
    }
    return "```chart\n" + json.dumps(chart_spec, ensure_ascii=False) + "\n```"


async def _tool_save_memory(args: dict, user_id: uuid.UUID, data_space_id: uuid.UUID | None) -> str:
    content = args.get("content", "")
    kind = args.get("kind", "fact")
    scope = args.get("scope", "session")
    if not content:
        return "记忆内容不能为空"

    from app.services.memory import store_memory
    memory_id = await store_memory(
        user_id=user_id,
        content=content,
        scope=scope,
        kind=kind,
        data_space_id=data_space_id,
    )
    return f"已保存记忆 (ID: {memory_id})"


async def _tool_nl2sql(args: dict, user_id: uuid.UUID, data_space_id: uuid.UUID | None) -> str:
    """自然语言转 SQL 并执行"""
    if not data_space_id:
        return "未选择数据空间"
    question = args.get("question", "")
    if not question:
        return "请提供要查询的问题"

    from app.services.nl2sql import generate_and_execute
    return await generate_and_execute(question, user_id, data_space_id)


async def _tool_kb_reindex(args: dict, user_id: uuid.UUID, data_space_id: uuid.UUID | None) -> str:
    """重新索引文件"""
    if not data_space_id:
        return "未选择数据空间"
    filename = args.get("filename", "")
    if not filename:
        return "请指定文件名"

    from app.services.ingest import IngestService
    svc = IngestService(user_id, data_space_id)
    result = await svc.kb_reindex_file(filename)
    if "error" in result:
        return result["error"]
    return f"已重新索引 '{filename}'，生成 {result['chunks_indexed']} 个文本块"


async def _tool_graph_search(args: dict, user_id: uuid.UUID, data_space_id: uuid.UUID | None) -> str:
    """搜索知识图谱中的实体"""
    if not data_space_id:
        return "未选择数据空间，无法搜索图谱"
    query = args.get("query", "")
    top_k = args.get("top_k", 5)
    if not query:
        return "请提供搜索关键词"

    from app.services.graph import GraphService
    gs = GraphService(str(user_id), str(data_space_id))
    results = await gs.search_entities(query, top_k=top_k)
    if not results:
        return f"图谱中未找到与 '{query}' 相关的实体"

    lines = [f"找到 {len(results)} 个相关实体："]
    for r in results:
        neighbors = await gs.neighbors(r["id"])
        neighbor_str = ", ".join(f"{n['relation']}→{n['entity']}" for n in neighbors[:3])
        lines.append(f"  - {r['label']} (类型: {r['type']}, 连接: {r['degree']}){' | ' + neighbor_str if neighbor_str else ''}")
    return "\n".join(lines)


async def _tool_graph_traverse(args: dict, user_id: uuid.UUID, data_space_id: uuid.UUID | None) -> str:
    """从实体出发遍历知识图谱"""
    if not data_space_id:
        return "未选择数据空间"
    entity = args.get("entity", "")
    max_hops = args.get("max_hops", 2)
    if not entity:
        return "请指定起始实体名称"

    from app.services.graph import GraphService
    gs = GraphService(str(user_id), str(data_space_id))
    paths = await gs.traverse(entity, max_hops=max_hops)
    if not paths:
        return f"图谱中未找到实体 '{entity}' 或该实体没有关系路径"

    lines = [f"从 '{entity}' 出发，发现 {len(paths)} 条关系路径："]
    for p in paths[:20]:
        steps = " → ".join(f"{s['from']} --[{s['relation']}]--> {s['to']}" for s in p["path"])
        lines.append(f"  [{p['depth']}跳] {steps}")
    return "\n".join(lines)


async def _tool_graph_extract(args: dict, user_id: uuid.UUID, data_space_id: uuid.UUID | None) -> str:
    """从文本中抽取三元组存入图谱"""
    if not data_space_id:
        return "未选择数据空间"
    text = args.get("text", "")
    max_triples = args.get("max_triples", 30)
    if not text:
        return "请提供要抽取的文本内容"

    from app.services.graph import GraphService
    gs = GraphService(str(user_id), str(data_space_id))
    result = await gs.extract_triples_from_text(text, max_triples=max_triples)
    added = result.get("added", 0)
    if added == 0:
        return "未从文本中抽取到三元组"

    lines = [f"已抽取 {added} 个三元组并存入图谱（共 {result.get('total_nodes', 0)} 节点, {result.get('total_edges', 0)} 条边）："]
    for t in result.get("triples", [])[:10]:
        lines.append(f"  - {t.get('subject', '?')} --[{t.get('relation', '?')}]--> {t.get('object', '?')}")
    return "\n".join(lines)
