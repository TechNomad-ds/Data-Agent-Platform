"""SQLite 查询引擎 - 将数据空间文件加载到内存 SQLite 执行 SQL"""
import uuid
import sqlite3
import tempfile
import time
import threading
import re
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
                tbls = [r[0] for r in src_conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()]
            except Exception:
                continue
            for tbl in tbls:
                # 每张表独立复制：单表失败不影响其它表（之前用 bare except 整库跳过）
                try:
                    quoted = '"' + tbl.replace('"', '""') + '"'
                    # 用 pandas 搬运，自动处理类型/空表，避免手写 DDL 出错
                    df = pd.read_sql(f"SELECT * FROM {quoted}", src_conn)
                    dest = tbl
                    existing = [t[0] for t in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
                    if dest in existing:
                        dest = f"{tbl}_db"
                    df.to_sql(dest, conn, if_exists="replace", index=False)
                except Exception:
                    continue
            try:
                src_conn.close()
            except Exception:
                pass
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


def execute_query(db_path: str, sql: str, max_rows: int = 10000) -> Dict[str, Any]:
    """执行只读 SQL 查询"""
    sql_clean = sql.strip()
    sql_upper = sql_clean.upper()
    if not (sql_upper.startswith("SELECT") or sql_upper.startswith("WITH")):
        return {"error": "只允许 SELECT/WITH 查询"}
    if re.search(r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|REPLACE|TRUNCATE)\b", sql_upper):
        return {"error": "只允许 SELECT/WITH 查询"}

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.execute(sql_clean)
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


def sweep_orphan_temp_files(max_age_seconds: int = 3600) -> int:
    """清理无主的 SQLite 临时文件。

    进程崩溃 / worker 被 max_requests 回收 / agent 异常中断时，内存里的 _cache
    会丢失，但 /tmp 里的 space_*.db 文件不会被清理，长期累积会撑满磁盘。
    这里扫描临时目录下所有由本模块创建（前缀 space_、后缀 .db）且超过 max_age
    的文件并删除——仍在缓存内、TTL 未过期的活跃文件会被跳过。

    返回删除的文件数。
    """
    import tempfile

    with _cache_lock:
        active = {entry["path"] for entry in _cache.values()}

    tmp_dir = Path(tempfile.gettempdir())
    now = time.time()
    removed = 0
    try:
        candidates = tmp_dir.glob("space_*.db")
    except Exception:
        return 0

    for p in candidates:
        sp = str(p)
        if sp in active:
            continue
        try:
            if now - p.stat().st_mtime < max_age_seconds:
                continue
            p.unlink(missing_ok=True)
            removed += 1
        except Exception:
            continue
    return removed


async def periodic_cleanup_loop(interval_seconds: int = 600, max_age_seconds: int = 3600) -> None:
    """后台周期性清理孤儿临时文件，由应用启动时拉起。"""
    import asyncio
    import logging
    logger = logging.getLogger("sqlite_engine")
    while True:
        try:
            await asyncio.sleep(interval_seconds)
            removed = await asyncio.get_running_loop().run_in_executor(
                None, sweep_orphan_temp_files, max_age_seconds
            )
            if removed:
                logger.info(f"周期清理：删除 {removed} 个孤儿 SQLite 临时文件")
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning(f"周期清理临时文件失败: {e}")

