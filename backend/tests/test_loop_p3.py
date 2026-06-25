"""P3 主循环单元测试：用假 Anthropic client 驱动 AgentLoop.run，
验证任务状态停止条件、update_plan 拦截、工具结果回填，全程无外部调用。
"""
import json
import uuid
import types
import pytest

from app.agent.loop import AgentLoop


# ---- 构造假的 Anthropic 流式响应 ---------------------------------------

class _FakeUsage:
    input_tokens = 10
    output_tokens = 5


class _FakeStream:
    """模拟 client.messages.stream(...) 返回的 async context manager。"""
    def __init__(self, events, final_msg):
        self._events = events
        self._final = final_msg

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def __aiter__(self):
        for e in self._events:
            yield e

    async def get_final_message(self):
        return self._final


def _text_events(text):
    """生成一段纯文本流事件。"""
    return [
        types.SimpleNamespace(type="content_block_delta",
                              delta=types.SimpleNamespace(type="text_delta", text=text)),
    ]


def _tool_events(text, tool_id, tool_name, tool_input):
    """生成一段含工具调用的流事件。"""
    ev = []
    if text:
        ev.append(types.SimpleNamespace(type="content_block_delta",
                                        delta=types.SimpleNamespace(type="text_delta", text=text)))
    ev.append(types.SimpleNamespace(type="content_block_start",
                                    content_block=types.SimpleNamespace(type="tool_use", id=tool_id, name=tool_name)))
    ev.append(types.SimpleNamespace(type="content_block_delta",
                                    delta=types.SimpleNamespace(type="input_json_delta",
                                                                partial_json=json.dumps(tool_input))))
    return ev


class _FakeMessages:
    def __init__(self, turns):
        self._turns = turns
        self._i = 0

    def stream(self, **kwargs):
        events = self._turns[self._i]
        self._i += 1
        final = types.SimpleNamespace(usage=_FakeUsage())
        return _FakeStream(events, final)


class _FakeClient:
    def __init__(self, turns):
        self.messages = _FakeMessages(turns)


# ---- 测试夹具：打桩掉所有 DB / 工具 / 配置依赖 -------------------------

@pytest.fixture
def patched_loop(monkeypatch):
    import app.agent.loop as loopmod

    # model 配置：anthropic 后端，不计费
    async def fake_resolve(self, model_id, user_id):
        return {"provider": "anthropic", "api_key": "enc", "api_base": None,
                "model_name": "fake", "multiplier": 1.0, "charge_credits": False}
    monkeypatch.setattr(loopmod.AgentLoop, "_resolve_model_config", fake_resolve)
    monkeypatch.setattr(loopmod, "decrypt_api_key", lambda k: "plain")

    # 上下文构建全部置空，避免触达 DB / 向量库
    async def _empty(self, *a, **k):
        return ""
    monkeypatch.setattr(loopmod.AgentLoop, "_get_data_space_info", _empty)
    monkeypatch.setattr(loopmod.AgentLoop, "_build_schema_context", _empty)
    monkeypatch.setattr(loopmod.AgentLoop, "_get_knowledge_context", _empty)

    async def fake_history(self, conv_id):
        return []
    monkeypatch.setattr(loopmod.AgentLoop, "_get_conversation_history", fake_history)

    # recall 记忆置空
    import app.services.memory as memmod
    async def fake_recall(*a, **k):
        return []
    monkeypatch.setattr(memmod, "recall", fake_recall)

    return loopmod


async def _collect(agent, **kwargs):
    events = []
    async for ev in agent.run(**kwargs):
        events.append(ev)
    return events


@pytest.mark.asyncio
async def test_simple_text_answer_stops(patched_loop, monkeypatch):
    """无工具调用 → 一个 turn 就收尾，产出 done + canonical。"""
    client = _FakeClient([_text_events("这是答案")])
    monkeypatch.setattr(patched_loop, "_get_client", lambda *a, **k: client)

    agent = AgentLoop()
    events = await _collect(
        agent,
        conversation_id=uuid.uuid4(), user_id=uuid.uuid4(), data_space_id=None,
        model_id="m", user_message="你好", is_admin=True,
    )
    types_seen = [e["type"] for e in events]
    assert "done" in types_seen
    done = next(e for e in events if e["type"] == "done")
    # canonical 应记录最终文本回答
    assert any(c["role"] == "assistant" and c["content"] == "这是答案"
               for c in done["canonical"])
    text = "".join(e.get("delta", "") for e in events if e["type"] == "text")
    assert "这是答案" in text


