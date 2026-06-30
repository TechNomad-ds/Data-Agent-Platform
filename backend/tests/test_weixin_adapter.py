"""微信 adapter 隔离单测。

只依赖 pydantic + stdlib。真实 HTTP 调用全部用 FakeHttpClient 替代。
异步测试用 asyncio.run()（不依赖 pytest-asyncio）。

运行方式：
    cd /root/Desktop/projects/Data-Agent-Platform/backend
    python3 -m pytest tests/test_weixin_adapter.py -q --noconftest
"""
from __future__ import annotations

import asyncio
import sys
import os

# 确保 backend/ 在 sys.path（--noconftest 不走 conftest.py 里的路径注入）
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.channels.adapters.weixin import (
    ITEM_TYPE_TEXT,
    ITEM_TYPE_VOICE,
    LoginEvent,
    LoginEventKind,
    WeixinAdapter,
    build_sendmessage_body,
    extract_text,
    make_wechat_uin,
    parse_getupdates_response,
    parse_login_qr_response,
    parse_login_status_response,
    parse_raw_message,
)
from app.channels.contracts import InboundMessage, OutboundMessage


# ---------------------------------------------------------------------------
# stdlib-only fake HTTP 层（无需 httpx）
# ---------------------------------------------------------------------------

class FakeResponse:
    """模拟 httpx.Response 的最小接口。"""

    def __init__(self, data: dict, status_code: int = 200) -> None:
        self._data = data
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> dict:
        return self._data


class FakeHttpClient:
    """顺序弹出预设响应的 fake 客户端，无需 import httpx。"""

    def __init__(self, responses: list[dict | tuple]) -> None:
        # 每项可为 dict（正常响应）或 (dict, status_code)
        self._queue: list[tuple[dict, int]] = []
        for r in responses:
            if isinstance(r, tuple):
                self._queue.append((r[0], r[1]))
            else:
                self._queue.append((r, 200))
        self.calls: list[dict] = []

    async def post(self, url: str, json=None, headers=None, timeout=None) -> FakeResponse:
        self.calls.append({"method": "post", "url": url, "json": json, "headers": headers})
        data, code = self._queue.pop(0) if self._queue else ({}, 200)
        return FakeResponse(data, code)

    async def get(self, url: str, params=None, headers=None) -> FakeResponse:
        self.calls.append({"method": "get", "url": url, "params": params, "headers": headers})
        data, code = self._queue.pop(0) if self._queue else ({}, 200)
        return FakeResponse(data, code)

    async def aclose(self) -> None:
        pass


# ---------------------------------------------------------------------------
# extract_text —— 纯逻辑测试
# ---------------------------------------------------------------------------

def test_extract_text_type1_basic():
    items = [{"type": 1, "text_item": {"text": "Hello"}}]
    assert extract_text(items) == "Hello"


def test_extract_text_type3_voice():
    items = [{"type": 3, "voice_item": {"text": "voice transcribed"}}]
    assert extract_text(items) == "voice transcribed"


def test_extract_text_mixed_type1_and_type3():
    items = [
        {"type": 1, "text_item": {"text": "text part"}},
        {"type": 3, "voice_item": {"text": "voice part"}},
    ]
    assert extract_text(items) == "text part\n\nvoice part"


def test_extract_text_ignores_image_and_file():
    items = [
        {"type": 2, "image_item": {}},
        {"type": 4, "file_item": {}},
    ]
    assert extract_text(items) == ""


def test_extract_text_strips_whitespace():
    items = [{"type": 1, "text_item": {"text": "  hello  "}}]
    assert extract_text(items) == "hello"


def test_extract_text_skips_empty_strings():
    items = [
        {"type": 1, "text_item": {"text": ""}},
        {"type": 1, "text_item": {"text": "real"}},
    ]
    assert extract_text(items) == "real"


def test_extract_text_empty_list():
    assert extract_text([]) == ""


def test_extract_text_missing_text_field():
    items = [{"type": 1, "text_item": {}}]
    assert extract_text(items) == ""


def test_item_type_constants():
    assert ITEM_TYPE_TEXT == 1
    assert ITEM_TYPE_VOICE == 3


# ---------------------------------------------------------------------------
# parse_raw_message —— 纯逻辑测试
# ---------------------------------------------------------------------------

