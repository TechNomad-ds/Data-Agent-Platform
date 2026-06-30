"""Mock 渠道 adapter：用于单测「入站→AgentBridge→回写」全链路，不依赖任何外部平台。

入站 body 为 JSON：{"platform_user_id","chat_id","text","display_name"?}。
出站把 send/edit 记录到 self.sent，便于断言流式行为。
"""
from __future__ import annotations

import json
from typing import Any, Optional

from app.channels.contracts import InboundAttachment, InboundMessage, OutboundMessage


class MockChannelAdapter:
    name = "mock"
    supports_edit = True

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []  # 记录每次 send/edit
        self._counter = 0
        self.attachment_store: dict[str, bytes] = {}  # resource_key -> bytes
        self.downloaded: list[str] = []               # 记录下载过的 resource_key

    def verify(self, headers: dict[str, str], body: bytes) -> bool:
        return True

    def parse_inbound(self, headers: dict[str, str], body: bytes) -> Optional[InboundMessage]:
        data = json.loads(body.decode("utf-8"))
        if "text" not in data:
            return None
        return InboundMessage(
            channel=self.name,
            platform_user_id=data["platform_user_id"],
            chat_id=data["chat_id"],
            text=data["text"],
            display_name=data.get("display_name"),
            raw=data,
        )

    async def send(self, chat_id: str, msg: OutboundMessage) -> str:
        self._counter += 1
        mid = f"mock-msg-{self._counter}"
        self.sent.append({"op": "send", "chat_id": chat_id, "message_id": mid,
                          "text": msg.text, "is_final": msg.is_final})
        return mid

    async def edit(self, chat_id: str, message_id: str, msg: OutboundMessage) -> None:
        self.sent.append({"op": "edit", "chat_id": chat_id, "message_id": message_id,
                          "text": msg.text, "is_final": msg.is_final})

    async def download_attachment(self, att: InboundAttachment) -> bytes:
        self.downloaded.append(att.resource_key)
        return self.attachment_store.get(att.resource_key, b"mock-bytes")