@pytest.mark.asyncio
async def test_hits_iteration_cap_forces_final_answer(patched_loop, monkeypatch):
    """P1-#3：撞步数上限时注入收尾轮，模型用已有信息给最终答复，而非裸中止。"""
    monkeypatch.setattr(patched_loop.settings, "enable_answer_self_check", False)
    # 前几轮调工具；收尾轮（工具被禁用）模型返回文本。max_iterations=3 时收尾轮落在第3个turn。
    turns = [
        _tool_events("第0步", "t0", "read_file", {"filename": "0.pdf"}),
        _tool_events("第1步", "t1", "read_file", {"filename": "1.pdf"}),
        _text_events("基于已读到的内容，给出阶段性结论"),
    ]
    client = _FakeClient(turns)
    monkeypatch.setattr(patched_loop, "_get_client", lambda *a, **k: client)

    async def fake_exec(tool_name, arguments, user_id, data_space_id):
        return "读到一些内容"
    monkeypatch.setattr(patched_loop, "execute_tool", fake_exec)

    agent = AgentLoop()
    agent.max_iterations = 3  # 故意调小，强制撞上限
    events = await _collect(
        agent,
        conversation_id=uuid.uuid4(), user_id=uuid.uuid4(), data_space_id=None,
        model_id="m", user_message="逐篇精读很多文件", is_admin=True,
    )
    text = "".join(e.get("delta", "") for e in events if e["type"] == "text")
    # 关键：撞上限后仍给出了真正的最终答复，而不是只有"已达到最大执行步数"
    assert "阶段性结论" in text, text
    # 正常 done 收尾（非 interrupted 裸停）
    assert any(e["type"] == "done" for e in events)


def _multi_tool_events(text, calls):
    """生成一段含多个工具调用的流事件（calls: [(id, name, input)]）。"""
    ev = []
    if text:
        ev.append(types.SimpleNamespace(type="content_block_delta",
                                        delta=types.SimpleNamespace(type="text_delta", text=text)))
    for tool_id, tool_name, tool_input in calls:
        ev.append(types.SimpleNamespace(type="content_block_start",
                                        content_block=types.SimpleNamespace(type="tool_use", id=tool_id, name=tool_name)))
        ev.append(types.SimpleNamespace(type="content_block_delta",
                                        delta=types.SimpleNamespace(type="input_json_delta",
                                                                    partial_json=json.dumps(tool_input))))
    return ev


@pytest.mark.asyncio
async def test_multiple_tools_run_concurrently(patched_loop, monkeypatch):
    """P0-2：一轮内多个工具并发执行，每个都得到 tool_result，且按 id 正确配对。"""
    import asyncio as _aio
    monkeypatch.setattr(patched_loop.settings, "enable_answer_self_check", False)
    client = _FakeClient([
        _multi_tool_events("同时读两个文件", [
            ("t1", "read_file", {"filename": "a.pdf"}),
            ("t2", "read_file", {"filename": "b.pdf"}),
        ]),
        _text_events("两个都读完了"),
    ])
    monkeypatch.setattr(patched_loop, "_get_client", lambda *a, **k: client)

    running = 0
    max_concurrent = 0
    async def fake_exec(tool_name, arguments, user_id, data_space_id):
        nonlocal running, max_concurrent
        running += 1
        max_concurrent = max(max_concurrent, running)
        await _aio.sleep(0.05)  # 模拟 I/O；若串行则总耗时叠加、并发数恒为 1
        running -= 1
        return f"内容: {arguments.get('filename')}"
    monkeypatch.setattr(patched_loop, "execute_tool", fake_exec)

    agent = AgentLoop()
    events = await _collect(
        agent,
        conversation_id=uuid.uuid4(), user_id=uuid.uuid4(), data_space_id=None,
        model_id="m", user_message="读 a 和 b", is_admin=True,
    )
    # 两个工具都产出了 tool_result
    results = [e for e in events if e["type"] == "tool_result"]
    assert len(results) == 2, results
    # 关键：确实并发（峰值并发数 >= 2），不是串行
    assert max_concurrent >= 2, f"max_concurrent={max_concurrent}（应并发）"
    # canonical 里两个工具结果都按 id 配对
    done = next(e for e in events if e["type"] == "done")
    tr = next(c for c in done["canonical"] if c["role"] == "tool_results")
    ids = {r["id"] for r in tr["results"]}
    assert ids == {"t1", "t2"}, ids