def test_parse_raw_message_ok():
    raw = {
        "from_user_id": "u1",
        "context_token": "ctx1",
        "msg_id": "m1",
        "item_list": [{"type": 1, "text_item": {"text": "hi"}}],
    }
    msg = parse_raw_message(raw)
    assert msg is not None
    assert msg.channel == "weixin"
    assert msg.platform_user_id == "u1"
    assert msg.chat_id == "u1"
    assert msg.text == "hi"
    assert msg.raw == raw


def test_parse_raw_message_no_from_user_id():
    raw = {"item_list": [{"type": 1, "text_item": {"text": "hi"}}]}
    assert parse_raw_message(raw) is None


def test_parse_raw_message_no_text_content():
    raw = {"from_user_id": "u1", "item_list": [{"type": 2, "image_item": {}}]}
    assert parse_raw_message(raw) is None


def test_parse_raw_message_empty_item_list():
    raw = {"from_user_id": "u1", "item_list": []}
    assert parse_raw_message(raw) is None


# ---------------------------------------------------------------------------
# parse_getupdates_response —— 纯逻辑测试
# ---------------------------------------------------------------------------

def test_parse_getupdates_ok_single_message():
    data = {
        "ret": 0,
        "errcode": 0,
        "msgs": [
            {
                "from_user_id": "user_1",
                "context_token": "ctx_abc",
                "msg_id": "msg_1",
                "item_list": [{"type": 1, "text_item": {"text": "Hello"}}],
            }
        ],
        "get_updates_buf": "buf_xyz",
    }
    messages, new_buf, ctx_updates = parse_getupdates_response(data)
    assert len(messages) == 1
    assert messages[0].platform_user_id == "user_1"
    assert messages[0].text == "Hello"
    assert messages[0].channel == "weixin"
    assert new_buf == "buf_xyz"
    assert ctx_updates == {"user_1": "ctx_abc"}


def test_parse_getupdates_api_error_raises():
    data = {"ret": 1001, "errcode": 401, "errmsg": "invalid token"}
    try:
        parse_getupdates_response(data)
        assert False, "Should raise RuntimeError"
    except RuntimeError as exc:
        assert "1001" in str(exc)
        assert "401" in str(exc)


def test_parse_getupdates_ret_nonzero_raises():
    data = {"ret": 500, "errmsg": "server error"}
    try:
        parse_getupdates_response(data)
        assert False
    except RuntimeError as exc:
        assert "500" in str(exc)


def test_parse_getupdates_no_msgs_returns_empty():
    data = {"ret": 0, "errcode": 0, "get_updates_buf": "buf_2"}
    messages, new_buf, ctx_updates = parse_getupdates_response(data)
    assert messages == []
    assert new_buf == "buf_2"
    assert ctx_updates == {}


def test_parse_getupdates_context_tokens_multiple_users():
    data = {
        "ret": 0,
        "msgs": [
            {"from_user_id": "u1", "context_token": "tok1",
             "item_list": [{"type": 1, "text_item": {"text": "a"}}]},
            {"from_user_id": "u2", "context_token": "tok2",
             "item_list": [{"type": 1, "text_item": {"text": "b"}}]},
        ],
    }
    _, _, ctx_updates = parse_getupdates_response(data)
    assert ctx_updates["u1"] == "tok1"
    assert ctx_updates["u2"] == "tok2"


def test_parse_getupdates_skips_msg_without_from_user_id():
    data = {
        "ret": 0,
        "msgs": [
            {"item_list": [{"type": 1, "text_item": {"text": "orphan"}}]},
            {"from_user_id": "u1", "context_token": "ctx",
             "item_list": [{"type": 1, "text_item": {"text": "valid"}}]},
        ],
    }
    messages, _, ctx_updates = parse_getupdates_response(data)
    assert len(messages) == 1
    assert messages[0].platform_user_id == "u1"


def test_parse_getupdates_context_token_stored_even_if_media_only():
    """context_token 要存，即使消息本身只有图片（无文本可返回给用户）。"""
    data = {
        "ret": 0,
        "msgs": [
            {"from_user_id": "u1", "context_token": "ctx_img",
             "item_list": [{"type": 2, "image_item": {}}]},
        ],
    }
    messages, _, ctx_updates = parse_getupdates_response(data)
    assert messages == []            # 无文本，不产生 InboundMessage
    assert ctx_updates["u1"] == "ctx_img"  # 但 token 仍要缓存


def test_parse_getupdates_empty_buf_preserved():
    """get_updates_buf 缺失时返回空串（初始游标）。"""
    data = {"ret": 0, "msgs": []}
    _, new_buf, _ = parse_getupdates_response(data)
    assert new_buf == ""


