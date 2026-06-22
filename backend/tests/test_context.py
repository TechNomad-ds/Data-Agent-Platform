"""P0 上下文管理单元测试：token 预算 + 混合 compaction + 双后端序列化。

全部为纯函数 / mock summarize，不触发任何真实外部接口。
"""
import pytest

from app.agent import context as ctx


def _user(text):
    return {"role": "user", "content": text}


def _assistant(text, tool_calls=None):
    return {"role": "assistant", "content": text, "tool_calls": tool_calls or []}


def _tool_results(results):
    return {"role": "tool_results", "results": results}


def test_estimate_tokens_cjk_vs_ascii():
    assert ctx.estimate_tokens("") == 0
    # CJK 约 1 token/字
    assert ctx.estimate_tokens("数据分析") >= 4
    # ASCII 约 4 字符/token
    assert ctx.estimate_tokens("a" * 40) <= 15


def test_truncate_tool_content_honest_marker():
    short = "x" * 100
    assert ctx.truncate_tool_content(short, 4000) == short
    long = "y" * 5000
    out = ctx.truncate_tool_content(long, 4000)
    assert out.startswith("y" * 4000)
    assert "已截断" in out
    assert "5000" in out  # 标注完整长度


@pytest.mark.asyncio
async def test_compact_under_budget_is_noop():
    msgs = [_user("你好"), _assistant("你好，我能帮你分析数据")]
    out = await ctx.compact_messages(msgs, budget=10000, min_recent=2)
    assert out == msgs


@pytest.mark.asyncio
async def test_compact_window_does_not_split_tool_pair():
    # 构造：老的 user，一个 assistant+tool_calls，紧跟 tool_results，再若干新消息
    msgs = [
        _user("第一个问题" * 200),
        _assistant("我来查", tool_calls=[{"id": "t1", "name": "sqlite_query", "input": {"sql": "SELECT 1"}}]),
        _tool_results([{"id": "t1", "name": "sqlite_query", "content": "结果" * 500, "is_error": False}]),
        _user("第二个问题"),
        _assistant("这是答案"),
    ]
    # 预算很小，强制裁剪；min_recent=1 让裁剪点可能落在工具配对中间
    out = await ctx.compact_messages(msgs, budget=50, min_recent=1, enable_summary=False)
    # 保留窗口的第一条绝不能是孤立的 tool_results
    assert out[0]["role"] != "tool_results"
    # 校验：任何 tool_results 前面必有带 tool_calls 的 assistant
    for i, m in enumerate(out):
        if m["role"] == "tool_results":
            assert i > 0 and out[i - 1]["role"] == "assistant"
            assert out[i - 1].get("tool_calls")


@pytest.mark.asyncio
async def test_compact_summary_fallback_invoked():
    calls = []

    async def fake_summarize(rendered):
        calls.append(rendered)
        return "这是早期对话的摘要"

    msgs = [_user("问题%d" % i + "内容" * 100) for i in range(20)]
    out = await ctx.compact_messages(
        msgs, budget=100, min_recent=2, enable_summary=True, summarize=fake_summarize
    )
    assert len(calls) == 1  # 只总结一次
    assert out[0]["role"] == "summary"
    assert "摘要" in out[0]["content"]
    # 摘要后仍保留最近窗口
    assert any(m["role"] == "user" for m in out[1:])


@pytest.mark.asyncio
async def test_compact_summary_failure_degrades_to_window():
    async def boom(rendered):
        raise RuntimeError("LLM down")

    msgs = [_user("问题%d" % i + "内容" * 100) for i in range(20)]
    out = await ctx.compact_messages(
        msgs, budget=100, min_recent=2, enable_summary=True, summarize=boom
    )
    # 总结失败不应抛出，退化为纯窗口（无 summary 条目）
    assert all(m["role"] != "summary" for m in out)
    assert len(out) < len(msgs)


