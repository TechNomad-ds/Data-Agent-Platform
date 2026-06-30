"""渠道接入层：让外部渠道（飞书/邮箱…）反向够到 DataMind 的 agent。

设计最大程度复刻 同类产品/同类引擎 的 channel（统一消息契约 / 可插拔 adapter /
配对本地批准 / 流式 send+edit 二态），但用 Python 在 DataMind 内同进程实现，
agent 直连 AgentLoop。详见 docs/channel-integration-design.md。
"""
from app.channels.contracts import InboundMessage, OutboundMessage, ChannelAdapter
from app.channels.bridge import AgentBridge
from app.channels.registry import ChannelRegistry
from app.channels.pairing import PairingService, InMemoryPairingStore, PairingStore

__all__ = [
    "InboundMessage",
    "OutboundMessage",
    "ChannelAdapter",
    "AgentBridge",
    "ChannelRegistry",
    "PairingService",
    "InMemoryPairingStore",
    "PairingStore",
]
