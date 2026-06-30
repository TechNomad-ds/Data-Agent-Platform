"""配对绑定（借鉴 同类产品 的「本地批准」安全模型）。

陌生外部用户首次发消息 → 发 6 位配对码 → 用户在已登录的网页端输入并批准 →
把外部身份写入 external_identities 白名单。授权动作只在已认证的网页端完成，
绝不通过 IM 通道授权，防止 bot 被劫持。

store 可插拔：生产用 Redis（带 TTL），测试用内存实现。本模块只依赖 stdlib。
"""
from __future__ import annotations

import secrets
import time
from typing import Callable, Optional, Protocol


class PairingStore(Protocol):
    async def put(self, code: str, channel: str, platform_user_id: str, ttl: float) -> None: ...
    async def take(self, code: str) -> Optional[tuple[str, str]]: ...
    """取出并消费配对码，返回 (channel, platform_user_id)；不存在/过期返回 None。"""


class InMemoryPairingStore:
    """内存配对码存储（测试 / 单进程用）。生产请用 RedisPairingStore。"""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._data: dict[str, tuple[str, str, float]] = {}  # code -> (channel, uid, expire_at)

    async def put(self, code: str, channel: str, platform_user_id: str, ttl: float) -> None:
        self._data[code] = (channel, platform_user_id, self._clock() + ttl)

    async def take(self, code: str) -> Optional[tuple[str, str]]:
        item = self._data.get(code)
        if item is None:
            return None
        channel, uid, expire_at = item
        # 一次性消费：无论是否过期都移除
        del self._data[code]
        if self._clock() > expire_at:
            return None
        return (channel, uid)


class RedisPairingStore:
    """Redis 配对码存储（带 TTL）。跨进程共享：manager 进程出码、web worker 审批。

    懒导入 redis_client，保持本模块顶层 import-light（隔离单测不拉 redis）。
    """

    _PREFIX = "pairing:code:"

    async def put(self, code: str, channel: str, platform_user_id: str, ttl: float) -> None:
        from app.core.redis_client import get_redis
        r = await get_redis()
        await r.set(self._PREFIX + code, f"{channel}|{platform_user_id}", ex=int(ttl))

    async def take(self, code: str) -> Optional[tuple[str, str]]:
        from app.core.redis_client import get_redis
        r = await get_redis()
        key = self._PREFIX + code
        val = await r.get(key)
        if val is None:
            return None
        await r.delete(key)  # 一次性消费
        if isinstance(val, (bytes, bytearray)):
            val = val.decode()
        channel, sep, uid = val.partition("|")
        if not sep or not uid:
            return None
        return (channel, uid)


class PairingService:
    def __init__(
        self,
        store: PairingStore,
        *,
        ttl_seconds: float = 600.0,
        code_gen: Callable[[], str] = lambda: f"{secrets.randbelow(900000) + 100000}",
    ) -> None:
        self._store = store
        self._ttl = ttl_seconds
        self._code_gen = code_gen

    async def issue(self, channel: str, platform_user_id: str) -> str:
        """为某外部用户签发配对码（发回 IM 让其在网页端输入）。"""
        code = self._code_gen()
        await self._store.put(code, channel, platform_user_id, self._ttl)
        return code

    async def approve(self, code: str) -> Optional[tuple[str, str]]:
        """网页端已登录用户提交配对码；成功返回 (channel, platform_user_id) 供写入白名单。"""
        return await self._store.take(code)