def test_to_anthropic_rebuilds_tool_pair():
    msgs = [
        _user("查一下"),
        _assistant("好的", tool_calls=[{"id": "t1", "name": "sqlite_query", "input": {"sql": "SELECT 1"}}]),
        _tool_results([{"id": "t1", "name": "sqlite_query", "content": "1", "is_error": False}]),
    ]
    out = ctx.to_anthropic(msgs)
    # user, assistant(含 tool_use), user(含 tool_result)
    assert out[0] == {"role": "user", "content": "查一下"}
    assert out[1]["role"] == "assistant"
    assert any(b["type"] == "tool_use" and b["id"] == "t1" for b in out[1]["content"])
    assert out[2]["role"] == "user"
    assert out[2]["content"][0]["type"] == "tool_result"
    assert out[2]["content"][0]["tool_use_id"] == "t1"


def test_to_openai_rebuilds_tool_pair():
    msgs = [
        _user("查一下"),
        _assistant("好的", tool_calls=[{"id": "t1", "name": "sqlite_query", "input": {"sql": "SELECT 1"}}]),
        _tool_results([{"id": "t1", "name": "sqlite_query", "content": "1", "is_error": False}]),
    ]
    out = ctx.to_openai(msgs)
    assert out[0] == {"role": "user", "content": "查一下"}
    assert out[1]["role"] == "assistant"
    assert out[1]["tool_calls"][0]["id"] == "t1"
    assert out[1]["tool_calls"][0]["function"]["name"] == "sqlite_query"
    assert out[2] == {"role": "tool", "tool_call_id": "t1", "content": "1"}


def test_to_anthropic_error_flag_preserved():
    msgs = [
        _assistant("", tool_calls=[{"id": "t1", "name": "pandas_query", "input": {}}]),
        _tool_results([{"id": "t1", "name": "pandas_query", "content": "代码执行错误: x", "is_error": True}]),
    ]
    out = ctx.to_anthropic(msgs)
    tr_msg = out[-1]
    assert tr_msg["content"][0]["is_error"] is True


def test_summary_serialized_as_user():
    msgs = [{"role": "summary", "content": "早期摘要"}, _user("新问题")]
    a = ctx.to_anthropic(msgs)
    o = ctx.to_openai(msgs)
    assert a[0] == {"role": "user", "content": "早期摘要"}
    assert o[0] == {"role": "user", "content": "早期摘要"}


def test_assistant_with_toolcalls_no_text_serializes():
    # P3 重构：full_text 为空但有工具调用时，序列化器必须仍产出 assistant 条目
    entry = {"role": "assistant", "content": "", "tool_calls": [
        {"id": "t1", "name": "pandas_query", "input": {"filename": "a.csv"}},
    ]}
    a = ctx.to_anthropic([entry])
    assert len(a) == 1 and a[0]["role"] == "assistant"
    assert a[0]["content"][0]["type"] == "tool_use"
    o = ctx.to_openai([entry])
    assert o[0]["content"] is None
    assert o[0]["tool_calls"][0]["id"] == "t1"


def test_multi_tool_results_in_one_entry():
    # 一个 assistant 回合并行调用多个工具 → 一个 tool_results 条目含多条
    entry = {"role": "tool_results", "results": [
        {"id": "t1", "name": "sqlite_query", "content": "r1", "is_error": False},
        {"id": "t2", "name": "read_file", "content": "r2", "is_error": False},
    ]}
    a = ctx.to_anthropic([entry])
    # Anthropic：合并到一条 user 消息的多个 tool_result block
    assert len(a) == 1 and len(a[0]["content"]) == 2
    o = ctx.to_openai([entry])
    # OpenAI：拆成两条 role:tool 消息
    assert len(o) == 2 and all(m["role"] == "tool" for m in o)
    assert [m["tool_call_id"] for m in o] == ["t1", "t2"]



# ---- 密钥脱敏 -----------------------------------------------------------

def test_redact_common_secrets():
    assert ctx.redact_secrets("key sk-abcdefghij1234567890") == "key [已隐藏]"
    assert ctx.redact_secrets("AKIA1234567890ABCDEF") == "[已隐藏]"
    assert "[已隐藏]" in ctx.redact_secrets("Authorization: Bearer abc123def456ghi789")
    # 键值对：真凭据（长+含字母数字）才遮蔽（避免 Stripe sk_live_ 示例触发 secret scan）
    assert ctx.redact_secrets("api_key=sk-test-FakeRedactDemoKey01") == "api_key=[已隐藏]"
    assert "[已隐藏]" in ctx.redact_secrets("client_secret: AbC123dEf456GhI789jKl0")


