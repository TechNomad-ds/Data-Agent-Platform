"""外部数据源连接路由 - 连接 MySQL/PostgreSQL 等外部数据库"""
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.deps import get_current_user
from app.models.user import User

router = APIRouter()


class DatabaseConnection(BaseModel):
    name: str
    db_type: str  # mysql, postgresql, sqlite
    host: Optional[str] = None
    port: Optional[int] = None
    database: str
    username: Optional[str] = None
    password: Optional[str] = None


class QueryRequest(BaseModel):
    connection: DatabaseConnection
    sql: str
    max_rows: int = 100


@router.post("/query")
async def query_external_database(
    data: QueryRequest,
    current_user: User = Depends(get_current_user),
):
    """查询外部数据库（只读）"""
    conn_info = data.connection
    sql = data.sql.strip()

    sql_upper = sql.upper()
    if any(kw in sql_upper for kw in ("INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "TRUNCATE")):
        raise HTTPException(status_code=400, detail="只允许 SELECT 查询")

    try:
        if conn_info.db_type == "mysql":
            return await _query_mysql(conn_info, sql, data.max_rows)
        elif conn_info.db_type == "postgresql":
            return await _query_postgresql(conn_info, sql, data.max_rows)
        elif conn_info.db_type == "sqlite":
            return _query_sqlite_file(conn_info, sql, data.max_rows)
        else:
            raise HTTPException(status_code=400, detail=f"不支持的数据库类型: {conn_info.db_type}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"查询失败: {str(e)}")


@router.post("/tables")
async def list_external_tables(
    connection: DatabaseConnection,
    current_user: User = Depends(get_current_user),
):
    """列出外部数据库的表"""
    try:
        if connection.db_type == "mysql":
            return await _list_mysql_tables(connection)
        elif connection.db_type == "postgresql":
            return await _list_pg_tables(connection)
        elif connection.db_type == "sqlite":
            return _list_sqlite_tables(connection)
        else:
            raise HTTPException(status_code=400, detail=f"不支持的数据库类型: {connection.db_type}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"连接失败: {str(e)}")


async def _query_mysql(conn: DatabaseConnection, sql: str, max_rows: int) -> dict:
    import aiomysql
    connection = await aiomysql.connect(
        host=conn.host or "localhost",
        port=conn.port or 3306,
        user=conn.username or "root",
        password=conn.password or "",
        db=conn.database,
    )
    try:
        async with connection.cursor() as cursor:
            await cursor.execute(sql)
            columns = [desc[0] for desc in cursor.description] if cursor.description else []
            rows = await cursor.fetchmany(max_rows)
            return {
                "columns": [{"name": c, "dtype": "text"} for c in columns],
                "rows": [[str(v) if v is not None else "" for v in row] for row in rows],
                "total_rows": len(rows),
            }
    finally:
        connection.close()


async def _query_postgresql(conn: DatabaseConnection, sql: str, max_rows: int) -> dict:
    import asyncpg
    connection = await asyncpg.connect(
        host=conn.host or "localhost",
        port=conn.port or 5432,
        user=conn.username or "postgres",
        password=conn.password or "",
        database=conn.database,
    )
    try:
        rows = await connection.fetch(sql)
        if not rows:
            return {"columns": [], "rows": [], "total_rows": 0}
        columns = list(rows[0].keys())
        data = [[str(row[c]) if row[c] is not None else "" for c in columns] for row in rows[:max_rows]]
        return {
            "columns": [{"name": c, "dtype": "text"} for c in columns],
            "rows": data,
            "total_rows": len(data),
        }
    finally:
        await connection.close()


def _query_sqlite_file(conn: DatabaseConnection, sql: str, max_rows: int) -> dict:
    import sqlite3
    connection = sqlite3.connect(conn.database)
    try:
        cursor = connection.execute(sql)
        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        rows = cursor.fetchmany(max_rows)
        return {
            "columns": [{"name": c, "dtype": "text"} for c in columns],
            "rows": [[str(v) if v is not None else "" for v in row] for row in rows],
            "total_rows": len(rows),
        }
    finally:
        connection.close()


async def _list_mysql_tables(conn: DatabaseConnection) -> dict:
    import aiomysql
    connection = await aiomysql.connect(
        host=conn.host or "localhost", port=conn.port or 3306,
        user=conn.username or "root", password=conn.password or "", db=conn.database,
    )
    try:
        async with connection.cursor() as cursor:
            await cursor.execute("SHOW TABLES")
            tables = [row[0] for row in await cursor.fetchall()]
            return {"tables": tables, "db_type": "mysql"}
    finally:
        connection.close()


async def _list_pg_tables(conn: DatabaseConnection) -> dict:
    import asyncpg
    connection = await asyncpg.connect(
        host=conn.host or "localhost", port=conn.port or 5432,
        user=conn.username or "postgres", password=conn.password or "", database=conn.database,
    )
    try:
        rows = await connection.fetch(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
        )
        tables = [row["table_name"] for row in rows]
        return {"tables": tables, "db_type": "postgresql"}
    finally:
        await connection.close()


def _list_sqlite_tables(conn: DatabaseConnection) -> dict:
    import sqlite3
    connection = sqlite3.connect(conn.database)
    try:
        cursor = connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall()]
        return {"tables": tables, "db_type": "sqlite"}
    finally:
        connection.close()
