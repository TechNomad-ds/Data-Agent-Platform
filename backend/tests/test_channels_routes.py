"""渠道路由纯逻辑单测（独立于 DB / 网络 / FastAPI）

覆盖：
  - 渠道名称映射（lark↔feishu / weixin）
  - 请求/响应 Pydantic 模型验证
  - 待配对 registry 逻辑（过期过滤 / 归属隔离 / 注册）
  - SSE event 格式生成
  - LoginEvent camelCase 序列化（to_sse_data 纯逻辑，内联实现）

只依赖 pydantic + stdlib，asyncio.run 代替 pytest-asyncio。

Run:
    cd backend && python3 -m pytest tests/test_channels_routes.py -q --noconftest
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Literal, Optional
from dataclasses import dataclass

import pytest
from pydantic import BaseModel, ValidationError


# ────────────────────────────────────────────────────────────────────────────
# 内联渠道映射（与 app/routers/channels.py 保持一致，供测试引用）
# ────────────────────────────────────────────────────────────────────────────

_TO_INTERNAL: dict[str, str] = {
    "lark": "feishu",
    "weixin": "weixin",
}
_TO_FRONTEND: dict[str, str] = {v: k for k, v in _TO_INTERNAL.items()}
KNOWN_CHANNELS: list[str] = list(_TO_INTERNAL)


def _to_internal(channel: str) -> str:
    result = _TO_INTERNAL.get(channel)
    if result is None:
        raise ValueError(f"未知渠道: {channel}")
    return result


def _to_frontend(channel: str) -> str:
    return _TO_FRONTEND.get(channel, channel)


# ────────────────────────────────────────────────────────────────────────────
# 内联 Pydantic 模型（镜像 channels.py 中的模型，供孤立测试）
# ────────────────────────────────────────────────────────────────────────────


class ChannelStatusOut(BaseModel):
    id: str
    enabled: bool
    connected: bool
    has_credentials: bool
    bot_info: Optional[dict[str, Any]] = None


class EnableChannelBody(BaseModel):
    credentials: dict[str, str]


class CheckChannelBody(BaseModel):
    credentials: dict[str, str]


class CheckChannelResponse(BaseModel):
    ok: bool
    bot_username: Optional[str] = None
    error: Optional[str] = None


class ApprovePairingBody(BaseModel):
    code: str


class RejectPairingBody(BaseModel):
    code: str


class RevokeUserBody(BaseModel):
    id: str


class ChannelSettingsOut(BaseModel):
    default_data_space_id: Optional[str] = None
    default_model: Optional[str] = None


class ChannelSettingsIn(BaseModel):
    default_data_space_id: Optional[str] = None
    default_model: Optional[str] = None


# ────────────────────────────────────────────────────────────────────────────
# 内联 PendingPairing registry 逻辑（镜像 channels.py 的内存字典操作）
# ────────────────────────────────────────────────────────────────────────────


class PendingPairingRegistry:
    """测试用纯逻辑实现，等价于 channels.py 中的 _pending_pairings 模块字典。"""

    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {}

    def register(
        self,
        *,
        code: str,
        user_id: str,
        channel: str,
        platform_user_id: str,
        platform_username: str = "",
        expires_at: datetime,
    ) -> None:
        self._store[code] = {
            "code": code,
            "user_id": user_id,
            "platform": _to_frontend(channel),
            "platform_user_id": platform_user_id,
            "platform_username": platform_username,
            "expires_at": expires_at.isoformat(),
        }

    def list_for_user(self, user_id: str) -> list[dict[str, Any]]:
        now = datetime.now(timezone.utc)
        return [
            v
            for v in self._store.values()
            if v["user_id"] == user_id
            and datetime.fromisoformat(v["expires_at"]) > now
        ]

    def pop(self, code: str) -> Optional[dict[str, Any]]:
        return self._store.pop(code, None)

    def __len__(self) -> int:
        return len(self._store)


# ────────────────────────────────────────────────────────────────────────────
# 内联 LoginEvent SSE 序列化（镜像 weixin.py 的纯逻辑部分）
# ────────────────────────────────────────────────────────────────────────────


class LoginEventKind(str, Enum):
    QR = "qr"
    SCANNED = "scanned"
    DONE = "done"
    ERROR = "error"


@dataclass
class LoginEvent:
    kind: LoginEventKind
    qr_img_content: Optional[str] = None
    qr_ticket: Optional[str] = None
    bot_token: Optional[str] = None
    account_id: Optional[str] = None
    base_url: Optional[str] = None
    error: Optional[str] = None

    def to_sse_data(self) -> dict[str, Any]:
        if self.kind == LoginEventKind.QR:
            return {"qrcodeData": self.qr_img_content or ""}
        if self.kind == LoginEventKind.SCANNED:
            return {}
        if self.kind == LoginEventKind.DONE:
            return {
                "accountId": self.account_id or "",
                "botToken": self.bot_token or "",
                "baseUrl": self.base_url or "",
            }
        return {"message": self.error or ""}


def format_sse_line(event: LoginEvent) -> str:
    """生成一条 SSE 帧，与 channels.py weixin_login_sse 中的 yield 格式一致。"""
    data = json.dumps(event.to_sse_data(), ensure_ascii=False)
    return f"event: {event.kind.value}\ndata: {data}\n\n"


# ════════════════════════════════════════════════════════════════════════════
# Tests
# ════════════════════════════════════════════════════════════════════════════


class TestChannelMapping:
    """渠道名称映射：前端 ↔ 内部。"""

    def test_lark_maps_to_feishu(self):
        assert _to_internal("lark") == "feishu"

    def test_feishu_maps_to_lark(self):
        assert _to_frontend("feishu") == "lark"

    def test_weixin_roundtrip(self):
        assert _to_internal("weixin") == "weixin"
        assert _to_frontend("weixin") == "weixin"

    def test_unknown_channel_raises(self):
        with pytest.raises(ValueError, match="未知渠道"):
            _to_internal("telegram")

    def test_unknown_frontend_passthrough(self):
        # 未知内部名不抛错，直接返回
        assert _to_frontend("unknown_internal") == "unknown_internal"

    def test_known_channels_list(self):
        assert set(KNOWN_CHANNELS) == {"lark", "weixin"}
        assert len(KNOWN_CHANNELS) == 2

    def test_to_frontend_covers_all_known(self):
        for frontend in KNOWN_CHANNELS:
            internal = _to_internal(frontend)
            assert _to_frontend(internal) == frontend


class TestChannelStatusOut:
    """ChannelStatusOut Pydantic 模型验证。"""

    def test_basic_lark_status(self):
        s = ChannelStatusOut(id="lark", enabled=True, connected=False, has_credentials=True)
        assert s.id == "lark"
        assert s.bot_info is None

    def test_all_channels(self):
        for ch in KNOWN_CHANNELS:
            s = ChannelStatusOut(id=ch, enabled=False, connected=False, has_credentials=False)
            assert s.id == ch

    def test_with_bot_info(self):
        s = ChannelStatusOut(
            id="lark",
            enabled=True,
            connected=True,
            has_credentials=True,
            bot_info={"robotCode": "larkbot01", "name": "TestBot"},
        )
        assert s.bot_info is not None
        assert s.bot_info["robotCode"] == "larkbot01"

    def test_requires_id(self):
        with pytest.raises(ValidationError):
            ChannelStatusOut(enabled=False, connected=False, has_credentials=False)  # type: ignore

    def test_serialise_round_trip(self):
        data = {"id": "weixin", "enabled": True, "connected": True, "has_credentials": True}
        s = ChannelStatusOut(**data)
        d = s.model_dump()
        assert d["id"] == "weixin"
        assert d["bot_info"] is None

    def test_list_serialise(self):
        statuses = [
            ChannelStatusOut(id=ch, enabled=False, connected=False, has_credentials=False)
            for ch in KNOWN_CHANNELS
        ]
        raw = [s.model_dump() for s in statuses]
        assert len(raw) == 2
        assert all("id" in r for r in raw)


class TestRequestBodies:
    """请求体 Pydantic 模型验证。"""

    def test_enable_channel_body(self):
        body = EnableChannelBody(credentials={"app_id": "cli_x", "app_secret": "sec_y"})
        assert body.credentials["app_id"] == "cli_x"

    def test_enable_channel_body_empty_credentials(self):
        # 空 dict 语法合法（业务层再校验必填字段）
        body = EnableChannelBody(credentials={})
        assert body.credentials == {}

    def test_enable_channel_body_requires_credentials(self):
        with pytest.raises(ValidationError):
            EnableChannelBody()  # type: ignore

    def test_check_channel_body(self):
        body = CheckChannelBody(credentials={"client_id": "cid", "client_secret": "cs"})
        assert body.credentials["client_id"] == "cid"

    def test_check_channel_response_success(self):
        r = CheckChannelResponse(ok=True, bot_username="BotName")
        assert r.ok is True
        assert r.error is None

    def test_check_channel_response_failure(self):
        r = CheckChannelResponse(ok=False, error="invalid app_secret")
        assert r.ok is False
        assert "invalid" in (r.error or "")

    def test_check_channel_response_defaults(self):
        r = CheckChannelResponse(ok=True)
        assert r.bot_username is None
        assert r.error is None

    def test_approve_pairing_body(self):
        body = ApprovePairingBody(code="ABC123")
        assert body.code == "ABC123"

    def test_approve_pairing_body_requires_code(self):
        with pytest.raises(ValidationError):
            ApprovePairingBody()  # type: ignore

    def test_reject_pairing_body(self):
        body = RejectPairingBody(code="CODE42")
        assert body.code == "CODE42"

    def test_revoke_user_body_uuid_string(self):
        body = RevokeUserBody(id="550e8400-e29b-41d4-a716-446655440000")
        assert "550e8400" in body.id

    def test_revoke_user_body_requires_id(self):
        with pytest.raises(ValidationError):
            RevokeUserBody()  # type: ignore


class TestChannelSettings:
    """ChannelSettingsOut / ChannelSettingsIn 模型。"""

    def test_out_defaults(self):
        s = ChannelSettingsOut()
        assert s.default_data_space_id is None
        assert s.default_model is None

    def test_out_with_values(self):
        s = ChannelSettingsOut(default_data_space_id="ds-1", default_model="gpt-4o")
        assert s.default_data_space_id == "ds-1"

    def test_in_partial(self):
        body = ChannelSettingsIn(default_model="claude-3-5-sonnet")
        assert body.default_model == "claude-3-5-sonnet"
        assert body.default_data_space_id is None

    def test_in_full(self):
        body = ChannelSettingsIn(
            default_data_space_id="ds-42",
            default_model="claude-3-5-haiku",
        )
        assert body.default_data_space_id == "ds-42"

    def test_round_trip_json(self):
        body = ChannelSettingsIn(default_data_space_id="ds-99", default_model=None)
        raw = body.model_dump_json()
        parsed = ChannelSettingsIn.model_validate_json(raw)
        assert parsed.default_data_space_id == "ds-99"
        assert parsed.default_model is None


class TestPendingPairingRegistry:
    """待配对 registry 纯逻辑：注册、过期过滤、用户隔离、弹出消费。"""

    def _future(self, seconds: int = 600) -> datetime:
        return datetime.now(timezone.utc) + timedelta(seconds=seconds)

    def _past(self, seconds: int = 10) -> datetime:
        return datetime.now(timezone.utc) - timedelta(seconds=seconds)

    def test_register_and_list(self):
        reg = PendingPairingRegistry()
        reg.register(
            code="C1",
            user_id="user-1",
            channel="feishu",
            platform_user_id="ou_abc",
            expires_at=self._future(),
        )
        items = reg.list_for_user("user-1")
        assert len(items) == 1
        assert items[0]["code"] == "C1"
        assert items[0]["platform"] == "lark"           # 内部 feishu → 前端 lark

    def test_expired_not_listed(self):
        reg = PendingPairingRegistry()
        reg.register(
            code="C2",
            user_id="user-1",
            channel="weixin",
            platform_user_id="staff001",
            expires_at=self._past(),
        )
        assert reg.list_for_user("user-1") == []

    def test_user_isolation(self):
        reg = PendingPairingRegistry()
        reg.register(
            code="C3", user_id="user-A", channel="weixin",
            platform_user_id="wx_1", expires_at=self._future(),
        )
        reg.register(
            code="C4", user_id="user-B", channel="weixin",
            platform_user_id="wx_2", expires_at=self._future(),
        )
        a_items = reg.list_for_user("user-A")
        b_items = reg.list_for_user("user-B")
        assert len(a_items) == 1 and a_items[0]["code"] == "C3"
        assert len(b_items) == 1 and b_items[0]["code"] == "C4"

    def test_pop_consumes_code(self):
        reg = PendingPairingRegistry()
        reg.register(
            code="C5", user_id="u", channel="feishu",
            platform_user_id="ou_x", expires_at=self._future(),
        )
        entry = reg.pop("C5")
        assert entry is not None
        assert entry["code"] == "C5"
        assert reg.pop("C5") is None       # 二次弹出返回 None
        assert len(reg) == 0

    def test_pop_nonexistent_returns_none(self):
        reg = PendingPairingRegistry()
        assert reg.pop("NONEXISTENT") is None

    def test_registry_entry_schema(self):
        reg = PendingPairingRegistry()
        reg.register(
            code="CTEST",
            user_id="u1",
            channel="feishu",
            platform_user_id="ou_xyz",
            platform_username="张三",
            expires_at=self._future(300),
        )
        entry = reg.pop("CTEST")
        assert entry is not None
        assert entry["platform"] == "lark"
        assert entry["platform_user_id"] == "ou_xyz"
        assert entry["platform_username"] == "张三"
        # expires_at 应为 ISO 格式字符串
        dt = datetime.fromisoformat(entry["expires_at"])
        assert dt > datetime.now(timezone.utc)

    def test_multiple_entries_different_channels(self):
        reg = PendingPairingRegistry()
        for ch, pid, code in [("feishu", "ou_1", "K1"), ("weixin", "wx_1", "K2")]:
            reg.register(
                code=code, user_id="u", channel=ch,
                platform_user_id=pid, expires_at=self._future(),
            )
        items = reg.list_for_user("u")
        assert len(items) == 2
        platforms = {i["platform"] for i in items}
        assert platforms == {"lark", "weixin"}


class TestSSEEventFormat:
    """SSE 帧格式（event: / data: / 双换行）及 LoginEvent 序列化。"""

    def test_qr_event_format(self):
        evt = LoginEvent(kind=LoginEventKind.QR, qr_img_content="data:image/png;base64,abc==")
        line = format_sse_line(evt)
        assert line.startswith("event: qr\n")
        assert "qrcodeData" in line
        assert line.endswith("\n\n")

    def test_scanned_event_format(self):
        evt = LoginEvent(kind=LoginEventKind.SCANNED)
        line = format_sse_line(evt)
        assert "event: scanned\n" in line
        payload = json.loads(line.split("data: ")[1].strip())
        assert payload == {}

    def test_done_event_format(self):
        evt = LoginEvent(
            kind=LoginEventKind.DONE,
            bot_token="tok-abc",
            account_id="acc-123",
            base_url="https://ilinkai.weixin.qq.com",
        )
        line = format_sse_line(evt)
        assert "event: done\n" in line
        payload = json.loads(line.split("data: ")[1].strip())
        assert payload["botToken"] == "tok-abc"
        assert payload["accountId"] == "acc-123"
        assert payload["baseUrl"] == "https://ilinkai.weixin.qq.com"

    def test_error_event_format(self):
        evt = LoginEvent(kind=LoginEventKind.ERROR, error="QR code expired")
        line = format_sse_line(evt)
        assert "event: error\n" in line
        payload = json.loads(line.split("data: ")[1].strip())
        assert "expired" in payload["message"]

    def test_sse_double_newline_separator(self):
        """每帧必须以 \\n\\n 结尾（SSE spec），前端 EventSource 才能识别帧边界。"""
        for kind in LoginEventKind:
            evt = LoginEvent(kind=kind, error="x" if kind == LoginEventKind.ERROR else None)
            line = format_sse_line(evt)
            assert line.endswith("\n\n"), f"{kind} 帧未以 \\n\\n 结尾"

    def test_qr_sse_data_camel_case(self):
        """QR 事件 data key 是 qrcodeData（camelCase，与 Rust SseQrEvent 一致）。"""
        evt = LoginEvent(kind=LoginEventKind.QR, qr_img_content="base64data")
        data = evt.to_sse_data()
        assert "qrcodeData" in data
        assert data["qrcodeData"] == "base64data"

    def test_done_sse_data_camel_case(self):
        evt = LoginEvent(
            kind=LoginEventKind.DONE,
            bot_token="t1",
            account_id="a1",
            base_url="https://example.com",
        )
        data = evt.to_sse_data()
        assert set(data.keys()) == {"botToken", "accountId", "baseUrl"}

    def test_done_empty_fields_default_empty_string(self):
        """DONE 事件字段为 None 时，to_sse_data() 用空串代替。"""
        evt = LoginEvent(kind=LoginEventKind.DONE)  # 所有可选字段 None
        data = evt.to_sse_data()
        assert data["botToken"] == ""
        assert data["accountId"] == ""

    def test_parse_multi_frame_sse_stream(self):
        """模拟前端 EventSource 解析一个完整登录 SSE 流（QR→SCANNED→DONE）。"""
        frames = [
            LoginEvent(kind=LoginEventKind.QR, qr_img_content="data:image/png;base64,xyz"),
            LoginEvent(kind=LoginEventKind.SCANNED),
            LoginEvent(
                kind=LoginEventKind.DONE,
                bot_token="real_tok",
                account_id="real_acc",
                base_url="https://ilinkai.weixin.qq.com",
            ),
        ]
        stream = "".join(format_sse_line(e) for e in frames)

        parsed: list[tuple[str, dict]] = []
        current_event = ""
        for line in stream.split("\n"):
            if line.startswith("event: "):
                current_event = line[7:].strip()
            elif line.startswith("data: "):
                parsed.append((current_event, json.loads(line[6:])))
                current_event = ""

        assert len(parsed) == 3
        assert parsed[0][0] == "qr"
        assert "qrcodeData" in parsed[0][1]
        assert parsed[1][0] == "scanned"
        assert parsed[1][1] == {}
        assert parsed[2][0] == "done"
        assert parsed[2][1]["botToken"] == "real_tok"


class TestAsyncCompatibility:
    """asyncio.run 兼容性：确认测试无需 pytest-asyncio。"""

    def test_async_channel_mapping(self):
        """async 函数内部做渠道映射，asyncio.run 驱动。"""

        async def run() -> list[str]:
            return [_to_internal(ch) for ch in KNOWN_CHANNELS]

        result = asyncio.run(run())
        assert "feishu" in result
        assert "weixin" in result

    def test_async_pending_registry(self):
        """async 函数内部操作 registry，asyncio.run 驱动。"""

        async def run() -> int:
            reg = PendingPairingRegistry()
            expires = datetime.now(timezone.utc) + timedelta(minutes=10)
            reg.register(
                code="ASYNC_CODE",
                user_id="u_async",
                channel="feishu",
                platform_user_id="ou_async",
                expires_at=expires,
            )
            items = reg.list_for_user("u_async")
            return len(items)

        assert asyncio.run(run()) == 1

    def test_async_sse_generation(self):
        """async generator 生成 SSE 帧，asyncio.run 收集结果。"""

        async def generate_frames() -> list[str]:
            events = [
                LoginEvent(kind=LoginEventKind.QR, qr_img_content="data:image/png;base64,x"),
                LoginEvent(kind=LoginEventKind.DONE, bot_token="t", account_id="a"),
            ]
            return [format_sse_line(e) for e in events]

        frames = asyncio.run(generate_frames())
        assert len(frames) == 2
        assert "qr" in frames[0]
        assert "done" in frames[1]
