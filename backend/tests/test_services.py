"""核心服务单元测试 — file_loader、retrieval分词、sqlite_engine、标题提取"""
import json
import importlib.util
import sys
import tempfile
import uuid
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


def test_file_loader_excel_sheets():
    """多 sheet Excel 会被完整枚举，不再只读第一个 sheet。"""
    pytest.importorskip("openpyxl")
    from app.services.file_loader import iter_named_dataframes, load_excel_sheets

    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
        path = Path(f.name)

    with pd.ExcelWriter(path) as writer:
        pd.DataFrame({"course_id": ["C001"], "name": ["机器学习"]}).to_excel(writer, sheet_name="课程目录", index=False)
        pd.DataFrame({"course_id": ["C001"], "student_id": ["S001"]}).to_excel(writer, sheet_name="报名记录", index=False)

    sheets = load_excel_sheets(path)
    assert list(sheets.keys()) == ["课程目录", "报名记录"]

    named = iter_named_dataframes(path, "xlsx", base_name="在线教育平台运营数据")
    assert [name for name, _df in named] == ["在线教育平台运营数据__课程目录", "在线教育平台运营数据__报名记录"]


def test_sandbox_preloads_specific_excel_sheets():
    """execute_python 的沙箱预加载可以精确读取指定工作表。"""
    pytest.importorskip("openpyxl")
    from app.agent.sandbox import run_in_sandbox

    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
        path = Path(f.name)

    with pd.ExcelWriter(path) as writer:
        pd.DataFrame({"course_id": ["C001"]}).to_excel(writer, sheet_name="课程目录", index=False)
        pd.DataFrame({"student_id": ["S001", "S002"]}).to_excel(writer, sheet_name="报名记录", index=False)

    result = run_in_sandbox(
        "result = (len(df_courses), len(df_enrollments))",
        preload={
            "df_courses": ("excel", str(path), "课程目录"),
            "df_enrollments": ("excel", str(path), "报名记录"),
        },
    )
    assert result["ok"] is True
    assert result["result"] == "(1, 2)"


def test_profile_tabular_excel_workbook():
    """Excel 画像包含所有工作表，供 agent schema 和搜索摘要使用。"""
    pytest.importorskip("openpyxl")
    from app.services.preprocessing import _profile_tabular

    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
        path = Path(f.name)

    with pd.ExcelWriter(path) as writer:
        pd.DataFrame({"course_id": ["C001"], "price": [199]}).to_excel(writer, sheet_name="课程目录", index=False)
        pd.DataFrame({"course_id": ["C001"], "revenue": [199]}).to_excel(writer, sheet_name="报名记录", index=False)

    profile = _profile_tabular(path, "xlsx")
    assert profile["workbook"] is True
    assert profile["sheet_count"] == 2
    assert [s["sheet_name"] for s in profile["sheets"]] == ["课程目录", "报名记录"]
    assert profile["sheets"][1]["columns"][1]["name"] == "revenue"


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


def test_system_prompt_contains_pku_study_guidance():
    """北大课程复习场景依赖这些提示词约束回答格式和范围。"""
    from app.agent.loop import SYSTEM_PROMPT_TEMPLATE

    for phrase in (
        "课程学习 / 复习辅导",
        "课程助教",
        "当前数据空间",
        "个性化问题",
        "核心概念 → 易混点 → 例题/应用 → 复习建议",
        "公式输出规范",
        "行内公式用 `$...$`",
        "独立公式用 `$$...$$`",
        "Markdown 稳定性",
        "UTF-8 正常文本",
    ):
        assert phrase in SYSTEM_PROMPT_TEMPLATE


def test_system_prompt_contains_text_analysis_quality_guidance():
    """报告中暴露的评论情感误判和首版代码报错，需要提示词长期约束。"""
    from app.agent.loop import SYSTEM_PROMPT_TEMPLATE

    for phrase in (
        "文本 / 评论 / 情感分析要求",
        "不要只靠关键词打标签",
        "希望增加更多实战",
        "改进诉求",
        "代表性原文短句",
        "代码可靠性要求",
        "确认真实列名",
        "避免链式赋值",
        "不要依赖上一轮工具里创建的临时变量",
    ):
        assert phrase in SYSTEM_PROMPT_TEMPLATE


def test_agent_data_context_is_intent_gated():
    """普通设计/提示词问题不应因为选了数据空间就被 schema 上下文带偏。"""
    from app.agent.loop import AgentLoop

    space_id = uuid.uuid4()
    assert not AgentLoop._should_include_data_context(
        "我怎么感觉 agent 问什么都关注 json/csv，是提示词里强调了吗？需要调整",
        space_id,
    )
    assert not AgentLoop._should_include_data_context("你觉得这个 agent 架构怎么设计更好？", space_id)

    assert AgentLoop._should_include_data_context("帮我统计 sales.csv 里每个区域的收入", space_id)
    assert AgentLoop._should_include_data_context("基于课程资料总结一下 cache miss 的考点", space_id)


