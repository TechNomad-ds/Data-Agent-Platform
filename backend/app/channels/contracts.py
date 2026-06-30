"""渠道接入统一契约（借鉴 同类产品 channel：统一消息格式隔离平台差异）。

agent 层完全不感知平台细节——所有 adapter 把平台原始消息翻译成 InboundMessage，
把 agent 输出翻译回 OutboundMessage。本模块只依赖 pydantic + stdlib，便于隔离单测。
详见 docs/channel-integration-design.md。
"""
from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable

from pydantic import BaseModel, Field


class InboundMessage(BaseModel):
    """外部渠道进来的一条用户消息（已归一）。"""

    channel: str                       # 'feishu' | 'email' | 'mock'
    platform_user_id: str              # 飞书 open_id / 邮箱地址
    chat_id: str                       # 外部会话/线程 id（用于映射 conversation 去重）
    text: str
    display_name: Optional[str] = None
    raw: dict[str, Any] = Field(default_factory=dict)  # 平台原始载荷，备查


class OutboundMessage(BaseModel):
    """要发回外部渠道的一条消息。

    is_final=False 表示流式中间块（对应平台的「编辑已发消息」）；
    is_final=True 表示终态。飞书等支持改卡片的平台用 send+edit 模拟流式。
    """

    text: str
    is_final: bool = True
    raw: dict[str, Any] = Field(default_factory=dict)


@runtime_checkable
class ChannelAdapter(Protocol):
    """各平台适配器要实现的最小契约（对应 同类产品 的 BasePlugin）。

    凭据通过适配器构造函数注入（不在此契约里假设来源），从而对
    「平台统一 bot」与「每用户自带 bot」两种归属模型都中立。
    """

    name: str  # 渠道标识，与 InboundMessage.channel 一致
    # 平台是否支持「编辑已发消息」做流式更新。False（如微信 iLink 只能发新消息）时，
    # 桥接层只发终态一条，避免把流式中间块发成多条不完整消息。默认 True。
    supports_edit: bool

    def verify(self, headers: dict[str, str], body: bytes) -> bool:
        """验证入站请求来自该平台（签名/token/AES）。webhook 不走 JWT，靠这个。"""
        ...

    def parse_inbound(self, headers: dict[str, str], body: bytes) -> Optional[InboundMessage]:
        """把平台 webhook 载荷解析成 InboundMessage；非消息事件返回 None。"""
        ...

    async def send(self, chat_id: str, msg: OutboundMessage) -> str:
        """发一条新消息，返回平台 message_id（供后续 edit 流式更新）。"""
        ...

    async def edit(self, chat_id: str, message_id: str, msg: OutboundMessage) -> None:
        """更新一条已发消息（流式回写）。不支持的平台可空实现。"""
        ...
