"""AgentBridge：SSE → 渠道的桥接（核心难点）。

现有对话走浏览器 SSE，外部渠道是异步 webhook，二者协议不兼容。AgentBridge 的职责：
消费 AgentLoop.run() 的事件流（async generator），聚合文本，按节流用
adapter.send（首块/新消息）+ adapter.edit（后续更新）模拟流式回写——这正是借鉴
同类产品「sendMessage / editMessage 二态」的设计。

刻意做成 agent-无关、DB-无关：只接受一个已启动的事件流 `agent_events`，因此可脱离
AgentLoop / 数据库单测。真实接线（构造 AgentLoop、落库）在 router 层完成。
"""
from __future__ import annotations

import time
from typing import Any, AsyncIterator, Callable

from app.channels.contracts import ChannelAdapter, OutboundMessage


class AgentBridge:
    def __init__(
        self,
        *,
        min_edit_interval: float = 0.5,
        clock: Callable[[], float] = time.monotonic,
        empty_text: str = "（无内容）",
    ) -> None:
        # 流式更新节流间隔（秒），与 同类产品 的 editMessage 节流同思路，避免刷爆平台 API
        self.min_edit_interval = min_edit_interval
        self.clock = clock
        self.empty_text = empty_text

    async def run_and_reply(
        self,
        adapter: ChannelAdapter,
        chat_id: str,
        agent_events: AsyncIterator[dict[str, Any]],
    ) -> OutboundMessage:
        """把 agent 事件流聚合并回写到渠道，返回最终发出的消息。"""
        buf: list[str] = []
        message_id: str | None = None
        last_edit: float = 0.0

        async def push(final: bool) -> None:
            nonlocal message_id, last_edit
            text = "".join(buf) or self.empty_text
            msg = OutboundMessage(text=text, is_final=final)
            if message_id is None:
                message_id = await adapter.send(chat_id, msg)
            else:
                await adapter.edit(chat_id, message_id, msg)
            last_edit = self.clock()

        async for ev in agent_events:
            etype = ev.get("type")
            if etype == "text":
                buf.append(ev.get("delta", ""))
                now = self.clock()
                # 首块立刻发；之后按节流间隔更新
                if message_id is None or (now - last_edit) >= self.min_edit_interval:
                    await push(final=False)
            elif etype == "error":
                buf.append(("\n\n" if buf else "") + ev.get("message", "出错了"))
                await push(final=True)
                return OutboundMessage(text="".join(buf), is_final=True)
            elif etype == "done":
                break
            # thinking / tool_use / tool_result / plan 等中间事件：当前不回写渠道
            # （IM 里只发最终答案；将来可选择性投射工具进度）

        await push(final=True)
        return OutboundMessage(text="".join(buf) or self.empty_text, is_final=True)
