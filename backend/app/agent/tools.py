"""Agent 工具定义与执行"""
import uuid
import json
import os
from pathlib import Path
from typing import Any

import pandas as pd
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
                "description": "在当前数据空间中搜索与查询相关的内容片段",
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
                "description": "查看结构化数据文件(CSV/Excel/JSON)的 schema、列信息和样本数据",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "filename": {"type": "string", "description": "文件名"},
                    },
                    "required": ["filename"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "pandas_query",
                "description": "对 CSV/Excel/JSON 文件执行 pandas 查询表达式。数据已加载为 df 变量。JSON 文件中的 records 数组会自动转为 DataFrame",
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
                "name": "execute_python",
                "description": "执行 Python 代码进行数据分析。数据空间中的文件已预加载为 DataFrame 变量（文件名去掉扩展名并转小写，如 Patient.json -> df_patient）。可用库：pandas(pd)、numpy(np)、json。FILES 字典包含文件名到路径的映射",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "code": {"type": "string", "description": "要执行的 Python 代码"},
                    },
                    "required": ["code"],
                },
            },
        },
    ]


async def _get_file_path(filename: str, user_id: uuid.UUID, data_space_id: uuid.UUID | None) -> Path | None:
    """安全地获取文件路径，确保用户权限"""
    async with get_session_factory()() as db:
        query = select(File).where(File.user_id == user_id, File.filename == filename)
        if data_space_id:
            query = (
                select(File)
                .join(DataSpaceFile, DataSpaceFile.file_id == File.id)
                .where(
                    File.user_id == user_id,
                    File.filename == filename,
                    DataSpaceFile.data_space_id == data_space_id,
                )
            )
        result = await db.execute(query)
        file = result.scalar_one_or_none()
        if not file:
            return None
        return Path(settings.storage_root) / file.storage_path


async def execute_tool(
    tool_name: str,
    arguments: dict[str, Any],
    user_id: uuid.UUID,
    data_space_id: uuid.UUID | None,
) -> str:
    """执行工具并返回结果"""
    try:
        if tool_name == "search_data_space":
            return await _tool_search(arguments, user_id, data_space_id)
        elif tool_name == "read_file":
            return await _tool_read_file(arguments, user_id, data_space_id)
        elif tool_name == "inspect_data":
            return await _tool_inspect_data(arguments, user_id, data_space_id)
        elif tool_name == "pandas_query":
            return await _tool_pandas_query(arguments, user_id, data_space_id)
        elif tool_name == "execute_python":
            return await _tool_execute_python(arguments, user_id, data_space_id)
        else:
            return f"未知工具: {tool_name}"
    except Exception as e:
        return f"工具执行错误: {str(e)}"


async def _tool_search(args: dict, user_id: uuid.UUID, data_space_id: uuid.UUID | None) -> str:
    """搜索数据空间内容（简单关键词匹配，后续接入向量检索）"""
    query = args.get("query", "")
    top_k = args.get("top_k", 5)

    if not data_space_id:
        return "未选择数据空间，无法搜索"

    # 获取数据空间中的所有文件
    async with get_session_factory()() as db:
        result = await db.execute(
            select(File)
            .join(DataSpaceFile, DataSpaceFile.file_id == File.id)
            .where(DataSpaceFile.data_space_id == data_space_id, File.user_id == user_id)
        )
        files = result.scalars().all()

    results = []
    for file in files:
        file_path = Path(settings.storage_root) / file.storage_path
        if not file_path.exists():
            continue

        # 对文本文件进行简单关键词搜索
        if file.file_type in ("txt", "md", "csv", "json", "py", "sql", "html", "xml"):
            try:
                content = file_path.read_text(encoding="utf-8", errors="ignore")
                lines = content.split("\n")
                for i, line in enumerate(lines):
                    if query.lower() in line.lower():
                        context_start = max(0, i - 1)
                        context_end = min(len(lines), i + 2)
                        snippet = "\n".join(lines[context_start:context_end])
                        results.append(f"[{file.filename}:行{i+1}]\n{snippet}")
                        if len(results) >= top_k:
                            break
            except Exception:
                continue

        if len(results) >= top_k:
            break

    if not results:
        return f"未找到与 '{query}' 相关的内容"

    return "\n\n---\n\n".join(results[:top_k])