def test_redact_does_not_touch_normal_business_columns():
    # 名为 password/token 的正常业务列、短值或中文值不应被误伤
    assert ctx.redact_secrets("password: 123") == "password: 123"
    assert ctx.redact_secrets("token: 启用") == "token: 启用"
    assert ctx.redact_secrets("某用户 password 字段是 hello") == "某用户 password 字段是 hello"
    # 太短的值不算凭据
    assert ctx.redact_secrets("access_token: abc") == "access_token: abc"


def test_redact_keeps_clean_text_intact():
    clean = "北京 2024 年销售额 1234567，共 42 行记录"
    assert ctx.redact_secrets(clean) == clean
    # 短数字/普通词不应误伤
    assert ctx.redact_secrets("count=42") == "count=42"


def test_redact_pem_private_key():
    pem = "-----BEGIN PRIVATE KEY-----\nMIIBVwIBADANB\n-----END PRIVATE KEY-----"
    assert ctx.redact_secrets(pem) == "[已隐藏]"


def test_redact_handles_none_and_empty():
    assert ctx.redact_secrets(None) == ""
    assert ctx.redact_secrets("") == ""


# ---- 压缩后健康校验 -----------------------------------------------------

def test_validate_sequence_accepts_well_formed():
    msgs = [
        _user("查一下"),
        _assistant("好", tool_calls=[{"id": "t1", "name": "sqlite_query", "input": {}}]),
        _tool_results([{"id": "t1", "name": "sqlite_query", "content": "r", "is_error": False}]),
        _user("再看看"),
    ]
    ok, _ = ctx.validate_sequence(msgs)
    assert ok


def test_validate_sequence_rejects_orphan_tool_results():
    # tool_results 前面没有对应的 assistant 工具调用（典型压缩切断事故）
    msgs = [
        _tool_results([{"id": "t1", "name": "sqlite_query", "content": "r", "is_error": False}]),
        _user("继续"),
    ]
    ok, reason = ctx.validate_sequence(msgs)
    assert not ok and "孤立" in reason


def test_validate_sequence_rejects_mismatched_id():
    msgs = [
        _assistant("好", tool_calls=[{"id": "t1", "name": "x", "input": {}}]),
        _tool_results([{"id": "t999", "name": "x", "content": "r", "is_error": False}]),
    ]
    ok, reason = ctx.validate_sequence(msgs)
    assert not ok


def test_validate_sequence_summary_prefix_ok():
    # 摘要(summary) + 保留窗口，窗口从 user 开始 → 合法
    msgs = [
        {"role": "summary", "content": "早期摘要"},
        _user("新问题"),
        _assistant("答案"),
    ]
    ok, _ = ctx.validate_sequence(msgs)
    assert ok


# ---- canonical 体积保护 -------------------------------------------------

def test_cap_canonical_noop_when_small():
    msgs = [_user("hi"), _assistant("答案")]
    assert ctx.cap_canonical(msgs, 10000) == msgs


def test_cap_canonical_keeps_tail_and_marks_dropped():
    big = [_assistant("A" * 100, tool_calls=[{"id": f"t{i}"}]) for i in range(20)]
    big.append(_assistant("最终答案"))
    out = ctx.cap_canonical(big, 300)
    assert len(out) < len(big)
    assert out[0]["role"] == "summary" and "省略" in out[0]["content"]
    assert out[-1]["content"] == "最终答案"  # 末尾最终答案被保住


def test_cap_canonical_counts_tool_results_chars():
    msgs = [
        _assistant("", tool_calls=[{"id": "t1"}]),
        _tool_results([{"id": "t1", "name": "x", "content": "Z" * 5000, "is_error": False}]),
        _assistant("done"),
    ]
    out = ctx.cap_canonical(msgs, 1000)
    # 大 tool_results 应被丢弃，末尾 assistant 保留
    assert out[-1]["content"] == "done"
