"""NL2SQL 服务 - 自然语言转 SQL 查询
适配自 DataMind nl2sql.py"""
import json
import uuid
from typing import Any

from anthropic import AsyncAnthropic

from app.config import settings
from app.services.sqlite_engine import load_space_to_sqlite, execute_query, list_tables


NL2SQL_PROMPT = """你是一个 SQL 专家。根据用户的自然语言问题和数据库 schema，生成一条 SQL 查询。

数据库 Schema：
{schema}

规则：
1. 只生成一条 SELECT 语句（可以用 WITH/CTE）
2. 不要使用 INSERT/UPDATE/DELETE/DROP/CREATE/ALTER
3. 只输出 SQL 语句本身，不要解释
4. 使用标准 SQLite 语法
5. 如果需要聚合，使用 GROUP BY
6. 限制结果行数不超过 200 行（加 LIMIT 200）

用户问题：{question}

SQL："""


async def generate_sql(
    question: str,
    schemas: list[dict],
    client: AsyncAnthropic | None = None,
) -> str:
    """从自然语言生成 SQL"""
    if client is None:
        client = AsyncAnthropic(api_key=settings.anthropic_api_key)

    schema_text = _format_schemas(schemas)
    prompt = NL2SQL_PROMPT.format(schema=schema_text, question=question)

    response = await client.messages.create(
        model=settings.anthropic_model,
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )

    sql = response.content[0].text.strip()
    if sql.startswith("```"):
        sql = sql.split("\n", 1)[1].rsplit("```", 1)[0].strip()

    if _is_destructive(sql):
        raise ValueError("生成的 SQL 包含危险操作，已拒绝执行")

    return sql


async def generate_and_execute(
    question: str,
    user_id: uuid.UUID,
    data_space_id: uuid.UUID,
) -> str:
    """生成 SQL 并执行，返回格式化结果"""
    import pandas as pd

    db_path = await load_space_to_sqlite(data_space_id, user_id)
    schemas = list_tables(db_path)

    if not schemas:
        return "数据空间中没有可查询的表格数据"

    try:
        sql = await generate_sql(question, schemas)
    except ValueError as e:
        return str(e)
    except Exception as e:
        return f"SQL 生成失败: {str(e)}"

    result = execute_query(db_path, sql)
    if "error" in result:
        return f"生成的 SQL:\n```sql\n{sql}\n```\n\n执行错误: {result['error']}"

    if not result["rows"]:
        return f"生成的 SQL:\n```sql\n{sql}\n```\n\n查询返回空结果"

    df = pd.DataFrame(result["rows"])
    output = f"生成的 SQL:\n```sql\n{sql}\n```\n\n"
    output += f"返回 {result['row_count']} 行"
    if result.get("truncated"):
        output += "（已截断至200行）"
    output += f"\n{df.to_string()}"
    return output


def _format_schemas(schemas: list[dict]) -> str:
    """格式化 schema 为紧凑文本"""
    lines = []
    for table in schemas:
        cols = ", ".join(f"{c['name']} {c['type']}" for c in table.get("columns", []))
        lines.append(f"TABLE {table['name']} ({table.get('row_count', '?')} rows): {cols}")
    return "\n".join(lines)


_DESTRUCTIVE_KEYWORDS = {"insert", "update", "delete", "drop", "create", "alter", "attach", "detach", "replace", "vacuum"}


def _is_destructive(sql: str) -> bool:
    """检查 SQL 是否包含破坏性操作"""
    tokens = sql.lower().split()
    return bool(set(tokens) & _DESTRUCTIVE_KEYWORDS)
