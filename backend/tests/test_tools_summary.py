"""P1/P2 工具层单元测试：人话进度摘要 + update_plan 工具定义。

纯函数测试，不触发外部接口。
"""
from app.agent.tools import tool_display_summary, get_tool_definitions


def test_display_summary_known_tools_hide_internals():
    # SQL / 代码不泄露内部细节
    assert "SQL" in tool_display_summary("sqlite_query", {"sql": "SELECT * FROM secret"})
    assert "secret" not in tool_display_summary("sqlite_query", {"sql": "SELECT * FROM secret"})
    assert tool_display_summary("execute_python", {"code": "print(1)"}) == "正在运行计算"
    # 文件名等无害信息可展示
    assert "sales.csv" in tool_display_summary("read_file", {"filename": "sales.csv"})


def test_display_summary_unknown_tool_fallback():
    assert tool_display_summary("mystery_tool", {}) == "正在执行 mystery_tool"


def test_display_summary_handles_bad_args():
    # 不应抛异常
    assert tool_display_summary("read_file", None) is not None
    assert tool_display_summary("search_data_space", {}) is not None


def test_update_plan_tool_registered():
    defs = get_tool_definitions()
    names = [d["function"]["name"] for d in defs]
    assert "update_plan" in names
    plan_def = next(d for d in defs if d["function"]["name"] == "update_plan")
    props = plan_def["function"]["parameters"]["properties"]
    assert "steps" in props
    step_props = props["steps"]["items"]["properties"]
    assert "content" in step_props and "status" in step_props
    assert set(step_props["status"]["enum"]) == {"pending", "in_progress", "completed"}
