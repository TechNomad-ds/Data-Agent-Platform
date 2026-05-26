"""SQLite 查询引擎 - 将数据空间文件加载到内存 SQLite 执行 SQL"""
import uuid
import sqlite3
import tempfile
from pathlib import Path
from typing import Dict, Any, Optional, List

import pandas as pd
from sqlalchemy import select

from app.config import settings
from app.core.database import get_session_factory
from app.models.file import File
from app.models.data_space import DataSpaceFile


_cache: Dict[str, str] = {}


async def load_space_to_sqlite(data_space_id: uuid.UUID, user_id: uuid.UUID) -> str:
    """将数据空间的表格文件加载到 SQLite，返回数据库路径"""
    cache_key = str(data_space_id)
    if cache_key in _cache and Path(_cache[cache_key]).exists():
        return _cache[cache_key]

    async with get_session_factory()() as db:
        result = await db.execute(
            select(File)
            .join(DataSpaceFile, DataSpaceFile.file_id == File.id)
            .where(DataSpaceFile.data_space_id == data_space_id, File.user_id == user_id)
        )
        files = result.scalars().all()

    db_path = tempfile.mktemp(suffix=".db", prefix="space_")
    conn = sqlite3.connect(db_path)

    for f in files:
        ext = f.file_type.lower()
        file_path = Path(settings.storage_root) / f.storage_path
        if not file_path.exists():
            continue

        # SQLite files: attach directly
        if ext in ("sqlite", "db", "sqlite3"):
            try:
                src_conn = sqlite3.connect(str(file_path))
                src_cursor = src_conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
                for (tbl,) in src_cursor.fetchall():
                    src_data = src_conn.execute(f"SELECT * FROM '{tbl}'")
                    cols = [d[0] for d in src_data.description]
                    rows = src_data.fetchall()
                    if cols and rows:
                        placeholders = ",".join(["?"] * len(cols))
                        col_defs = ",".join(f'"{c}" TEXT' for c in cols)
                        conn.execute(f'CREATE TABLE IF NOT EXISTS "{tbl}" ({col_defs})')
                        conn.executemany(f'INSERT INTO "{tbl}" VALUES ({placeholders})', rows)
                src_conn.close()
            except Exception:
                continue
            continue

        if ext not in ("csv", "tsv", "xlsx", "xls", "json", "jsonl", "parquet", "feather"):
            continue

        table_name = f.filename.rsplit(".", 1)[0].replace(" ", "_").replace("-", "_").lower()

        try:
            if ext == "csv":
                from app.services.preprocessing import _detect_encoding
                encoding = _detect_encoding(file_path)
                df = pd.read_csv(file_path, encoding=encoding, on_bad_lines="skip")
            elif ext == "tsv":
                from app.services.preprocessing import _detect_encoding
                encoding = _detect_encoding(file_path)
                df = pd.read_csv(file_path, sep="\t", encoding=encoding, on_bad_lines="skip")
            elif ext in ("xlsx", "xls"):
                df = pd.read_excel(file_path)
            elif ext == "json":
                df = _load_json(file_path)
            elif ext == "jsonl":
                df = pd.read_json(file_path, lines=True)
            elif ext == "parquet":
                df = pd.read_parquet(file_path)
            elif ext == "feather":
                df = pd.read_feather(file_path)
            else:
                continue

            df.to_sql(table_name, conn, if_exists="replace", index=False)
        except Exception:
            continue

    conn.close()
    _cache[cache_key] = db_path
    return db_path


def execute_query(db_path: str, sql: str, max_rows: int = 200) -> Dict[str, Any]:
    """执行只读 SQL 查询"""
    sql_upper = sql.strip().upper()
    if any(kw in sql_upper for kw in ("INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE")):
        return {"error": "只允许 SELECT/WITH 查询"}

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.execute(sql)
        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        rows = cursor.fetchmany(max_rows)
        data = [dict(row) for row in rows]
        total = len(data)
        return {
            "columns": columns,
            "rows": data,
            "row_count": total,
            "truncated": total >= max_rows,
        }
    except Exception as e:
        return {"error": str(e)}
    finally:
        conn.close()


def list_tables(db_path: str) -> List[Dict[str, Any]]:
    """列出 SQLite 中的所有表"""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = []
        for (name,) in cursor.fetchall():
            info_cursor = conn.execute(f"PRAGMA table_info('{name}')")
            columns = [{"name": row[1], "type": row[2]} for row in info_cursor.fetchall()]
            count_cursor = conn.execute(f"SELECT COUNT(*) FROM '{name}'")
            row_count = count_cursor.fetchone()[0]
            tables.append({"name": name, "columns": columns, "row_count": row_count})
        return tables
    finally:
        conn.close()


def invalidate_cache(data_space_id: str) -> None:
    """清除缓存"""
    cache_key = data_space_id
    if cache_key in _cache:
        path = _cache.pop(cache_key)
        try:
            Path(path).unlink(missing_ok=True)
        except Exception:
            pass


def _load_json(file_path: Path) -> pd.DataFrame:
    import json
    content = file_path.read_text(encoding="utf-8")
    data = json.loads(content)
    if isinstance(data, list):
        return pd.DataFrame(data)
    elif isinstance(data, dict) and "records" in data:
        return pd.DataFrame(data["records"])
    elif isinstance(data, dict):
        return pd.DataFrame([data])
    return pd.DataFrame()