# ---------------------------------------------------------------------------
# build_sendmessage_body —— 纯逻辑测试
# ---------------------------------------------------------------------------

def test_build_sendmessage_with_context_token():
    body = build_sendmessage_body("u1", "hello", "ctx_token", client_id="fixed-uuid")
    msg = body["msg"]
    assert msg["to_user_id"] == "u1"
    assert msg["client_id"] == "fixed-uuid"
    assert msg["message_type"] == 2
    assert msg["message_state"] == 2
    assert msg["context_token"] == "ctx_token"
    assert msg["item_list"] == [{"type": 1, "text_item": {"text": "hello"}}]
    assert body["base_info"] == {}


def test_build_sendmessage_no_context_token():
    body = build_sendmessage_body("u1", "hi", None, client_id="uuid-1")
    assert "context_token" not in body["msg"]


def test_build_sendmessage_empty_context_token_omitted():
    body = build_sendmessage_body("u1", "hi", "", client_id="uuid-2")
    assert "context_token" not in body["msg"]


def test_build_sendmessage_client_id_auto_generated():
    body1 = build_sendmessage_body("u1", "a")
    body2 = build_sendmessage_body("u1", "b")
    # uuid4 生成，两次不同
    assert body1["msg"]["client_id"] != body2["msg"]["client_id"]


def test_build_sendmessage_item_list_structure():
    body = build_sendmessage_body("u1", "test text", client_id="id1")
    items = body["msg"]["item_list"]
    assert len(items) == 1
    assert items[0]["type"] == ITEM_TYPE_TEXT
    assert items[0]["text_item"]["text"] == "test text"


# ---------------------------------------------------------------------------
# parse_login_qr_response —— 纯逻辑测试
# ---------------------------------------------------------------------------

def test_parse_login_qr_ok_direct():
    data = {"qrcode": "ticket_123", "qrcode_img_content": "https://example.com/qr.png"}
    ticket, img = parse_login_qr_response(data)
    assert ticket == "ticket_123"
    assert img == "https://example.com/qr.png"


def test_parse_login_qr_ok_wrapped():
    data = {"code": 0, "data": {"qrcode": "t456", "qrcode_img_content": "http://img.url"}}
    ticket, img = parse_login_qr_response(data)
    assert ticket == "t456"
    assert img == "http://img.url"


def test_parse_login_qr_missing_ticket_raises():
    data = {"qrcode_img_content": "url"}
    try:
        parse_login_qr_response(data)
        assert False
    except RuntimeError as exc:
        assert "ticket" in str(exc)


def test_parse_login_qr_missing_img_raises():
    data = {"qrcode": "ticket_1"}
    try:
        parse_login_qr_response(data)
        assert False
    except RuntimeError as exc:
        assert "qrcode_img_content" in str(exc)


# ---------------------------------------------------------------------------
# parse_login_status_response —— 纯逻辑测试（状态机转换）
# ---------------------------------------------------------------------------

def test_parse_login_status_wait():
    st = parse_login_status_response({"status": "wait"})
    assert st["status"] == "wait"
    assert st["bot_token"] is None


def test_parse_login_status_scaned():
    # 注意 iLink 原始拼写：scaned（非 scanned）
    st = parse_login_status_response({"status": "scaned"})
    assert st["status"] == "scaned"


def test_parse_login_status_confirmed():
    data = {
        "status": "confirmed",
        "bot_token": "tok1",
        "ilink_bot_id": "acc1",
        "baseurl": "https://ilinkai.weixin.qq.com",
    }
    st = parse_login_status_response(data)
    assert st["status"] == "confirmed"
    assert st["bot_token"] == "tok1"
    assert st["ilink_bot_id"] == "acc1"
    assert st["baseurl"] == "https://ilinkai.weixin.qq.com"


def test_parse_login_status_expired():
    st = parse_login_status_response({"status": "expired"})
    assert st["status"] == "expired"


def test_parse_login_status_wrapped_format():
    data = {"code": 0, "data": {"status": "wait"}}
    st = parse_login_status_response(data)
    assert st["status"] == "wait"


# ---------------------------------------------------------------------------
# LoginEvent.to_sse_data —— 纯逻辑测试（SSE 序列化）
# ---------------------------------------------------------------------------