def test_system_prompt_calls_schema_context_preview_not_full_inventory():
    """schema 预注入是相关文件预览，不能暗示模型已经看完全部文件。"""
    from app.agent.loop import SYSTEM_PROMPT_TEMPLATE

    for phrase in (
        "本轮相关文件预览",
        "不是完整文件清单",
        "不代表你已经读取了全部文件",
        "未展开文件仍属于数据空间",
    ):
        assert phrase in SYSTEM_PROMPT_TEMPLATE


def _load_pku_llm_acceptance_module():
    scripts_dir = Path(__file__).resolve().parents[2] / "scripts"
    script_path = scripts_dir / "pku_llm_acceptance_check.py"
    sys.path.insert(0, str(scripts_dir))
    spec = importlib.util.spec_from_file_location("pku_llm_acceptance_check", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(scripts_dir))
    return module


def _load_pku_acceptance_smoke_module():
    scripts_dir = Path(__file__).resolve().parents[2] / "scripts"
    script_path = scripts_dir / "pku_acceptance_smoke.py"
    sys.path.insert(0, str(scripts_dir))
    spec = importlib.util.spec_from_file_location("pku_acceptance_smoke", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(scripts_dir))
    return module


def test_pku_llm_acceptance_writes_failure_report(tmp_path):
    """真实 LLM 验收失败也要落盘，方便部署排查留证据。"""
    module = _load_pku_llm_acceptance_module()

    report_path = tmp_path / "nested" / "failure.json"
    module._write_report(str(report_path), {
        "ok": False,
        "error": "connection refused",
        "base_url": "http://127.0.0.1:9",
    })

    data = json.loads(report_path.read_text(encoding="utf-8"))
    assert data["ok"] is False
    assert data["error"] == "connection refused"
    assert data["base_url"] == "http://127.0.0.1:9"


def test_pku_llm_acceptance_main_writes_report_on_error(tmp_path, monkeypatch):
    """脚本 main() 异常路径也必须写报告，而不是只打印 stderr。"""
    module = _load_pku_llm_acceptance_module()
    report_path = tmp_path / "llm_failure.json"

    def fail_run(_args):
        raise RuntimeError("model endpoint failed")

    monkeypatch.setattr(module, "run", fail_run)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "pku_llm_acceptance_check.py",
            "--base-url",
            "http://127.0.0.1:9",
            "--report",
            str(report_path),
        ],
    )

    assert module.main() == 1
    data = json.loads(report_path.read_text(encoding="utf-8"))
    assert data["ok"] is False
    assert data["error"] == "model endpoint failed"
    assert data["base_url"] == "http://127.0.0.1:9"


def test_pku_llm_acceptance_skips_blank_model_ids():
    """模型列表可能含空配置，验收脚本必须选择可用模型。"""
    module = _load_pku_llm_acceptance_module()

    class FakeResponse:
        status_code = 200

        def json(self):
            return [
                {"id": "", "model_name": "", "provider": "anthropic"},
                {"id": "deepseek-v4-flash", "model_name": "deepseek-v4-pro", "provider": "openai"},
            ]

    class FakeClient:
        def get(self, _path, headers=None):
            return FakeResponse()

    assert module._pick_model_id(FakeClient(), {"Authorization": "Bearer test"}, None) == "deepseek-v4-flash"


def test_pku_smoke_main_writes_report_on_error(tmp_path, monkeypatch):
    """基础 smoke 失败也要落盘，否则线上初测失败缺少可归档证据。"""
    module = _load_pku_acceptance_smoke_module()
    report_path = tmp_path / "smoke_failure.json"

    def fail_run(_args):
        raise RuntimeError("api unavailable")

    monkeypatch.setattr(module, "run", fail_run)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "pku_acceptance_smoke.py",
            "--base-url",
            "http://127.0.0.1:9",
            "--report",
            str(report_path),
        ],
    )

    assert module.main() == 1
    data = json.loads(report_path.read_text(encoding="utf-8"))
    assert data["ok"] is False
    assert data["error"] == "api unavailable"
    assert data["base_url"] == "http://127.0.0.1:9"
    assert "python_version" in data


def test_embedding_get_collection_handles_create_race(monkeypatch):
    """并发上传同一空间时，Chroma collection 创建冲突应回退为读取已有 collection。"""
    from chromadb.db.base import UniqueConstraintError
    from app.services import embedding

    class FakeClient:
        def __init__(self):
            self.created = []
            self.fetched = []

        def get_or_create_collection(self, name, metadata):
            self.created.append((name, metadata))
            raise UniqueConstraintError("collection already exists")

        def get_collection(self, name):
            self.fetched.append(name)
            return {"name": name}

    client = FakeClient()
    monkeypatch.setattr(embedding, "get_chroma_client", lambda: client)

    collection = embedding.get_collection("54adc376-45a3-4743-9cd0-35e00a456b47")

    assert collection == {"name": "space_54adc37645a347439cd035e00a456b47"}
    assert client.created == [
        ("space_54adc37645a347439cd035e00a456b47", {"hnsw:space": "cosine"})
    ]
    assert client.fetched == ["space_54adc37645a347439cd035e00a456b47"]
