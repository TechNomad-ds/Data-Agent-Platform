"""核心服务单元测试 — file_loader、retrieval分词、sqlite_engine、标题提取"""
import json
import tempfile
from pathlib import Path

import pytest
import pandas as pd


def test_file_loader_csv():
    """CSV 文件加载"""
    from app.services.file_loader import load_dataframe
    with tempfile.NamedTemporaryFile(suffix=".csv", mode="w", delete=False) as f:
        f.write("name,age,city\nAlice,30,Beijing\nBob,25,Shanghai\n")
        f.flush()
        df = load_dataframe(Path(f.name), "csv")
    assert len(df) == 2
    assert list(df.columns) == ["name", "age", "city"]


def test_file_loader_json():
    """JSON 文件加载"""
    from app.services.file_loader import load_dataframe
    with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as f:
        json.dump([{"a": 1, "b": 2}, {"a": 3, "b": 4}], f)
        f.flush()
        df = load_dataframe(Path(f.name), "json")
    assert len(df) == 2
    assert "a" in df.columns


def test_file_loader_unsupported():
    """不支持的格式返回空 DataFrame"""
    from app.services.file_loader import load_dataframe
    df = load_dataframe(Path("/tmp/fake.xyz"), "xyz")
    assert isinstance(df, pd.DataFrame)
    assert df.empty


def test_retrieval_tokenizer():
    """分词器能正确处理中英文"""
    from app.services.retrieval import _tokenize
    tokens = _tokenize("Hello world 你好世界")
    assert "hello" in tokens
    assert "world" in tokens
    assert "你" in tokens
    assert "好" in tokens


def test_retrieval_tokenizer_filtered():
    """过滤停用词"""
    from app.services.retrieval import _tokenize_filtered
    tokens = _tokenize_filtered("the quick brown fox 的了在")
    assert "the" not in tokens
    assert "的" not in tokens
    assert "quick" in tokens
    assert "brown" in tokens


def test_sqlite_engine_readonly():
    """SQLite 引擎拒绝写操作"""
    import sqlite3
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE t (id INTEGER, name TEXT)")
    conn.execute("INSERT INTO t VALUES (1, 'test')")
    conn.commit()
    conn.close()

    from app.services.sqlite_engine import execute_query
    result = execute_query(db_path, "SELECT * FROM t")
    assert result["row_count"] == 1

    result2 = execute_query(db_path, "DELETE FROM t")
    assert "error" in result2

    result3 = execute_query(db_path, "DROP TABLE t")
    assert "error" in result3


def test_extract_title():
    """对话标题提取"""
    from app.routers.chat import _extract_title

    assert _extract_title("帮我看看销售数据") == "看看销售数据"
    assert _extract_title("请帮我分析一下这个月的收入") != ""
    assert _extract_title("") == "新对话"
    assert len(_extract_title("这是一段非常非常非常非常非常非常非常非常长的用户输入消息")) <= 30