def test_login_event_sse_qr():
    evt = LoginEvent(kind=LoginEventKind.QR, qr_img_content="https://qr.url")
    assert evt.to_sse_data() == {"qrcodeData": "https://qr.url"}


def test_login_event_sse_qr_empty_img():
    evt = LoginEvent(kind=LoginEventKind.QR)
    assert evt.to_sse_data() == {"qrcodeData": ""}


def test_login_event_sse_scanned():
    evt = LoginEvent(kind=LoginEventKind.SCANNED)
    assert evt.to_sse_data() == {}


def test_login_event_sse_done():
    evt = LoginEvent(
        kind=LoginEventKind.DONE,
        account_id="acc1",
        bot_token="tok1",
        base_url="https://base.url",
    )
    assert evt.to_sse_data() == {
        "accountId": "acc1",
        "botToken": "tok1",
        "baseUrl": "https://base.url",
    }


def test_login_event_sse_error():
    evt = LoginEvent(kind=LoginEventKind.ERROR, error="timed out")
    assert evt.to_sse_data() == {"message": "timed out"}


def test_login_event_sse_error_empty():
    evt = LoginEvent(kind=LoginEventKind.ERROR)
    assert evt.to_sse_data() == {"message": ""}


# ---------------------------------------------------------------------------
# make_wechat_uin —— 纯逻辑测试
# ---------------------------------------------------------------------------

def test_make_wechat_uin_length():
    uin = make_wechat_uin()
    assert len(uin) == 8  # base64(4 bytes) = 8 chars with padding


def test_make_wechat_uin_is_valid_base64():
    import base64
    uin = make_wechat_uin()
    decoded = base64.b64decode(uin)
    assert len(decoded) == 4


def test_make_wechat_uin_randomness():
    uins = {make_wechat_uin() for _ in range(10)}
    # 10 次随机极不可能全相同（2^32 空间）
    assert len(uins) > 1


# ---------------------------------------------------------------------------
# WeixinAdapter 构造与验证
# ---------------------------------------------------------------------------

def test_adapter_constructor_rejects_empty_token():
    try:
        WeixinAdapter("", "acc1")
        assert False
    except ValueError as exc:
        assert "bot_token" in str(exc)


def test_adapter_constructor_rejects_empty_account():
    try:
        WeixinAdapter("tok1", "")
        assert False
    except ValueError as exc:
        assert "account_id" in str(exc)


def test_adapter_name():
    adapter = WeixinAdapter("tok1", "acc1")
    assert adapter.name == "weixin"


def test_adapter_verify_always_false():
    adapter = WeixinAdapter("tok1", "acc1")
    assert adapter.verify({}, b"") is False


def test_adapter_parse_inbound_always_none():
    adapter = WeixinAdapter("tok1", "acc1")
    assert adapter.parse_inbound({}, b"{}") is None


# ---------------------------------------------------------------------------
# WeixinAdapter.send —— 注入 fake HTTP，验证请求体构造与 context_token 携带
# ---------------------------------------------------------------------------

def test_adapter_send_uses_context_token():
    async def _run():
        fake = FakeHttpClient([{"ret": 0}])
        adapter = WeixinAdapter("tok1", "acc1", _http_client=fake)
        adapter._context_tokens["user_1"] = "ctx_stored"
        msg = OutboundMessage(text="hello", is_final=True)
        result = await adapter.send("user_1", msg)
        assert result == ""  # iLink 不返回 message_id
        assert len(fake.calls) == 1
        call = fake.calls[0]
        assert "sendmessage" in call["url"]
        payload = call["json"]
        assert payload["msg"]["to_user_id"] == "user_1"
        assert payload["msg"]["context_token"] == "ctx_stored"
        assert payload["msg"]["item_list"][0]["text_item"]["text"] == "hello"
        assert payload["base_info"] == {}

    asyncio.run(_run())


def test_adapter_send_without_context_token():
    async def _run():
        fake = FakeHttpClient([{"ret": 0}])
        adapter = WeixinAdapter("tok1", "acc1", _http_client=fake)
        # 无缓存 context_token
        msg = OutboundMessage(text="world", is_final=True)
        await adapter.send("user_2", msg)
        payload = fake.calls[0]["json"]
        assert "context_token" not in payload["msg"]

    asyncio.run(_run())


