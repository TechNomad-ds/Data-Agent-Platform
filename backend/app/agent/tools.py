"""Agent 工具定义与执行 - 增强版"""
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
    if ext == "csv":
        from app.services.preprocessing import _detect_encoding
        encoding = _detect_encoding(file_path)
        return pd.read_csv(file_path, encoding=encoding, on_bad_lines="skip")
    elif ext == "tsv":
        from app.services.preprocessing import _detect_encoding
        encoding = _detect_encoding(file_path)
        return pd.read_csv(file_path, sep="\t", encoding=encoding, on_bad_lines="skip")
    elif ext in ("xlsx", "xls"):
        return pd.read_excel(file_path)
    elif ext == "parquet":
        return pd.read_parquet(file_path)
    elif ext == "feather":
        return pd.read_feather(file_path)
    elif ext == "json":
        content = file_path.read_text(encoding="utf-8")
        data = json.loads(content)
        if isinstance(data, list):
            return pd.DataFrame(data)
        elif isinstance(data, dict) and "records" in data:
            return pd.DataFrame(data["records"])
        elif isinstance(data, dict):
            return pd.DataFrame([data])
    elif ext == "jsonl":
        return pd.read_json(file_path, lines=True)
    return pd.DataFrame()


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

    from app.services import embedding as embed_svc
    results = embed_svc.search(str(data_space_id), query, top_k=top_k)
    if results:
        output = []
        for r in results:
            meta = r.get("metadata", {})
            output.append(f"[{meta.get('filename', '?')}] (相似度: {1 - r.get('distance', 0):.2f})\n{r['text'][:300]}")
        return "\n\n---\n\n".join(output)

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
    try:
        content = file_path.read_text(encoding="utf-8", errors="ignore")
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
        if ext not in ("csv", "xlsx", "xls", "json"):
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
    tabular = [f for f in files if f.file_type in ("csv", "xlsx", "xls", "json")]
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
    suggestions = []
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
                    suggestions.append(f"  - {files[i]}.{col_name} <-> {files[j]}.{col_name} (Jaccard: {jaccard:.2f})")
    return suggestions[:10]


async def _tool_pandas_query(args: dict, user_id: uuid.UUID, data_space_id: uuid.UUID | None) -> str:
    filename = args.get("filename", "")
    expression = args.get("expression", "")

    try:
        tree = ast.parse(expression, mode="eval")
        for node in ast.walk(tree):
            if isinstance(node, ast.Import | ast.ImportFrom):
                return "安全限制：不允许 import"
            if isinstance(node, ast.Attribute) and isinstance(node.attr, str) and node.attr.startswith("__"):
                return "安全限制：不允许访问 dunder 属性"
    except SyntaxError as e:
        return f"表达式语法错误: {e}"

    file_path = await _get_file_path(filename, user_id, data_space_id)
    if not file_path or not file_path.exists():
        return f"文件 '{filename}' 不存在或无权访问"

    ext = filename.rsplit(".", 1)[-1].lower()
    try:
        df = _load_df(file_path, ext)
        local_vars = {"df": df, "pd": pd, "np": np, "len": len, "min": min, "max": max, "sum": sum, "abs": abs, "round": round, "sorted": sorted, "set": set, "list": list}
        result = eval(expression, {"__builtins__": {}}, local_vars)
        if isinstance(result, pd.DataFrame):
            if len(result) > 50:
                return f"结果共 {len(result)} 行，显示前50行:\n{result.head(50).to_string()}"
            return result.to_string()
        elif isinstance(result, pd.Series):
            return result.to_string()
        return str(result)
    except Exception as e:
        return f"查询执行失败: {str(e)}"


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
    dangerous_patterns = ["import os", "import sys", "import subprocess", "import shutil", "os.system", "os.popen", "subprocess.", "__import__", "import socket", "import requests"]
    for pattern in dangerous_patterns:
        if pattern in code:
            return f"安全限制：不允许使用 '{pattern}'"

    file_paths = {}
    if data_space_id:
        files = await _get_space_files(user_id, data_space_id)
        for f in files:
            full_path = Path(settings.storage_root) / f.storage_path
            file_paths[f.filename] = str(full_path)

    import io
    import sys
    from contextlib import redirect_stdout, redirect_stderr

    stdout_capture = io.StringIO()
    stderr_capture = io.StringIO()

    ALLOWED_MODULES = {"pandas", "numpy", "json", "math", "statistics", "collections", "itertools", "functools", "re", "datetime"}

    def _safe_import(name, *a, **kw):
        if name not in ALLOWED_MODULES:
            raise ImportError(f"不允许导入: {name}")
        return __import__(name, *a, **kw)

    safe_builtins = {
        "__import__": _safe_import,
        "abs": abs, "all": all, "any": any, "bool": bool, "dict": dict,
        "enumerate": enumerate, "filter": filter, "float": float, "format": format,
        "int": int, "isinstance": isinstance, "iter": iter, "len": len, "list": list,
        "map": map, "max": max, "min": min, "next": next, "print": print,
        "range": range, "repr": repr, "reversed": reversed, "round": round,
        "set": set, "slice": slice, "sorted": sorted, "str": str, "sum": sum,
        "tuple": tuple, "type": type, "zip": zip,
        "True": True, "False": False, "None": None,
        "ValueError": ValueError, "TypeError": TypeError, "KeyError": KeyError,
        "IndexError": IndexError, "Exception": Exception,
    }

    exec_globals = {"__builtins__": safe_builtins, "pd": pd, "np": np, "json": json, "FILES": file_paths}

    for fname, fpath in file_paths.items():
        var_name = fname.rsplit(".", 1)[0].replace(" ", "_").replace("-", "_").lower()
        ext = fname.rsplit(".", 1)[-1].lower()
        try:
            if ext == "csv":
                exec_globals[f"df_{var_name}"] = pd.read_csv(fpath)
            elif ext in ("xlsx", "xls"):
                exec_globals[f"df_{var_name}"] = pd.read_excel(fpath)
            elif ext == "json":
                exec_globals[f"df_{var_name}"] = _load_df(Path(fpath), "json")
        except Exception:
            pass

    try:
        with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
            exec(code, exec_globals)
        stdout = stdout_capture.getvalue()
        stderr = stderr_capture.getvalue()
        parts = []
        if stdout:
            parts.append(f"输出:\n{stdout}")
        if stderr:
            parts.append(f"警告:\n{stderr}")
        if not parts:
            parts.append("代码执行成功（无输出）")
        return "\n".join(parts)[:5000]
    except Exception as e:
        return f"代码执行错误: {type(e).__name__}: {str(e)}"


def _tool_generate_chart(args: dict) -> str:
    chart_spec = {
        "chart_type": args.get("chart_type", "bar"),
        "title": args.get("title", ""),
        "data": args.get("data", {}),
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
