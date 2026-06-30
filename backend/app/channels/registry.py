"""渠道注册表：按配置启用哪些 adapter，按名字路由入站请求。

对应 同类产品 的 ChannelManager（可插拔多渠道）。只依赖 contracts，import-light。
"""
from __future__ import annotations

from app.channels.contracts import ChannelAdapter


class ChannelRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, ChannelAdapter] = {}

    def register(self, adapter: ChannelAdapter) -> None:
        self._adapters[adapter.name] = adapter

    def get(self, name: str) -> ChannelAdapter | None:
        return self._adapters.get(name)

    def names(self) -> list[str]:
        return list(self._adapters)