async def _tool_read_file(args: dict, user_id: uuid.UUID, data_space_id: uuid.UUID | None) -> str:
    """读取文件内容"""
    filename = args.get("filename", "")
    start_line = args.get("start_line", 0)
    max_lines = args.get("max_lines", 100)

    file_path = await _get_file_path(filename, user_id, data_space_id)
    if not file_path or not file_path.exists():
        return f"文件 '{filename}' 不存在或无权访问"

    try:
        content = file_path.read_text(encoding="utf-8", errors="ignore")
        lines = content.split("\n")
        total_lines = len(lines)
        selected = lines[start_line:start_line + max_lines]
        result = "\n".join(selected)

        header = f"文件: {filename} (共 {total_lines} 行，显示第 {start_line+1}-{start_line+len(selected)} 行)\n"
        return header + "---\n" + result
    except Exception as e:
        return f"读取文件失败: {str(e)}"


def _load_json_as_df(file_path: Path) -> pd.DataFrame:
    """将 JSON 文件加载为 DataFrame，支持 {table, records} 和纯数组格式"""
    content = file_path.read_text(encoding="utf-8")
    data = json.loads(content)
    if isinstance(data, list):
        return pd.DataFrame(data)
    elif isinstance(data, dict) and "records" in data:
        return pd.DataFrame(data["records"])
    else:
        raise ValueError("JSON 格式不支持直接转为表格，请使用 read_file 查看原始内容")


async def _tool_inspect_data(args: dict, user_id: uuid.UUID, data_space_id: uuid.UUID | None) -> str:
    """查看结构化数据的 schema"""
    filename = args.get("filename", "")

    file_path = await _get_file_path(filename, user_id, data_space_id)
    if not file_path or not file_path.exists():
        return f"文件 '{filename}' 不存在或无权访问"

    ext = filename.rsplit(".", 1)[-1].lower()

    try:
        if ext == "csv":
            df = pd.read_csv(file_path)
        elif ext in ("xlsx", "xls"):
            df = pd.read_excel(file_path)
        elif ext == "json":
            df = _load_json_as_df(file_path)
        else:
            return f"不支持 inspect_data 的文件类型: {ext}"

        info = []
        info.append(f"文件: {filename}")
        info.append(f"行数: {len(df)}")
        info.append(f"列数: {len(df.columns)}")
        info.append(f"\n列信息:")
        for col in df.columns:
            non_null = df[col].notna().sum()
            info.append(f"  - {col}: {df[col].dtype} ({non_null}/{len(df)} 非空, 示例: {df[col].dropna().iloc[0] if non_null > 0 else 'N/A'})")
        info.append(f"\n前5行预览:")
        info.append(df.head(5).to_string())

        return "\n".join(info)
    except ValueError as e:
        return str(e)
    except Exception as e:
        return f"解析文件失败: {str(e)}"


async def _tool_pandas_query(args: dict, user_id: uuid.UUID, data_space_id: uuid.UUID | None) -> str:
    """执行 pandas 查询"""
    filename = args.get("filename", "")
    expression = args.get("expression", "")

    # 安全检查：禁止危险操作（在访问数据库之前）
    dangerous_keywords = ["import os", "import sys", "subprocess", "exec(", "eval(", "__", "open("]
    for kw in dangerous_keywords:
        if kw in expression:
            return f"安全限制：表达式中不允许使用 '{kw}'"

    file_path = await _get_file_path(filename, user_id, data_space_id)
    if not file_path or not file_path.exists():
        return f"文件 '{filename}' 不存在或无权访问"

    ext = filename.rsplit(".", 1)[-1].lower()

    try:
        if ext == "csv":
            df = pd.read_csv(file_path)
        elif ext in ("xlsx", "xls"):
            df = pd.read_excel(file_path)
        elif ext == "json":
            df = _load_json_as_df(file_path)
        else:
            return f"pandas_query 仅支持 CSV/Excel/JSON 文件"

        # 在受限环境中执行表达式
        local_vars = {"df": df, "pd": pd}
        result = eval(expression, {"__builtins__": {}}, local_vars)

        if isinstance(result, pd.DataFrame):
            if len(result) > 50:
                return f"结果共 {len(result)} 行，显示前50行:\n{result.head(50).to_string()}"
            return result.to_string()
        elif isinstance(result, pd.Series):
            return result.to_string()
        else:
            return str(result)
    except Exception as e:
        return f"查询执行失败: {str(e)}"