def test_adapter_send_auth_headers():
    async def _run():
        fake = FakeHttpClient([{"ret": 0}])
        adapter = WeixinAdapter("my_token", "acc1", _http_client=fake)
        await adapter.send("u1", OutboundMessage(text="x"))
        headers = fake.calls[0]["headers"]
        assert headers["AuthorizationType"] == "ilink_bot_token"
        assert headers["Authorization"] == "Bearer my_token"
        assert "X-WECHAT-UIN" in headers
        # X-WECHAT-UIN 应为 8 字符 base64
        assert len(headers["X-WECHAT-UIN"]) == 8

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# WeixinAdapter.edit —— 降级为 send
# ---------------------------------------------------------------------------

def test_adapter_edit_delegates_to_send():
    async def _run():
        fake = FakeHttpClient([{"ret": 0}])
        adapter = WeixinAdapter("tok1", "acc1", _http_client=fake)
        msg = OutboundMessage(text="edited")
        await adapter.edit("user_1", "msg_id", msg)
        # edit → send → 1 次 POST /sendmessage
        assert len(fake.calls) == 1
        assert "sendmessage" in fake.calls[0]["url"]
        assert fake.calls[0]["json"]["msg"]["item_list"][0]["text_item"]["text"] == "edited"

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# context_token 存取（通过轮询更新）
# ---------------------------------------------------------------------------

def test_adapter_context_token_updated_by_poll():
    """模拟一次 getupdates 成功响应，验证 context_tokens 被正确更新，消息被回调。"""
    async def _run():
        received: list[InboundMessage] = []
        poll_response = {
            "ret": 0,
            "errcode": 0,
            "msgs": [
                {
                    "from_user_id": "u1",
                    "context_token": "ctx_new",
                    "item_list": [{"type": 1, "text_item": {"text": "test msg"}}],
                }
            ],
            "get_updates_buf": "new_buf",
        }

        class OneShot:
            """第一次返回消息，之后抛 CancelledError 结束 poll_loop。"""
            def __init__(self):
                self._idx = 0

            async def post(self, url, json=None, headers=None, timeout=None):
                if self._idx == 0:
                    self._idx += 1
                    return FakeResponse(poll_response)
                raise asyncio.CancelledError()

            async def aclose(self):
                pass

        adapter = WeixinAdapter("tok1", "acc1", _http_client=OneShot())

        def on_msg(msg: InboundMessage):
            received.append(msg)

        await adapter.start(on_msg)
        try:
            await asyncio.wait_for(adapter._poll_task, timeout=2.0)
        except (asyncio.TimeoutError, asyncio.CancelledError, Exception):
            pass

        assert adapter._context_tokens.get("u1") == "ctx_new"
        assert len(received) == 1
        assert received[0].text == "test msg"
        assert received[0].platform_user_id == "u1"

    asyncio.run(_run())


def test_adapter_send_picks_up_updated_context_token():
    """context_token 被轮询更新后，后续 send() 能携带新值。"""
    async def _run():
        adapter = WeixinAdapter("tok1", "acc1",
                                _http_client=FakeHttpClient([{"ret": 0}]))
        # 直接写入 context_tokens（模拟轮询写入后的状态）
        adapter._context_tokens["u1"] = "latest_ctx"
        await adapter.send("u1", OutboundMessage(text="reply"))
        payload = adapter._http_client.calls[0]["json"]
        assert payload["msg"]["context_token"] == "latest_ctx"

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# start / stop 生命周期
# ---------------------------------------------------------------------------

def test_adapter_start_stop():
    async def _run():
        class InfiniteEmpty:
            async def post(self, url, json=None, headers=None, timeout=None):
                await asyncio.sleep(0.01)
                return FakeResponse({"ret": 0, "msgs": [], "get_updates_buf": ""})

            async def aclose(self):
                pass

        adapter = WeixinAdapter("tok1", "acc1", _http_client=InfiniteEmpty())
        await adapter.start(lambda m: None)
        assert adapter._poll_task is not None
        assert not adapter._poll_task.done()
        await adapter.stop()
        assert adapter._poll_task is None

    asyncio.run(_run())


def test_adapter_start_idempotent_shutdown_event():
    """stop() 后 _shutdown_event 已 set；再 start() 后应 clear。"""
    async def _run():
        class InfiniteEmpty:
            async def post(self, url, json=None, headers=None, timeout=None):
                await asyncio.sleep(0.01)
                return FakeResponse({"ret": 0, "msgs": []})

            async def aclose(self):
                pass

        adapter = WeixinAdapter("tok1", "acc1", _http_client=InfiniteEmpty())
        await adapter.start(lambda m: None)
        await adapter.stop()
        # 第二次 start 应重置 shutdown event
        await adapter.start(lambda m: None)
        assert not adapter._shutdown_event.is_set()
        await adapter.stop()

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# 登录状态机转换（通过 login_stream + fake client 驱动）
# ---------------------------------------------------------------------------

