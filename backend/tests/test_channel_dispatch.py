"""入站调度隔离单测 (backend/tests/test_channel_dispatch.py)

验证 Dispatcher 三条路径（无 DB / 无 LLM / 无真实适配器）:
  1. 未绑定用户 → 发出配对码
  2. 已绑定用户 → 普通消息 → 调 AgentBridge → 回写渠道
  3. 命令 /new → 新建会话 / /space <uuid> → 更新默认空间

只依赖 pydantic + stdlib (asyncio.run，不用 pytest-asyncio)。
运行: cd backend && python3 -m pytest tests/test_channel_dispatch.py -q --noconftest
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Any, AsyncGenerator, Callable, Optional

from app.channels.contracts import InboundAttachment, InboundMessage, OutboundMessage
from app.channels.pairing import InMemoryPairingStore, PairingService
from app.channels.bridge import AgentBridge
from app.channels.adapters.mock import MockChannelAdapter
from app.channels.manager import (
    ChannelConfigSnapshot,
    Dispatcher,
)


# ---------------------------------------------------------------------------
# 内存 IdentityRepo
# ---------------------------------------------------------------------------

class InMemoryIdentityRepo:
    """测试用内存身份仓库：直接写 dict 注册绑定。"""

    def __init__(self) -> None:
        # (channel, platform_user_id) -> user_id
        self._bindings: dict[tuple[str, str], uuid.UUID] = {}
        # (user_id, channel) -> ChannelConfigSnapshot
        self._configs: dict[tuple[uuid.UUID, str], ChannelConfigSnapshot] = {}
        # 记录 set_default_space 调用
        self.space_updates: list[tuple[uuid.UUID, str, uuid.UUID]] = []

    def bind(
        self,
        channel: str,
        platform_user_id: str,
        user_id: uuid.UUID,
        *,
        space_id: Optional[uuid.UUID] = None,
        model: str = "test-model",
    ) -> None:
        self._bindings[(channel, platform_user_id)] = user_id
        self._configs[(user_id, channel)] = ChannelConfigSnapshot(
            user_id=user_id,
            channel=channel,
            default_data_space_id=space_id,
            default_model=model,
        )

    async def find_user_id(
        self, channel: str, platform_user_id: str
    ) -> Optional[uuid.UUID]:
        return self._bindings.get((channel, platform_user_id))

    async def get_channel_config(
        self, user_id: uuid.UUID, channel: str
    ) -> Optional[ChannelConfigSnapshot]:
        return self._configs.get((user_id, channel))

    async def set_default_space(
        self, user_id: uuid.UUID, channel: str, space_id: uuid.UUID
    ) -> None:
        self.space_updates.append((user_id, channel, space_id))
        key = (user_id, channel)
        if key in self._configs:
            old = self._configs[key]
            self._configs[key] = ChannelConfigSnapshot(
                user_id=old.user_id,
                channel=old.channel,
                default_data_space_id=space_id,
                default_model=old.default_model,
            )


# ---------------------------------------------------------------------------
# 内存 ConversationRepo
# ---------------------------------------------------------------------------

class InMemoryConversationRepo:
    """测试用内存会话仓库。"""

    def __init__(self) -> None:
        # (user_id, channel, chat_id) -> latest conv_id
        self._latest: dict[tuple[uuid.UUID, str, str], uuid.UUID] = {}
        # conv_id -> (user_text, assistant_text) list
        self.saved: dict[uuid.UUID, list[tuple[str, str]]] = {}
        # 记录 create_new 调用
        self.new_count: int = 0

    async def find_or_create(
        self,
        user_id: uuid.UUID,
        channel: str,
        chat_id: str,
        default_space_id: Optional[uuid.UUID],
        default_model: str,
    ) -> uuid.UUID:
        key = (user_id, channel, chat_id)
        if key not in self._latest:
            self._latest[key] = uuid.uuid4()
        return self._latest[key]

    async def create_new(
        self,
        user_id: uuid.UUID,
        channel: str,
        chat_id: str,
        default_space_id: Optional[uuid.UUID],
        default_model: str,
    ) -> uuid.UUID:
        self.new_count += 1
        new_id = uuid.uuid4()
        self._latest[(user_id, channel, chat_id)] = new_id
        return new_id

    async def save_messages(
        self,
        conv_id: uuid.UUID,
        user_text: str,
        assistant_text: str,
    ) -> None:
        self.saved.setdefault(conv_id, []).append((user_text, assistant_text))


# ---------------------------------------------------------------------------
# Fake AgentLoop
# ---------------------------------------------------------------------------

class _FakeAgent:
    """模拟 AgentLoop：按预设 delta 序列 yield text/done 事件。

    run() 必须是 async generator 函数（内含 yield），与真实 AgentLoop.run() 一致——
    调用后直接返回 AsyncGenerator，不需要 await，可直接 async for 迭代。
    """

    def __init__(self, deltas: list[str]) -> None:
        self._deltas = deltas
        self.last_call: dict[str, Any] = {}

    async def run(
        self,
        conversation_id: uuid.UUID,
        user_id: uuid.UUID,
        data_space_id: Optional[uuid.UUID],
        model_id: str,
        user_message: str,
        is_admin: bool = False,
        extra_space_ids: Optional[list] = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        # 记录调用参数（供断言）；在第一个 yield 之前设置 → 迭代开始时即记录
        self.last_call = {
            "conversation_id": conversation_id,
            "user_id": user_id,
            "data_space_id": data_space_id,
            "model_id": model_id,
            "user_message": user_message,
        }
        for d in self._deltas:
            yield {"type": "text", "delta": d}
        yield {"type": "done"}


def _make_fake_agent(deltas: list[str]) -> tuple[_FakeAgent, Callable[[], _FakeAgent]]:
    """返回 (agent_instance, factory)。factory 每次调用都返回同一个 agent（便于断言）。"""
    agent = _FakeAgent(deltas)
    return agent, lambda: agent


# ---------------------------------------------------------------------------
# Dispatcher 工厂辅助
# ---------------------------------------------------------------------------

def _make_dispatcher(
    identity_repo: InMemoryIdentityRepo,
    conversation_repo: InMemoryConversationRepo,
    agent_factory: Callable,
    *,
    pairing_ttl: float = 600.0,
    code_gen: Callable[[], str] = lambda: "123456",
) -> Dispatcher:
    store = InMemoryPairingStore()
    pairing = PairingService(store, ttl_seconds=pairing_ttl, code_gen=code_gen)
    bridge = AgentBridge(clock=lambda: 0.0)  # 时钟恒 0 → 不触发中间 edit
    return Dispatcher(
        identity_repo=identity_repo,
        conversation_repo=conversation_repo,
        pairing_service=pairing,
        agent_factory=agent_factory,
        bridge=bridge,
    )


def _inbound(text: str, channel: str = "mock", uid: str = "u1", chat: str = "c1") -> InboundMessage:
    return InboundMessage(
        channel=channel,
        platform_user_id=uid,
        chat_id=chat,
        text=text,
    )


# ===========================================================================
# 测试 1: 未绑定用户 → 签发配对码
# ===========================================================================

def test_unbound_user_issues_pairing_code():
    """未绑定用户发消息 → adapter 收到"配对码 XXXXXX"回复，不调 AgentLoop。"""
    identity = InMemoryIdentityRepo()   # 空：无绑定
    convs = InMemoryConversationRepo()
    _, factory = _make_fake_agent(["你好"])
    adapter = MockChannelAdapter()
    dispatcher = _make_dispatcher(identity, convs, factory, code_gen=lambda: "654321")

    asyncio.run(dispatcher.dispatch(adapter, _inbound("hello")))

    # 只应发一条消息（配对码）
    assert len(adapter.sent) == 1
    sent = adapter.sent[0]
    assert sent["op"] == "send"
    assert "654321" in sent["text"]
    assert "配对码" in sent["text"]

    # AgentLoop 不应被调用（会话列表为空）
    assert len(convs.saved) == 0


def test_unbound_user_different_codes():
    """两个不同的未绑定用户各自收到独立配对码。"""
    _codes = iter(["111111", "222222"])
    identity = InMemoryIdentityRepo()
    convs = InMemoryConversationRepo()
    _, factory = _make_fake_agent([])
    dispatcher = _make_dispatcher(identity, convs, factory, code_gen=lambda: next(_codes))

    adapter1 = MockChannelAdapter()
    adapter2 = MockChannelAdapter()
    asyncio.run(dispatcher.dispatch(adapter1, _inbound("hi", uid="u_a")))
    asyncio.run(dispatcher.dispatch(adapter2, _inbound("hi", uid="u_b")))

    assert "111111" in adapter1.sent[0]["text"]
    assert "222222" in adapter2.sent[0]["text"]


# ===========================================================================
# 测试 2: 已绑定用户 → 普通消息 → AgentBridge 回写
# ===========================================================================

def test_bound_user_routes_to_agent_bridge():
    """已绑定用户发普通消息 → AgentLoop.run() 被调用 → adapter 收到 agent 回复。"""
    user_id = uuid.uuid4()
    identity = InMemoryIdentityRepo()
    identity.bind("mock", "u1", user_id, model="test-model")

    convs = InMemoryConversationRepo()
    agent_obj, factory = _make_fake_agent(["你好", "，世界"])
    adapter = MockChannelAdapter()
    dispatcher = _make_dispatcher(identity, convs, factory)

    asyncio.run(dispatcher.dispatch(adapter, _inbound("你好吗")))

    # adapter 应收到 agent 输出（bridge clock=0 → 只有 send + final edit）
    assert len(adapter.sent) >= 1
    final = adapter.sent[-1]
    assert final["is_final"] is True
    assert "你好" in final["text"]
    assert "世界" in final["text"]

    # save_messages 应被调用
    assert len(convs.saved) == 1
    conv_id = list(convs.saved.keys())[0]
    msgs = convs.saved[conv_id]
    assert len(msgs) == 1
    user_text, asst_text = msgs[0]
    assert user_text == "你好吗"
    assert "你好" in asst_text


def test_bound_user_reuses_conversation():
    """同一 chat_id 两次消息复用同一会话。"""
    user_id = uuid.uuid4()
    identity = InMemoryIdentityRepo()
    identity.bind("mock", "u1", user_id)
    convs = InMemoryConversationRepo()
    agent_obj, factory = _make_fake_agent(["ok"])
    adapter = MockChannelAdapter()
    dispatcher = _make_dispatcher(identity, convs, factory)

    asyncio.run(dispatcher.dispatch(adapter, _inbound("msg1")))
    asyncio.run(dispatcher.dispatch(adapter, _inbound("msg2")))

    # 两次消息用同一 conv_id（find_or_create 返回相同 id）
    assert len(convs.saved) == 1          # 只有 1 个 conv_id key
    conv_id = list(convs.saved.keys())[0]
    assert len(convs.saved[conv_id]) == 2  # 两轮对话


def test_bound_user_passes_space_and_model_to_agent():
    """默认 space_id 和 model 透传给 AgentLoop.run()。"""
    user_id = uuid.uuid4()
    space_id = uuid.uuid4()
    identity = InMemoryIdentityRepo()
    identity.bind("mock", "u1", user_id, space_id=space_id, model="gpt-4o")
    convs = InMemoryConversationRepo()
    agent_obj, factory = _make_fake_agent(["reply"])
    adapter = MockChannelAdapter()
    dispatcher = _make_dispatcher(identity, convs, factory)

    asyncio.run(dispatcher.dispatch(adapter, _inbound("test")))

    assert agent_obj.last_call["data_space_id"] == space_id
    assert agent_obj.last_call["model_id"] == "gpt-4o"
    assert agent_obj.last_call["user_message"] == "test"
    assert agent_obj.last_call["user_id"] == user_id


# ===========================================================================
# 测试 3: /new 命令 → 新建会话
# ===========================================================================

def test_slash_new_resets_conversation():
    """/new 命令 → ConversationRepo.create_new() 被调用 → 回复"已开启新对话"。"""
    user_id = uuid.uuid4()
    identity = InMemoryIdentityRepo()
    identity.bind("mock", "u1", user_id)
    convs = InMemoryConversationRepo()
    _, factory = _make_fake_agent(["unreachable"])
    adapter = MockChannelAdapter()
    dispatcher = _make_dispatcher(identity, convs, factory)

    asyncio.run(dispatcher.dispatch(adapter, _inbound("/new")))

    # create_new 应被调用一次
    assert convs.new_count == 1

    # adapter 收到确认消息
    assert len(adapter.sent) == 1
    assert "新对话" in adapter.sent[0]["text"]

    # 不应有消息落库（/new 不走 agent）
    assert len(convs.saved) == 0


def test_slash_new_then_message_uses_new_conv():
    """/new 后发消息使用新建的会话。"""
    user_id = uuid.uuid4()
    identity = InMemoryIdentityRepo()
    identity.bind("mock", "u1", user_id)
    convs = InMemoryConversationRepo()
    agent_obj, factory = _make_fake_agent(["hi"])
    adapter = MockChannelAdapter()
    dispatcher = _make_dispatcher(identity, convs, factory)

    # 第一条普通消息 → 建会话 A
    asyncio.run(dispatcher.dispatch(adapter, _inbound("first")))
    old_conv_id = list(convs.saved.keys())[0]

    # /new → 清掉旧会话引用，建会话 B
    asyncio.run(dispatcher.dispatch(adapter, _inbound("/new")))
    assert convs.new_count == 1

    # 第二条消息 → 走新会话 B（find_or_create 返回 _latest 中最新的 id）
    asyncio.run(dispatcher.dispatch(adapter, _inbound("second")))
    new_conv_id = list(convs.saved.keys())[-1]

    assert old_conv_id != new_conv_id


# ===========================================================================
# 测试 4: /space 命令 → 更新默认数据空间
# ===========================================================================

def test_slash_space_updates_default_space():
    """/space <uuid> 命令 → IdentityRepo.set_default_space() 被调用 → 回复确认。"""
    user_id = uuid.uuid4()
    new_space = uuid.uuid4()
    identity = InMemoryIdentityRepo()
    identity.bind("mock", "u1", user_id)
    convs = InMemoryConversationRepo()
    _, factory = _make_fake_agent([])
    adapter = MockChannelAdapter()
    dispatcher = _make_dispatcher(identity, convs, factory)

    asyncio.run(dispatcher.dispatch(adapter, _inbound(f"/space {new_space}")))

    # set_default_space 应被调用
    assert len(identity.space_updates) == 1
    uid_got, ch_got, sid_got = identity.space_updates[0]
    assert uid_got == user_id
    assert ch_got == "mock"
    assert sid_got == new_space

    # adapter 回复切换确认
    assert len(adapter.sent) == 1
    assert str(new_space) in adapter.sent[0]["text"]

    # 不应走 agent
    assert len(convs.saved) == 0


def test_slash_space_missing_id_returns_usage():
    """/space 不带参数 → 回复用法提示。"""
    user_id = uuid.uuid4()
    identity = InMemoryIdentityRepo()
    identity.bind("mock", "u1", user_id)
    convs = InMemoryConversationRepo()
    _, factory = _make_fake_agent([])
    adapter = MockChannelAdapter()
    dispatcher = _make_dispatcher(identity, convs, factory)

    asyncio.run(dispatcher.dispatch(adapter, _inbound("/space")))

    assert len(adapter.sent) == 1
    assert "用法" in adapter.sent[0]["text"]
    assert len(identity.space_updates) == 0


def test_slash_space_invalid_uuid_returns_error():
    """/space 带非 UUID 参数 → 回复"无效的数据空间 ID"。"""
    user_id = uuid.uuid4()
    identity = InMemoryIdentityRepo()
    identity.bind("mock", "u1", user_id)
    convs = InMemoryConversationRepo()
    _, factory = _make_fake_agent([])
    adapter = MockChannelAdapter()
    dispatcher = _make_dispatcher(identity, convs, factory)

    asyncio.run(dispatcher.dispatch(adapter, _inbound("/space not-a-uuid")))

    assert len(adapter.sent) == 1
    assert "无效" in adapter.sent[0]["text"]
    assert len(identity.space_updates) == 0


# ===========================================================================
# 测试 5: 各路径的白盒/边界
# ===========================================================================

def test_unknown_command_treated_as_regular_message():
    """/unknown 命令（非 /new / /space）当作普通消息处理，走 agent。"""
    user_id = uuid.uuid4()
    identity = InMemoryIdentityRepo()
    identity.bind("mock", "u1", user_id)
    convs = InMemoryConversationRepo()
    agent_obj, factory = _make_fake_agent(["response"])
    adapter = MockChannelAdapter()
    dispatcher = _make_dispatcher(identity, convs, factory)

    asyncio.run(dispatcher.dispatch(adapter, _inbound("/unknown")))

    # 走 agent，保存消息
    assert len(convs.saved) == 1
    assert agent_obj.last_call["user_message"] == "/unknown"


def test_whitespace_stripped_from_text():
    """消息文本两端空白被裁剪。"""
    user_id = uuid.uuid4()
    identity = InMemoryIdentityRepo()
    identity.bind("mock", "u1", user_id)
    convs = InMemoryConversationRepo()
    agent_obj, factory = _make_fake_agent(["ok"])
    adapter = MockChannelAdapter()
    dispatcher = _make_dispatcher(identity, convs, factory)

    asyncio.run(dispatcher.dispatch(adapter, _inbound("  /new  ")))

    # strip 后是 /new → 走 /new 路径
    assert convs.new_count == 1
    assert len(convs.saved) == 0


def test_no_config_falls_back_to_default_model():
    """已绑定用户但无渠道配置 → 使用 fallback 模型，不 raise。"""
    user_id = uuid.uuid4()
    identity = InMemoryIdentityRepo()
    # 只注册绑定，不注册 channel config
    identity._bindings[("mock", "u1")] = user_id
    convs = InMemoryConversationRepo()
    agent_obj, factory = _make_fake_agent(["fallback ok"])
    adapter = MockChannelAdapter()
    dispatcher = _make_dispatcher(identity, convs, factory)

    asyncio.run(dispatcher.dispatch(adapter, _inbound("query")))

    # agent 应以 fallback 模型被调用
    assert "gpt-4o-mini" in agent_obj.last_call["model_id"]
    assert agent_obj.last_call["data_space_id"] is None


# ===========================================================================
# 测试 6: 附件入库（文件/图片，任意渠道统一路径）
# ===========================================================================

def _patch_ingest(recorder):
    """把 channel_ingest.ingest_files_to_space 替换为记录器，返回 (orig, module)。"""
    import app.services.channel_ingest as ing

    async def fake(user_id, space_id, files):
        recorder["user_id"] = user_id
        recorder["space_id"] = space_id
        recorder["files"] = files
        return [{"filename": n} for n, _ in files]

    orig = ing.ingest_files_to_space
    ing.ingest_files_to_space = fake
    return orig, ing


def _attach_inbound(atts, channel="mock", uid="u1", chat="c1") -> InboundMessage:
    return InboundMessage(channel=channel, platform_user_id=uid, chat_id=chat,
                          text="", attachments=atts)


def test_attachment_downloads_and_ingests():
    """带附件消息 → adapter.download_attachment 拉取 → ingest 收到 (name,bytes) → 回告已导入。"""
    user_id = uuid.uuid4()
    space_id = uuid.uuid4()
    identity = InMemoryIdentityRepo()
    identity.bind("mock", "u1", user_id, space_id=space_id)
    convs = InMemoryConversationRepo()
    _, factory = _make_fake_agent([])
    adapter = MockChannelAdapter()
    adapter.attachment_store["k1"] = b"FILEBYTES"
    dispatcher = _make_dispatcher(identity, convs, factory)

    rec: dict = {}
    orig, ing = _patch_ingest(rec)
    try:
        att = InboundAttachment(kind="file", name="report.pdf", resource_key="k1", locator="m1")
        asyncio.run(dispatcher.dispatch(adapter, _attach_inbound([att])))
    finally:
        ing.ingest_files_to_space = orig

    assert adapter.downloaded == ["k1"]
    assert rec["space_id"] == space_id
    assert rec["files"] == [("report.pdf", b"FILEBYTES")]
    assert len(adapter.sent) == 1
    assert "已导入 1 个文件" in adapter.sent[-1]["text"]
    assert "report.pdf" in adapter.sent[-1]["text"]
    # 附件路径不走 agent
    assert len(convs.saved) == 0


def test_attachment_without_default_space_prompts_user():
    """未设默认数据空间 → 提示先设置，不下载不入库。"""
    user_id = uuid.uuid4()
    identity = InMemoryIdentityRepo()
    identity.bind("mock", "u1", user_id, space_id=None)
    convs = InMemoryConversationRepo()
    _, factory = _make_fake_agent([])
    adapter = MockChannelAdapter()
    dispatcher = _make_dispatcher(identity, convs, factory)

    att = InboundAttachment(kind="image", name="i.jpg", resource_key="k", locator="m")
    asyncio.run(dispatcher.dispatch(adapter, _attach_inbound([att])))

    assert adapter.downloaded == []
    assert len(adapter.sent) == 1
    assert "默认数据空间" in adapter.sent[-1]["text"]


def test_attachment_unsupported_channel_prompts_user():
    """adapter 无 download_attachment → 提示暂不支持。"""
    class _NoAttachAdapter(MockChannelAdapter):
        supports_attachments = False  # 不支持附件 → 走「暂不支持」分支

    user_id = uuid.uuid4()
    space_id = uuid.uuid4()
    identity = InMemoryIdentityRepo()
    identity.bind("mock", "u1", user_id, space_id=space_id)
    convs = InMemoryConversationRepo()
    _, factory = _make_fake_agent([])
    adapter = _NoAttachAdapter()
    dispatcher = _make_dispatcher(identity, convs, factory)

    att = InboundAttachment(kind="file", name="f", resource_key="k", locator="m")
    asyncio.run(dispatcher.dispatch(adapter, _attach_inbound([att])))

    assert len(adapter.sent) == 1
    assert "暂不支持" in adapter.sent[-1]["text"]


# ===========================================================================
# 测试 7: 飞书文档链接（渠道无关——任意渠道发飞书链接都用用户的飞书凭据抓取）
# ===========================================================================

FEISHU_LINK = "看下这个文档 https://x.feishu.cn/wiki/ABC123 谢谢"


def _patch_feishu_ingest(recorder):
    """把 feishu_doc.try_ingest_feishu_doc 替换为记录器，返回 (orig, module)。"""
    import app.services.feishu_doc as fd

    async def fake(fetcher, inbound, user_id, space_id):
        recorder["fetcher"] = fetcher
        recorder["space_id"] = space_id
        return [{"filename": "doc.md"}]

    orig = fd.try_ingest_feishu_doc
    fd.try_ingest_feishu_doc = fake
    return orig, fd


def test_feishu_link_on_feishu_channel_reuses_online_adapter():
    """飞书渠道发飞书链接 → 复用在线 adapter 抓取 → 回告已导入，不走 agent。"""
    user_id = uuid.uuid4()
    space = uuid.uuid4()
    identity = InMemoryIdentityRepo()
    identity.bind("feishu", "u1", user_id, space_id=space)
    convs = InMemoryConversationRepo()
    _, factory = _make_fake_agent([])
    adapter = MockChannelAdapter()
    dispatcher = _make_dispatcher(identity, convs, factory)

    rec: dict = {}
    orig, fd = _patch_feishu_ingest(rec)
    try:
        asyncio.run(dispatcher.dispatch(adapter, _inbound(FEISHU_LINK, channel="feishu")))
    finally:
        fd.try_ingest_feishu_doc = orig

    assert rec["fetcher"] is adapter          # 飞书渠道复用在线 adapter
    assert "已导入" in adapter.sent[-1]["text"]
    assert len(convs.saved) == 0              # 不走 agent


def test_feishu_link_on_weixin_without_feishu_config_prompts():
    """微信发飞书链接但用户没配飞书应用 → 提示去配置，不抓取不走 agent。"""
    import app.channels.store as store_mod
    user_id = uuid.uuid4()
    identity = InMemoryIdentityRepo()
    identity.bind("weixin", "u1", user_id, space_id=uuid.uuid4())
    convs = InMemoryConversationRepo()
    _, factory = _make_fake_agent([])
    adapter = MockChannelAdapter()
    dispatcher = _make_dispatcher(identity, convs, factory)

    async def no_cfg(uid, ch):
        return None

    orig = store_mod.get_config
    store_mod.get_config = no_cfg
    try:
        asyncio.run(dispatcher.dispatch(adapter, _inbound(FEISHU_LINK, channel="weixin")))
    finally:
        store_mod.get_config = orig

    assert "飞书应用" in adapter.sent[-1]["text"]
    assert len(convs.saved) == 0


def test_feishu_link_on_weixin_with_config_fetches_via_user_feishu_creds():
    """微信发飞书链接且用户已配飞书应用 → 用其飞书凭据临时构造抓取器(非微信 adapter 本身)入库。"""
    import app.channels.store as store_mod
    user_id = uuid.uuid4()
    space = uuid.uuid4()
    identity = InMemoryIdentityRepo()
    identity.bind("weixin", "u1", user_id, space_id=space)
    convs = InMemoryConversationRepo()
    _, factory = _make_fake_agent([])
    adapter = MockChannelAdapter()
    dispatcher = _make_dispatcher(identity, convs, factory)

    class _Cfg:
        credentials_encrypted = b"enc"

    async def has_cfg(uid, ch):
        assert ch == "feishu"   # 取的是用户的飞书配置
        return (_Cfg(), {"app_id": "cli_x", "app_secret": "sec"})

    rec: dict = {}
    orig_cfg = store_mod.get_config
    store_mod.get_config = has_cfg
    orig_ing, fd = _patch_feishu_ingest(rec)
    try:
        asyncio.run(dispatcher.dispatch(adapter, _inbound(FEISHU_LINK, channel="weixin")))
    finally:
        store_mod.get_config = orig_cfg
        fd.try_ingest_feishu_doc = orig_ing

    assert rec["fetcher"] is not adapter      # 用临时飞书抓取器，不是微信 adapter
    assert rec["space_id"] == space
    assert "已导入" in adapter.sent[-1]["text"]
    assert len(convs.saved) == 0


if __name__ == "__main__":
    # 也可直接 python3 tests/test_channel_dispatch.py 运行
    import sys
    import unittest

    loader = unittest.TestLoader()
    tests = loader.loadTestsFromModule(sys.modules[__name__])
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(tests)
    sys.exit(0 if result.wasSuccessful() else 1)
