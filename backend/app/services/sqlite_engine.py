"""SQLite 查询引擎 - 将数据空间文件加载到内存 SQLite 执行 SQL"""
import uuid
import sqlite3
import tempfile
import time
import threading
from pathlib import Path
from typing import Dict, Any, List

import pandas as pd
from sqlalchemy import select

from app.config import settings
from app.core.database import get_session_factory
from app.models.file import File
from app.models.data_space import DataSpaceFile


_cache: Dict[str, dict] = {}
_cache_lock = threading.Lock()
CACHE_TTL = 300  # 5 分钟后重建


async def load_space_to_sqlite(data_space_id: uuid.UUID, user_id: uuid.UUID) -> str:
    """将数据空间的表格文件加载到 SQLite，返回数据库路径"""
    cache_key = str(data_space_id)

    with _cache_lock:
        entry = _cache.get(cache_key)
        if entry and Path(entry["path"]).exists() and time.time() - entry["ts"] < CACHE_TTL:
            return entry["path"]

    async with get_session_factory()() as db:
        result = await db.execute(
            select(File)
            .join(DataSpaceFile, DataSpaceFile.file_id == File.id)
            .where(DataSpaceFile.data_space_id == data_space_id, File.user_id == user_id)
        )
        files = result.scalars().all()

    fd, db_path = tempfile.mkstemp(suffix=".db", prefix="space_")
    import os
    os.close(fd)
    conn = sqlite3.connect(db_path)

    for f in files:
        ext = f.file_type.lower()
        file_path = Path(settings.storage_root) / f.storage_path
        if not file_path.exists():
            continue

        if ext in ("sqlite", "db", "sqlite3"):
            try:
                src_conn = sqlite3.connect(str(file_path))
                src_cursor = src_conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
                for (tbl,) in src_cursor.fetchall():
                    quoted_tbl = '"' + tbl.replace('"', '""') + '"'
                    pragma = src_conn.execute(f"PRAGMA table_info({quoted_tbl})").fetchall()
                    col_defs = ",".join(
                        f'"{row[1]}" {row[2] if row[2] else "TEXT"}' for row in pragma
                    )
                    src_data = src_conn.execute(f"SELECT * FROM {quoted_tbl}")
                    cols = [d[0] for d in src_data.description]
                    rows = src_data.fetchall()
                    if cols and rows:
                        placeholders = ",".join(["?"] * len(cols))
                        conn.execute(f'CREATE TABLE IF NOT EXISTS "{tbl}" ({col_defs})')
                        conn.executemany(f'INSERT INTO "{tbl}" VALUES ({placeholders})', rows)
                src_conn.close()
            except Exception:
                continue
            continue

        if ext not in ("csv", "tsv", "xlsx", "xls", "json", "jsonl", "parquet", "feather", "dta", "sav", "sas7bdat"):
            continue

        base_name = f.filename.rsplit(".", 1)[0].replace(" ", "_").replace("-", "_").lower()
        table_name = base_name
        existing_tables = [t[0] for t in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        if table_name in existing_tables:
            table_name = f"{base_name}_{ext}"

        try:
            from app.services.file_loader import load_dataframe
            df = load_dataframe(file_path, ext)
            if df.empty:
                continue

            df.to_sql(table_name, conn, if_exists="replace", index=False)
        except Exception:
            continue

    conn.close()

    with _cache_lock:
        old = _cache.get(cache_key)
        if old:
            try:
                Path(old["path"]).unlink(missing_ok=True)
            except Exception:
                pass
        _cache[cache_key] = {"path": db_path, "ts": time.time()}

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
            quoted = '"' + name.replace('"', '""') + '"'
            info_cursor = conn.execute(f"PRAGMA table_info({quoted})")
            columns = [{"name": row[1], "type": row[2]} for row in info_cursor.fetchall()]
            count_cursor = conn.execute(f"SELECT COUNT(*) FROM {quoted}")
            row_count = count_cursor.fetchone()[0]
            tables.append({"name": name, "columns": columns, "row_count": row_count})
        return tables
    finally:
        conn.close()


def cleanup_all() -> None:
    """清理所有缓存的 SQLite 临时文件"""
    with _cache_lock:
        for entry in _cache.values():
            try:
                Path(entry["path"]).unlink(missing_ok=True)
            except Exception:
                pass
        _cache.clear()


def invalidate_cache(data_space_id: str) -> None:
    """清除缓存"""
    with _cache_lock:
        entry = _cache.pop(data_space_id, None)
        if entry:
            try:
                Path(entry["path"]).unlink(missing_ok=True)
            except Exception:
                pass