@pytest.mark.asyncio
async def test_tool_call_then_answer(patched_loop, monkeypatch):
    """turn1 调工具 → turn2 出答案。验证工具结果回填 canonical。"""
    monkeypatch.setattr(patched_loop.settings, "enable_answer_self_check", False)  # 单独测取数自检
    client = _FakeClient([
        _tool_events("先查一下", "t1", "sqlite_query", {"sql": "SELECT 1"}),
        _text_events("查到了，结论如下"),
    ])
    monkeypatch.setattr(patched_loop, "_get_client", lambda *a, **k: client)

    async def fake_exec(tool_name, arguments, user_id, data_space_id):
        return "查询结果: 42"
    monkeypatch.setattr(patched_loop, "execute_tool", fake_exec)

    agent = AgentLoop()
    events = await _collect(
        agent,
        conversation_id=uuid.uuid4(), user_id=uuid.uuid4(), data_space_id=None,
        model_id="m", user_message="查一下", is_admin=True,
    )
    types_seen = [e["type"] for e in events]
    assert "tool_use" in types_seen and "tool_result" in types_seen and "done" in types_seen
    # tool_use 事件带人话 summary
    tu = next(e for e in events if e["type"] == "tool_use")
    assert tu.get("summary")
    # canonical 含 tool_results
    done = next(e for e in events if e["type"] == "done")
    assert any(c["role"] == "tool_results" for c in done["canonical"])


@pytest.mark.asyncio
async def test_update_plan_emits_plan_event(patched_loop, monkeypatch):
    """update_plan 被拦截为 plan 事件，不进 execute_tool；计划全完成后收尾。"""
    client = _FakeClient([
        _tool_events("", "p1", "update_plan",
                     {"steps": [{"content": "第一步", "status": "completed"}]}),
        _text_events("完成"),
    ])
    monkeypatch.setattr(patched_loop, "_get_client", lambda *a, **k: client)

    called = []
    async def fake_exec(tool_name, arguments, user_id, data_space_id):
        called.append(tool_name)
        return "x"
    monkeypatch.setattr(patched_loop, "execute_tool", fake_exec)

    agent = AgentLoop()
    events = await _collect(
        agent,
        conversation_id=uuid.uuid4(), user_id=uuid.uuid4(), data_space_id=None,
        model_id="m", user_message="做个多步任务", is_admin=True,
    )
    # update_plan 不应进入真正的工具执行
    assert "update_plan" not in called
    plan_events = [e for e in events if e["type"] == "plan"]
    assert plan_events and plan_events[0]["steps"][0]["content"] == "第一步"
    assert any(e["type"] == "done" for e in events)


@pytest.mark.asyncio
async def test_graceful_interrupt_persists_canonical(patched_loop, monkeypatch):
    """中断（可续）：done 带 interrupted 标志且 canonical 已落盘，下一轮可继续。"""
    client = _FakeClient([_text_events("一些内容")])
    monkeypatch.setattr(patched_loop, "_get_client", lambda *a, **k: client)

    # 第一次检查返回 True：在 turn 顶部就中断
    agent = AgentLoop(abort_check=lambda: True)
    events = await _collect(
        agent,
        conversation_id=uuid.uuid4(), user_id=uuid.uuid4(), data_space_id=None,
        model_id="m", user_message="长任务", is_admin=True,
    )
    done = next(e for e in events if e["type"] == "done")
    assert done.get("interrupted") is True
    # canonical 字段存在（即便为空也应可被路由层持久化）
    assert "canonical" in done


# ---- 错误韧性：重试 + 降级 + 致命错误 -----------------------------------

class _FlakyMessages:
    """前 fail_times 次 stream() 抛可重试错误，之后正常返回。"""
    def __init__(self, turns, exc, fail_times):
        self._turns = turns
        self._exc = exc
        self._fail_times = fail_times
        self._calls = 0
        self._i = 0

    def stream(self, **kwargs):
        self._calls += 1
        if self._calls <= self._fail_times:
            raise self._exc
        events = self._turns[self._i]
        self._i += 1
        return _FakeStream(events, types.SimpleNamespace(usage=_FakeUsage()))


class _FlakyClient:
    def __init__(self, turns, exc, fail_times):
        self.messages = _FlakyMessages(turns, exc, fail_times)