def test_login_stream_qr_scanned_done():
    """完整登录流程：QR → SCANNED → DONE。"""
    async def _run():
        qr_resp = {"qrcode": "ticket_abc", "qrcode_img_content": "https://img.url/qr.png"}
        wait_resp = {"status": "wait"}
        scaned_resp = {"status": "scaned"}
        confirmed_resp = {
            "status": "confirmed",
            "bot_token": "bt_1",
            "ilink_bot_id": "aid_1",
            "baseurl": "https://ilinkai.weixin.qq.com",
        }
        fake = FakeHttpClient([qr_resp, wait_resp, scaned_resp, confirmed_resp])

        adapter = WeixinAdapter("tok", "acc")
        events: list[LoginEvent] = []
        async for evt in adapter.login_stream(poll_interval=0, _client=fake):
            events.append(evt)

        kinds = [e.kind for e in events]
        assert kinds == [LoginEventKind.QR, LoginEventKind.SCANNED, LoginEventKind.DONE]
        assert events[0].qr_img_content == "https://img.url/qr.png"
        assert events[0].qr_ticket == "ticket_abc"
        assert events[2].bot_token == "bt_1"
        assert events[2].account_id == "aid_1"
        assert events[2].base_url == "https://ilinkai.weixin.qq.com"

    asyncio.run(_run())


def test_login_stream_qr_then_confirmed_without_scaned():
    """服务端跳过 scaned 直接 confirmed（边界情况）。"""
    async def _run():
        qr_resp = {"qrcode": "t1", "qrcode_img_content": "https://url"}
        confirmed_resp = {
            "status": "confirmed",
            "bot_token": "bt",
            "ilink_bot_id": "aid",
            "baseurl": "https://base.url",
        }
        fake = FakeHttpClient([qr_resp, confirmed_resp])
        adapter = WeixinAdapter("tok", "acc")
        events: list[LoginEvent] = []
        async for evt in adapter.login_stream(poll_interval=0, _client=fake):
            events.append(evt)
        kinds = [e.kind for e in events]
        assert kinds == [LoginEventKind.QR, LoginEventKind.DONE]

    asyncio.run(_run())


def test_login_stream_qr_fetch_error():
    """get_bot_qrcode 失败 → 直接 ERROR。"""
    async def _run():
        class ErrorClient:
            async def get(self, url, params=None, headers=None):
                raise RuntimeError("network error")

            async def aclose(self):
                pass

        adapter = WeixinAdapter("tok", "acc")
        events: list[LoginEvent] = []
        async for evt in adapter.login_stream(poll_interval=0, _client=ErrorClient()):
            events.append(evt)
        assert len(events) == 1
        assert events[0].kind == LoginEventKind.ERROR
        assert "network error" in (events[0].error or "")

    asyncio.run(_run())


def test_login_stream_qr_expired():
    """扫码后二维码过期 → ERROR。"""
    async def _run():
        qr_resp = {"qrcode": "t1", "qrcode_img_content": "https://url"}
        expired_resp = {"status": "expired"}
        fake = FakeHttpClient([qr_resp, expired_resp])
        adapter = WeixinAdapter("tok", "acc")
        events: list[LoginEvent] = []
        async for evt in adapter.login_stream(poll_interval=0, _client=fake):
            events.append(evt)
        kinds = [e.kind for e in events]
        assert LoginEventKind.QR in kinds
        assert events[-1].kind == LoginEventKind.ERROR
        assert "expired" in (events[-1].error or "")

    asyncio.run(_run())


def test_login_stream_missing_ticket_raises_error_event():
    """get_bot_qrcode 响应缺少 ticket → ERROR event（不 raise 到调用方）。"""
    async def _run():
        bad_qr = {"qrcode_img_content": "url"}  # 缺 qrcode
        fake = FakeHttpClient([bad_qr])
        adapter = WeixinAdapter("tok", "acc")
        events: list[LoginEvent] = []
        async for evt in adapter.login_stream(poll_interval=0, _client=fake):
            events.append(evt)
        assert len(events) == 1
        assert events[0].kind == LoginEventKind.ERROR
        assert "ticket" in (events[0].error or "")

    asyncio.run(_run())