async def _tool_execute_python(args: dict, user_id: uuid.UUID, data_space_id: uuid.UUID | None) -> str:
    """执行 Python 代码（当前为进程内执行，后续改为 Docker 沙箱）"""
    code = args.get("code", "")

    # 安全检查：只禁止真正危险的操作
    dangerous_patterns = [
        "import os", "import sys", "import subprocess", "import shutil",
        "os.system", "os.popen", "subprocess.", "__import__",
        "import socket", "import requests", "import urllib",
    ]
    for pattern in dangerous_patterns:
        if pattern in code:
            return f"安全限制：代码中不允许使用 '{pattern}'"

    # 构建文件路径映射，让代码可以通过文件名访问数据
    file_paths = {}
    if data_space_id:
        async with get_session_factory()() as db:
            result = await db.execute(
                select(File)
                .join(DataSpaceFile, DataSpaceFile.file_id == File.id)
                .where(DataSpaceFile.data_space_id == data_space_id, File.user_id == user_id)
            )
            files = result.scalars().all()
            for f in files:
                full_path = Path(settings.storage_root) / f.storage_path
                file_paths[f.filename] = str(full_path)

    import io
    import sys
    from contextlib import redirect_stdout, redirect_stderr

    stdout_capture = io.StringIO()
    stderr_capture = io.StringIO()

    # 准备执行环境 - 使用受限的 builtins
    ALLOWED_MODULES = {"pandas", "numpy", "json", "math", "statistics", "collections", "itertools", "functools", "re", "datetime"}

    def _safe_import(name, *args, **kwargs):
        if name not in ALLOWED_MODULES:
            raise ImportError(f"不允许导入模块: {name}")
        return __builtins__["__import__"](name, *args, **kwargs) if isinstance(__builtins__, dict) else __import__(name, *args, **kwargs)

    safe_builtins = {
        "__import__": _safe_import,
        "abs": abs, "all": all, "any": any, "bool": bool,
        "dict": dict, "enumerate": enumerate, "filter": filter,
        "float": float, "format": format, "frozenset": frozenset,
        "int": int, "isinstance": isinstance, "issubclass": issubclass,
        "iter": iter, "len": len, "list": list, "map": map,
        "max": max, "min": min, "next": next, "print": print,
        "range": range, "repr": repr, "reversed": reversed,
        "round": round, "set": set, "slice": slice, "sorted": sorted,
        "str": str, "sum": sum, "tuple": tuple, "type": type,
        "zip": zip, "True": True, "False": False, "None": None,
        "ValueError": ValueError, "TypeError": TypeError,
        "KeyError": KeyError, "IndexError": IndexError,
        "Exception": Exception, "StopIteration": StopIteration,
    }

    exec_globals = {
        "__builtins__": safe_builtins,
        "pd": pd,
        "json": json,
        "FILES": file_paths,
    }

    try:
        import numpy as np
        exec_globals["np"] = np
    except ImportError:
        pass

    # 预加载数据文件为 DataFrame
    for fname, fpath in file_paths.items():
        var_name = fname.rsplit(".", 1)[0].replace(" ", "_").replace("-", "_").lower()
        ext = fname.rsplit(".", 1)[-1].lower()
        try:
            if ext == "csv":
                exec_globals[f"df_{var_name}"] = pd.read_csv(fpath)
            elif ext in ("xlsx", "xls"):
                exec_globals[f"df_{var_name}"] = pd.read_excel(fpath)
            elif ext == "json":
                exec_globals[f"df_{var_name}"] = _load_json_as_df(Path(fpath))
        except Exception:
            pass

    try:
        with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
            exec(code, exec_globals)

        stdout = stdout_capture.getvalue()
        stderr = stderr_capture.getvalue()

        result_parts = []
        if stdout:
            result_parts.append(f"输出:\n{stdout}")
        if stderr:
            result_parts.append(f"警告/错误:\n{stderr}")
        if not result_parts:
            result_parts.append("代码执行成功（无输出）")

        return "\n".join(result_parts)[:5000]
    except Exception as e:
        return f"代码执行错误: {type(e).__name__}: {str(e)}"
