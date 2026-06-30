"""channel 接入层核心单测：脱离 DB / LLM / 真实平台，验证抽象 + 桥接 + 配对。

只依赖 pydantic + pytest（用 asyncio.run 驱动异步，免 pytest-asyncio）。
证明「入站 → AgentBridge(buffer agent 流) → 流式回写」全链路 + 配对状态机成立。
"""
import asyncio
import json

from app.channels.contracts import OutboundMessage
from app.channels.bridge import AgentBridge
from app.channels.pairing import PairingService, InMemoryPairingStore
from app.channels.registry import ChannelRegistry
from app.channels.adapters.mock import MockChannelAdapter


class Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


async def _scripted(clock, script):
    """按脚本推进时钟并 yield 事件，模拟 AgentLoop.run 的事件流。"""
    for t, ev in script:
        clock.t = t
        yield ev


async def _agent_text(deltas, *, error=None):
    for d in deltas:
        yield {"type": "text", "delta": d}
    if error is not None:
        yield {"type": "error", "message": error}
    yield {"type": "done"}


# ---------- AgentBridge ----------

def test_bridge_buffers_and_finalizes():
    adapter = MockChannelAdapter()
    bridge = AgentBridge(clock=lambda: 0.0)  # 时钟恒 0 → 中间不触发 edit，只首发 + 终态
    final = asyncio.run(
        bridge.run_and_reply(adapter, "c1", _agent_text(["你好", "，", "世界"]))
    )
    assert final.text == "你好，世界"
    assert final.is_final is True
    # 首块 send，终态 edit
    assert [s["op"] for s in adapter.sent] == ["send", "edit"]
    assert adapter.sent[0]["text"] == "你好"
    assert adapter.sent[-1]["is_final"] is True
    assert adapter.sent[-1]["text"] == "你好，世界"


def test_bridge_streaming_throttle():
    clock = Clock()
    adapter = MockChannelAdapter()
    bridge = AgentBridge(min_edit_interval=10.0, clock=clock)
    script = [
        (0.0, {"type": "text", "delta": "a"}),   # send
        (1.0, {"type": "text", "delta": "b"}),   # 1-0<10 跳过
        (2.0, {"type": "text", "delta": "c"}),   # 跳过
        (20.0, {"type": "text", "delta": "d"}),  # 20-0>=10 → edit
        (20.0, {"type": "done"}),                # 终态 edit
    ]
    final = asyncio.run(bridge.run_and_reply(adapter, "c1", _scripted(clock, script)))
    assert final.text == "abcd"
    ops = [s["op"] for s in adapter.sent]
    assert ops == ["send", "edit", "edit"]  # 节流后只 1 次中间 edit + 终态
    assert adapter.sent[1]["is_final"] is False
    assert adapter.sent[-1]["is_final"] is True


def test_bridge_error_event():
    adapter = MockChannelAdapter()
    bridge = AgentBridge(clock=lambda: 0.0)
    final = asyncio.run(
        bridge.run_and_reply(adapter, "c1", _agent_text(["处理中"], error="额度不足"))
    )
    assert "额度不足" in final.text
    assert final.is_final is True


def test_bridge_empty_output():
    adapter = MockChannelAdapter()
    bridge = AgentBridge(clock=lambda: 0.0, empty_text="（无内容）")
    async def _empty():
        yield {"type": "done"}
    final = asyncio.run(bridge.run_and_reply(adapter, "c1", _empty()))
    assert final.text == "（无内容）"
    assert adapter.sent[-1]["is_final"] is True


# ---------- PairingService ----------

def test_pairing_issue_approve_consume():
    store = InMemoryPairingStore()
    svc = PairingService(store, ttl_seconds=600, code_gen=lambda: "123456")
    code = asyncio.run(svc.issue("feishu", "ou_abc"))
    assert code == "123456"
    assert asyncio.run(svc.approve("123456")) == ("feishu", "ou_abc")
    # 一次性消费：再批准失败
    assert asyncio.run(svc.approve("123456")) is None


def test_pairing_expiry():
    clock = Clock()
    store = InMemoryPairingStore(clock=clock)
    svc = PairingService(store, ttl_seconds=600, code_gen=lambda: "999999")
    asyncio.run(svc.issue("feishu", "ou_x"))
    clock.t = 601.0  # 超过 TTL
    assert asyncio.run(svc.approve("999999")) is None


def test_pairing_bad_code():
    svc = PairingService(InMemoryPairingStore(), code_gen=lambda: "111111")
    assert asyncio.run(svc.approve("000000")) is None


# ---------- Registry ----------

def test_registry():
    reg = ChannelRegistry()
    m = MockChannelAdapter()
    reg.register(m)
    assert reg.get("mock") is m
    assert reg.names() == ["mock"]
    assert reg.get("nope") is None


# ---------- 端到端：入站解析 → 桥接 → 回写 ----------

def test_inbound_to_reply_pipeline():
    adapter = MockChannelAdapter()
    body = json.dumps({"platform_user_id": "u1", "chat_id": "c1", "text": "分析销售数据"}).encode()
    inbound = adapter.parse_inbound({}, body)
    assert inbound is not None
    assert inbound.channel == "mock"
    assert inbound.text == "分析销售数据"
    assert inbound.platform_user_id == "u1"

    bridge = AgentBridge(clock=lambda: 0.0)

    async def fake_agent():
        yield {"type": "text", "delta": f"echo:{inbound.text}"}
        yield {"type": "done"}

    final = asyncio.run(bridge.run_and_reply(adapter, inbound.chat_id, fake_agent()))
    assert final.text == "echo:分析销售数据"
    assert adapter.sent[-1]["chat_id"] == "c1"
    assert adapter.sent[-1]["is_final"] is True


def test_adapter_parse_non_message_returns_none():
    adapter = MockChannelAdapter()
    body = json.dumps({"platform_user_id": "u1", "chat_id": "c1"}).encode()  # 无 text
    assert adapter.parse_inbound({}, body) is None
