"""Agent 工具定义与执行 - 融合 DataMind + KDD-CUP 能力"""
import uuid
import json
import ast
import os
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
                "description": "在当前数据空间中搜索与查询相关的内容片段（支持向量语义搜索）",
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
                "description": "读取数据空间中指定文件的内容。对于大文件可以指定起始行和行数",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "filename": {"type": "string", "description": "文件名"},
                        "start_line": {"type": "integer", "description": "起始行号（从0开始）", "default": 0},
                        "max_lines": {"type": "integer", "description": "最大读取行数", "default": 100},
                    },
                    "required": ["filename"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "inspect_data",
                "description": "查看结构化数据文件(CSV/Excel/JSON)的 schema、列信息、样本数据和跨文件 join 建议",
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
                "description": "对 CSV/Excel/JSON 文件执行 pandas 查询表达式。数据已加载为 df 变量",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "filename": {"type": "string", "description": "数据文件名"},
                        "expression": {"type": "string", "description": "pandas 表达式，例如 df.describe()、df.groupby('col').sum()"},
                    },
                    "required": ["filename", "expression"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "sqlite_query",
                "description": "对数据空间中的所有表格数据执行 SQL 查询。表名为文件名（去扩展名，小写，下划线替换空格）。只支持 SELECT 查询",
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
                "description": "执行 Python 代码进行数据分析。数据空间中的文件已预加载为 DataFrame 变量（如 df_patient）。可用库：pandas(pd)、numpy(np)、json、math、statistics",
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
                "description": "用自然语言描述你想查询的内容，自动生成 SQL 并执行。适合复杂的多表查询场景",
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
                "name": "db_import_csv",
                "description": "将 CSV/TSV 文件导入为 SQL 表。导入后可用 sqlite_query 查询该表",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "filename": {"type": "string", "description": "CSV/TSV 文件名"},
                        "table_name": {"type": "string", "description": "导入后的表名"},
                    },
                    "required": ["filename", "table_name"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "graph_search",
                "description": "在知识图谱中搜索实体。返回匹配的节点及其连接度",
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
                "description": "从指定实体出发，遍历知识图谱中的关系路径。可发现多跳关系",
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
                "description": "从文本中用 LLM 抽取实体关系三元组并存入知识图谱",
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
        result = await db.execute(query)
        file = result.scalar_one_or_none()
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


def _load_df(file_path: Path, ext: str) -> pd.DataFrame:
    from app.services.file_loader import load_dataframe
    return load_dataframe(file_path, ext)


async def execute_tool(tool_name: str, arguments: dict[str, Any], user_id: uuid.UUID, data_space_id: uuid.UUID | None) -> str:
    try:
        handlers = {
            "search_data_space": _tool_search,
            "read_file": _tool_read_file,
            "inspect_data": _tool_inspect_data,
            "pandas_query": _tool_pandas_query,
            "sqlite_query": _tool_sqlite_query,
            "execute_python": _tool_execute_python,
            "generate_chart": lambda a, u, d: _tool_generate_chart(a),
            "save_memory": _tool_save_memory,
            "nl2sql": _tool_nl2sql,
            "kb_reindex_file": _tool_kb_reindex,
            "db_import_csv": _tool_db_import_csv,
            "graph_search": _tool_graph_search,
            "graph_traverse": _tool_graph_traverse,
            "graph_extract_from_text": _tool_graph_extract,
        }
        handler = handlers.get(tool_name)
        if not handler:
            return f"未知工具: {tool_name}"
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
            output.append(f"[{filename}] (得分: {r.score:.3f}, 来源: {r.source})\n{r.text[:300]}")
        return "\n\n---\n\n".join(output)

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


async def _tool_read_file(args: dict, user_id: uuid.UUID, data_space_id: uuid.UUID | None) -> str:
    filename = args.get("filename", "")
    start_line = args.get("start_line", 0)
    max_lines = args.get("max_lines", 100)
    file_path = await _get_file_path(filename, user_id, data_space_id)
    if not file_path or not file_path.exists():
        return f"文件 '{filename}' 不存在或无权访问"

    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    try:
        # 表格文件：用 pandas 加载后输出为可读文本
        if ext in ("csv", "tsv", "xlsx", "xls", "json", "jsonl", "parquet", "feather", "dta", "sav", "sas7bdat"):
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
                lines = content.split("\n")
                selected = lines[start_line:start_line + max_lines]
                return f"文件: {filename} (PDF, {len(lines)} 行，显示第 {start_line+1}-{start_line+len(selected)} 行)\n---\n" + "\n".join(selected)
            except ImportError:
                pass

        # Word 文件
        if ext == "docx":
            try:
                from docx import Document
                doc = Document(str(file_path))
                content = "\n".join(p.text for p in doc.paragraphs)
                lines = content.split("\n")
                selected = lines[start_line:start_line + max_lines]
                return f"文件: {filename} (Word, {len(lines)} 行，显示第 {start_line+1}-{start_line+len(selected)} 行)\n---\n" + "\n".join(selected)
            except ImportError:
                pass

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
        selected = lines[start_line:start_line + max_lines]
        return f"文件: {filename} (共 {len(lines)} 行，显示第 {start_line+1}-{start_line+len(selected)} 行)\n---\n" + "\n".join(selected)
    except Exception as e:
        return f"读取文件失败: {str(e)}"


async def _tool_inspect_data(args: dict, user_id: uuid.UUID, data_space_id: uuid.UUID | None) -> str:
    filename = args.get("filename", "")
    if not data_space_id:
        return "未选择数据空间"

    if filename:
        file_path = await _get_file_path(filename, user_id, data_space_id)
        if not file_path or not file_path.exists():
            return f"文件 '{filename}' 不存在"
        ext = filename.rsplit(".", 1)[-1].lower()
        if ext not in ("csv", "tsv", "xlsx", "xls", "json", "jsonl", "parquet", "feather", "dta", "sav", "sas7bdat"):
            return f"不支持 inspect_data 的文件类型: {ext}"
        try:
            df = _load_df(file_path, ext)
            info = [f"文件: {filename}", f"行数: {len(df)}", f"列数: {len(df.columns)}", "\n列信息:"]
            for col in df.columns:
                non_null = int(df[col].notna().sum())
                unique = int(df[col].nunique())
                sample = str(df[col].dropna().iloc[0])[:50] if non_null > 0 else "N/A"
                info.append(f"  - {col}: {df[col].dtype} ({non_null}/{len(df)} 非空, {unique} 唯一值, 示例: {sample})")
            info.append(f"\n前5行:\n{df.head(5).to_string()}")
            return "\n".join(info)
        except Exception as e:
            return f"解析失败: {str(e)}"

    files = await _get_space_files(user_id, data_space_id)
    tabular = [f for f in files if f.file_type in ("csv", "tsv", "xlsx", "xls", "json", "jsonl", "parquet", "feather", "dta", "sav", "sas7bdat")]
    if not tabular:
        return "数据空间中没有表格文件"

    output = []
    all_columns: dict[str, dict[str, set]] = {}
    for f in tabular:
        fp = Path(settings.storage_root) / f.storage_path
        if not fp.exists():
            continue
        try:
            df = _load_df(fp, f.file_type)
            output.append(f"## {f.filename} ({len(df)} 行, {len(df.columns)} 列)\n列: " + ", ".join(f"{c}({df[c].dtype})" for c in df.columns))
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

    # 把表达式包装成给 result 赋值，交给隔离沙箱执行（df 已在子进程内预加载）
    from app.agent.sandbox import run_in_sandbox
    # 单表达式优先；若本身是多行语句则原样执行（用户需自行赋值给 result）
    code = expression
    try:
        ast.parse(expression, mode="eval")
        code = f"result = ({expression})"
    except SyntaxError:
        pass

    preload = {"df": (kind, str(file_path))}
    r = run_in_sandbox(code, preload=preload,
                       cpu_seconds=10, wall_timeout=30)
    if not r.get("ok"):
        return r.get("error", "查询执行失败")
    if r.get("result") is not None:
        out = r["result"]
        # DataFrame.to_string 可能很长，截断
        if len(out) > 6000:
            return out[:6000] + "\n...(结果已截断)"
        return out
    if r.get("stdout"):
        return r["stdout"][:6000]
    return "执行完成（无返回值，可将结果赋给 result 变量）"


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
        output += "（已截断至200行）"
    output += f"\n{df.to_string()}"
    return output


async def _tool_execute_python(args: dict, user_id: uuid.UUID, data_space_id: uuid.UUID | None) -> str:
    code = args.get("code", "")

    # 收集数据空间文件，按文件名生成 df_xxx 变量供子进程预加载
    preload = {}
    if data_space_id:
        files = await _get_space_files(user_id, data_space_id)
        for f in files:
            full_path = Path(settings.storage_root) / f.storage_path
            ext = f.filename.rsplit(".", 1)[-1].lower()
            kind = {"csv": "csv", "xlsx": "excel", "xls": "excel", "json": "json"}.get(ext)
            if not kind:
                continue
            var = f.filename.rsplit(".", 1)[0].replace(" ", "_").replace("-", "_").lower()
            preload[f"df_{var}"] = (kind, str(full_path))

    # 交给加固沙箱：静态检查 + 隔离子进程 + 资源限额 + 文件路径守卫
    from app.agent.sandbox import run_in_sandbox
    r = run_in_sandbox(code, preload=preload, cpu_seconds=10, wall_timeout=30)

    if not r.get("ok"):
        return f"代码执行错误: {r.get('error', '未知错误')}"

    parts = []
    stdout_text = r.get("stdout") or ""
    if len(stdout_text) > 10000:
        stdout_text = stdout_text[:10000] + "\n...(输出已截断)"
    if stdout_text:
        parts.append(f"输出:\n{stdout_text}")
    if r.get("result") is not None:
        parts.append(f"result = {r['result'][:4000]}")
    stderr_text = r.get("stderr") or ""
    if stderr_text:
        parts.append(f"警告:\n{stderr_text[:2000]}")
    if not parts:
        parts.append("代码执行成功（无输出，可将结果赋给 result 变量以便查看）")
    return "\n".join(parts)[:12000]


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


async def _tool_db_import_csv(args: dict, user_id: uuid.UUID, data_space_id: uuid.UUID | None) -> str:
    """将 CSV 导入为 SQL 表"""
    if not data_space_id:
        return "未选择数据空间"
    filename = args.get("filename", "")
    table_name = args.get("table_name", "")
    if not filename or not table_name:
        return "请指定文件名和表名"

    from app.services.ingest import IngestService
    svc = IngestService(user_id, data_space_id)
    result = await svc.db_import_csv(filename, table_name)
    if "error" in result:
        return result["error"]
    return f"已将 '{filename}' 导入为表 '{result['table_name']}'（{result['row_count']} 行, {result['column_count']} 列）。现在可以用 sqlite_query 查询该表。"


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