@pytest.mark.asyncio
async def test_retryable_error_then_success(patched_loop, monkeypatch):
    """首次连接超时 → 退避重试 → 成功收尾。无重复输出。"""
    monkeypatch.setattr(patched_loop.settings, "llm_retry_base_delay", 0.0)  # 测试不真等
    monkeypatch.setattr(patched_loop.settings, "llm_max_retries", 2)
    client = _FlakyClient([_text_events("最终答案")], Exception("Connection timeout"), fail_times=1)
    monkeypatch.setattr(patched_loop, "_get_client", lambda *a, **k: client)

    agent = AgentLoop()
    events = await _collect(
        agent,
        conversation_id=uuid.uuid4(), user_id=uuid.uuid4(), data_space_id=None,
        model_id="m", user_message="问题", is_admin=True,
    )
    # 不应产生 error 事件；应正常 done
    assert not any(e["type"] == "error" for e in events)
    assert any(e["type"] == "done" for e in events)
    text = "".join(e.get("delta", "") for e in events if e["type"] == "text")
    assert text.count("最终答案") == 1  # 只输出一次，没因重试重复


@pytest.mark.asyncio
async def test_fatal_error_no_retry(patched_loop, monkeypatch):
    """致命错误（鉴权）不重试，直接清晰报错。"""
    monkeypatch.setattr(patched_loop.settings, "llm_retry_base_delay", 0.0)
    client = _FlakyClient([_text_events("x")], Exception("invalid api key"), fail_times=99)
    monkeypatch.setattr(patched_loop, "_get_client", lambda *a, **k: client)

    agent = AgentLoop()
    events = await _collect(
        agent,
        conversation_id=uuid.uuid4(), user_id=uuid.uuid4(), data_space_id=None,
        model_id="m", user_message="问题", is_admin=True,
    )
    err = next(e for e in events if e["type"] == "error")
    # 只调用一次（不重试）
    assert client.messages._calls == 1
    assert "拒绝" in err["message"] or "API Key" in err["message"]


# ---- 取数结果自检（completion audit） -----------------------------------

@pytest.mark.asyncio
async def test_self_check_injected_once_after_data_tool(patched_loop, monkeypatch):
    """用过数据工具 → 收尾前注入一次自检 → 第二次答复才真正 done。"""
    monkeypatch.setattr(patched_loop.settings, "enable_answer_self_check", True)
    # turn1: 调数据工具；turn2: 给答案（触发自检）；turn3: 自检后最终答案
    client = _FakeClient([
        _tool_events("查一下", "t1", "sqlite_query", {"sql": "SELECT count(*)"}),
        _text_events("一共 42 行"),
        _text_events("核对无误，答案是 42"),
    ])
    monkeypatch.setattr(patched_loop, "_get_client", lambda *a, **k: client)

    async def fake_exec(tool_name, arguments, user_id, data_space_id):
        return "count: 42"
    monkeypatch.setattr(patched_loop, "execute_tool", fake_exec)

    agent = AgentLoop()
    events = await _collect(
        agent,
        conversation_id=uuid.uuid4(), user_id=uuid.uuid4(), data_space_id=None,
        model_id="m", user_message="一共多少行", is_admin=True,
    )
    # 消费了全部 3 个 turn（自检确实多走了一轮）
    assert client.messages._i == 3
    done = next(e for e in events if e["type"] == "done")
    # 自检注入的 user 提示进入了 canonical
    assert any(c.get("role") == "user" and "自检" in c.get("content", "")
               for c in done["canonical"])


@pytest.mark.asyncio
async def test_no_self_check_without_data_tool(patched_loop, monkeypatch):
    """纯文本回答（没用数据工具）→ 不触发自检，一轮收尾。"""
    monkeypatch.setattr(patched_loop.settings, "enable_answer_self_check", True)
    client = _FakeClient([_text_events("这是个概念解释")])
    monkeypatch.setattr(patched_loop, "_get_client", lambda *a, **k: client)

    agent = AgentLoop()
    events = await _collect(
        agent,
        conversation_id=uuid.uuid4(), user_id=uuid.uuid4(), data_space_id=None,
        model_id="m", user_message="什么是标准差", is_admin=True,
    )
    assert client.messages._i == 1  # 只走了一轮，没有自检追加
    done = next(e for e in events if e["type"] == "done")
    assert not any("自检" in c.get("content", "") for c in done["canonical"] if isinstance(c.get("content"), str))



