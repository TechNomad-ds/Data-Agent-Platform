"""飞书 adapter 纯逻辑单测。

覆盖范围（不需真实凭据/网络）：
  1. PbFrame 编码 → 解码往返（data 帧含 payload、控制帧 method=0、unicode payload）
  2. 畸形字节 raise ValueError
  3. build_ack_frame（保留 type/message_id/trace_id，追加 biz_rt=0，payload={code:200}）
  4. FragmentCache 分片重组
  5. _parse_message_event（文本成功、非文本→None、缺 open_id→None、空 text→None）
  6. build_interactive_card（结构正确、特殊字符不破坏 JSON）
  7. _extract_service_id（有/无参数、无 query）
  8. event dedup（首次通过、重复跳过、不同 id 各自独立）

运行：cd <repo>/backend && python3 -m pytest tests/test_feishu_adapter.py -q --noconftest
"""
import asyncio
import json

import pytest

from app.channels.adapters.feishu import (
    FragmentCache,
    PbFrame,
    PbHeader,
    build_ack_frame,
    build_interactive_card,
    build_ping_frame,
    decode_frame,
    encode_frame,
    get_header,
    _extract_service_id,
    _parse_message_event,
    FeishuAdapter,
    METHOD_CONTROL,
    METHOD_DATA,
)

# ---------------------------------------------------------------------------
# 1. PbFrame 编解码往返
# ---------------------------------------------------------------------------

def test_roundtrip_data_frame():
    """完整 DATA 帧含所有字段，往返后字段一致。"""
    original = PbFrame(
        seq_id=42,
        log_id=99,
        service=1,
        method=METHOD_DATA,
        headers=[
            PbHeader(key="type", value="event"),
            PbHeader(key="message_id", value="msg-001"),
        ],
        payload_encoding="gzip",
        payload_type="json",
        payload=b'{"key":"value"}',
        log_id_new="new-log-id-001",
    )
    raw = encode_frame(original)
    restored = decode_frame(raw)
    assert restored.seq_id == 42
    assert restored.log_id == 99
    assert restored.service == 1
    assert restored.method == METHOD_DATA
    assert len(restored.headers) == 2
    assert restored.headers[0].key == "type"
    assert restored.headers[0].value == "event"
    assert restored.headers[1].key == "message_id"
    assert restored.headers[1].value == "msg-001"
    assert restored.payload_encoding == "gzip"
    assert restored.payload_type == "json"
    assert restored.payload == b'{"key":"value"}'
    assert restored.log_id_new == "new-log-id-001"


def test_roundtrip_control_frame():
    """控制帧 method=0（METHOD_CONTROL = protobuf default），往返 method 仍为 0。"""
    frame = PbFrame(
        seq_id=1,
        service=3,
        method=METHOD_CONTROL,
        headers=[PbHeader(key="type", value="ping")],
    )
    restored = decode_frame(encode_frame(frame))
    assert restored.method == METHOD_CONTROL
    assert restored.service == 3
    assert get_header(restored.headers, "type") == "ping"


def test_roundtrip_unicode_payload():
    """payload 含中文 UTF-8，往返字节不变。"""
    text = "你好，飞书！🎉"
    b = text.encode("utf-8")
    frame = PbFrame(method=METHOD_DATA, payload=b)
    restored = decode_frame(encode_frame(frame))
    assert restored.payload == b


def test_roundtrip_empty_frame():
    """空帧（全默认值）编码为空字节，解码返回全默认 PbFrame。"""
    raw = encode_frame(PbFrame())
    assert raw == b""
    restored = decode_frame(raw)
    assert restored.seq_id == 0
    assert restored.method == METHOD_CONTROL
    assert restored.headers == []
    assert restored.payload == b""


def test_roundtrip_large_varint():
    """seq_id 超 32-bit 的大整数能正确往返。"""
    frame = PbFrame(seq_id=2**48 + 7, log_id=2**63 - 1)
    restored = decode_frame(encode_frame(frame))
    assert restored.seq_id == (2**48 + 7) & 0xFFFF_FFFF_FFFF_FFFF
    # log_id 在合法 uint64 范围内
    assert restored.log_id == 2**63 - 1


def test_roundtrip_multiple_headers():
    """多个 header 顺序保留。"""
    frame = PbFrame(
        method=METHOD_DATA,
        headers=[
            PbHeader(key="type", value="event"),
            PbHeader(key="message_id", value="m1"),
            PbHeader(key="trace_id", value="t1"),
            PbHeader(key="seq", value="2"),
            PbHeader(key="sum", value="5"),
        ],
    )
    restored = decode_frame(encode_frame(frame))
    assert len(restored.headers) == 5
    assert get_header(restored.headers, "seq") == "2"
    assert get_header(restored.headers, "sum") == "5"


def test_decode_invalid_bytes_raises():
    """高位全 1 的截断 varint 应该 raise ValueError。"""
    with pytest.raises(ValueError, match="截断的 varint"):
        decode_frame(b"\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF")


def test_decode_unknown_wire_type_raises():
    """wire type = 5 (32-bit) 不被支持，应 raise ValueError。"""
    # 构造 field_num=1 wire_type=5 tag: (1<<3)|5 = 13 = 0x0D
    with pytest.raises(ValueError, match="wire type"):
        decode_frame(b"\x0D\x00\x00\x00\x00")


# ---------------------------------------------------------------------------
# 2. build_ping_frame / build_ack_frame
# ---------------------------------------------------------------------------

def test_build_ping_frame():
    frame = build_ping_frame(service_id=5)
    assert frame.method == METHOD_CONTROL
    assert frame.service == 5
    assert get_header(frame.headers, "type") == "ping"


def test_build_ack_frame_structure():
    """ACK 帧保留 type/message_id/trace_id，追加 biz_rt=0，payload={code:200}。"""
    original = PbFrame(
        seq_id=10,
        log_id=20,
        service=2,
        method=METHOD_DATA,
        headers=[
            PbHeader(key="type", value="event"),
            PbHeader(key="message_id", value="msg-777"),
            PbHeader(key="trace_id", value="tr-888"),
            PbHeader(key="seq", value="0"),         # 不应保留
            PbHeader(key="sum", value="1"),          # 不应保留
        ],
        payload=b"some event payload",
        log_id_new="log-new",
    )
    ack = build_ack_frame(original)
    assert ack.seq_id == 10
    assert ack.log_id == 20
    assert ack.service == 2
    assert ack.method == METHOD_DATA
    assert ack.log_id_new == "log-new"

    header_keys = [h.key for h in ack.headers]
    assert "type" in header_keys
    assert "message_id" in header_keys
    assert "trace_id" in header_keys
    assert "seq" not in header_keys
    assert "sum" not in header_keys
    assert "biz_rt" in header_keys

    assert get_header(ack.headers, "type") == "event"
    assert get_header(ack.headers, "message_id") == "msg-777"
    assert get_header(ack.headers, "trace_id") == "tr-888"
    assert get_header(ack.headers, "biz_rt") == "0"

    assert ack.payload == b'{"code":200}'


def test_build_ack_frame_roundtrips():
    """ACK 帧编码 → 解码后字段不变。"""
    original = PbFrame(
        seq_id=1,
        method=METHOD_DATA,
        headers=[PbHeader(key="type", value="event"), PbHeader(key="message_id", value="m1")],
    )
    ack = build_ack_frame(original)
    restored = decode_frame(encode_frame(ack))
    assert restored.payload == b'{"code":200}'
    assert get_header(restored.headers, "biz_rt") == "0"


# ---------------------------------------------------------------------------
# 3. FragmentCache 分片重组
# ---------------------------------------------------------------------------

def test_fragment_single():
    """单片消息立即返回。"""
    cache = FragmentCache()
    result = cache.push("m1", sum_=1, seq=0, data=b"hello")
    assert result == b"hello"


def test_fragment_multi_in_order():
    """3 片按顺序到齐后合并。"""
    cache = FragmentCache()
    assert cache.push("m2", 3, 0, b"foo") is None
    assert cache.push("m2", 3, 1, b"bar") is None
    result = cache.push("m2", 3, 2, b"baz")
    assert result == b"foobarbaz"


def test_fragment_multi_out_of_order():
    """乱序到达，全到后合并保原序。"""
    cache = FragmentCache()
    assert cache.push("m3", 3, 2, b"C") is None
    assert cache.push("m3", 3, 0, b"A") is None
    result = cache.push("m3", 3, 1, b"B")
    assert result == b"ABC"


def test_fragment_independent_messages():
    """两个 message_id 互不干扰。"""
    cache = FragmentCache()
    assert cache.push("ma", 2, 0, b"1") is None
    assert cache.push("mb", 2, 0, b"X") is None
    r1 = cache.push("ma", 2, 1, b"2")
    r2 = cache.push("mb", 2, 1, b"Y")
    assert r1 == b"12"
    assert r2 == b"XY"


def test_fragment_cleared_after_completion():
    """完成后条目清除，再 push 同 id 从头开始。"""
    cache = FragmentCache()
    cache.push("mx", 1, 0, b"done")
    # 再次 push 同 id，sum=2 — 不应与之前合并
    assert cache.push("mx", 2, 0, b"part1") is None
    result = cache.push("mx", 2, 1, b"part2")
    assert result == b"part1part2"


def test_fragment_cleanup_removes_stale(monkeypatch):
    """cleanup 按 TTL 清除未完成分片，完成的条目不受影响（已删除）。"""
    import time
    cache = FragmentCache()
    cache.push("stale", 3, 0, b"x")  # 未完成

    # 模拟时间流逝超过 TTL（patch monotonictime）
    import app.channels.adapters.feishu as feishu_mod
    real_mono = time.monotonic
    monkeypatch.setattr(feishu_mod.time, "monotonic", lambda: real_mono() + 1000)
    cache.cleanup(ttl=300)
    # "stale" 应被清除
    assert "stale" not in cache._entries


# ---------------------------------------------------------------------------
# 4. _parse_message_event
# ---------------------------------------------------------------------------

def _make_event(
    open_id="ou_abc123",
    chat_id="oc_chat999",
    message_type="text",
    content_text="你好",
) -> dict:
    return {
        "sender": {"sender_id": {"open_id": open_id}},
        "message": {
            "chat_id": chat_id,
            "message_type": message_type,
            "content": json.dumps({"text": content_text}) if content_text is not None else "{}",
        },
    }


def test_parse_message_event_success():
    """标准文本消息正确解析为 InboundMessage。"""
    ev = _make_event(open_id="ou_user1", chat_id="oc_room1", content_text="帮我分析数据")
    msg = _parse_message_event(ev)
    assert msg is not None
    assert msg.channel == "feishu"
    assert msg.platform_user_id == "ou_user1"
    assert msg.chat_id == "oc_room1"
    assert msg.text == "帮我分析数据"


def test_parse_message_event_unsupported_type_returns_none():
    """既非 text 也非 image/file 的类型（如 audio）返回 None。"""
    ev = _make_event(message_type="audio", content_text=None)
    assert _parse_message_event(ev) is None


def _make_media_event(message_type, content: dict, message_id="om_msg1",
                      open_id="ou_abc123", chat_id="oc_chat999") -> dict:
    return {
        "sender": {"sender_id": {"open_id": open_id}},
        "message": {
            "chat_id": chat_id,
            "message_id": message_id,
            "message_type": message_type,
            "content": json.dumps(content),
        },
    }


def test_parse_message_event_image_attachment():
    """图片消息 → InboundMessage 带一个 image 附件（locator=message_id）。"""
    ev = _make_media_event("image", {"image_key": "img_v2_xyz"}, message_id="om_1")
    msg = _parse_message_event(ev)
    assert msg is not None and msg.text == ""
    assert len(msg.attachments) == 1
    att = msg.attachments[0]
    assert att.kind == "image"
    assert att.resource_key == "img_v2_xyz"
    assert att.locator == "om_1"


def test_parse_message_event_file_attachment_keeps_filename():
    """文件消息 → file 附件，保留原文件名。"""
    ev = _make_media_event("file", {"file_key": "file_v2_abc", "file_name": "报表.xlsx"})
    msg = _parse_message_event(ev)
    assert msg is not None
    att = msg.attachments[0]
    assert att.kind == "file"
    assert att.resource_key == "file_v2_abc"
    assert att.name == "报表.xlsx"


def test_parse_message_event_attachment_missing_key_returns_none():
    """图片/文件缺少 key → None。"""
    assert _parse_message_event(_make_media_event("image", {})) is None
    assert _parse_message_event(_make_media_event("file", {})) is None


def test_parse_message_event_attachment_missing_message_id_returns_none():
    """附件消息缺少 message_id（无法下载）→ None。"""
    ev = _make_media_event("image", {"image_key": "k"}, message_id="")
    assert _parse_message_event(ev) is None


class _FakeBinResp:
    def __init__(self, content=b"", headers=None, payload=None):
        self.content = content
        self.headers = headers or {"content-type": "application/octet-stream"}
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class _FakeHttpGet:
    def __init__(self, resp):
        self._resp = resp
        self.last_url = None

    async def get(self, url, headers=None):
        self.last_url = url
        return self._resp


def test_download_attachment_returns_bytes():
    """download_attachment 拼对 URL（含 type=file）并返回二进制。"""
    from app.channels.contracts import InboundAttachment
    adapter = FeishuAdapter(app_id="x", app_secret="y")
    adapter._http = _FakeHttpGet(_FakeBinResp(content=b"PDFDATA"))

    async def fake_token():
        return "tok"
    adapter._get_token = fake_token

    att = InboundAttachment(kind="file", name="r.pdf", resource_key="fk1", locator="om_9")
    data = asyncio.run(adapter.download_attachment(att))
    assert data == b"PDFDATA"
    assert "/im/v1/messages/om_9/resources/fk1?type=file" in adapter._http.last_url


def test_download_attachment_json_error_raises():
    """资源接口返回 JSON（content-type application/json）= 出错 → raise。"""
    from app.channels.contracts import InboundAttachment
    adapter = FeishuAdapter(app_id="x", app_secret="y")
    adapter._http = _FakeHttpGet(_FakeBinResp(
        headers={"content-type": "application/json"},
        payload={"code": 99991663, "msg": "no permission"}))

    async def fake_token():
        return "tok"
    adapter._get_token = fake_token

    att = InboundAttachment(kind="image", name="i.jpg", resource_key="ik1", locator="om_9")
    with pytest.raises(RuntimeError, match="no permission"):
        asyncio.run(adapter.download_attachment(att))


def test_parse_message_event_missing_open_id_returns_none():
    """sender.sender_id.open_id 缺失时返回 None。"""
    ev = _make_event()
    ev["sender"]["sender_id"]["open_id"] = ""  # 空串也算缺失
    assert _parse_message_event(ev) is None


def test_parse_message_event_empty_text_returns_none():
    """content.text 为空时返回 None（无意义消息）。"""
    ev = {
        "sender": {"sender_id": {"open_id": "ou_x"}},
        "message": {
            "chat_id": "oc_y",
            "message_type": "text",
            "content": json.dumps({"text": ""}),
        },
    }
    assert _parse_message_event(ev) is None


def test_parse_message_event_malformed_content_returns_none():
    """content 字段不是合法 JSON 时返回 None（不 crash）。"""
    ev = {
        "sender": {"sender_id": {"open_id": "ou_x"}},
        "message": {
            "chat_id": "oc_y",
            "message_type": "text",
            "content": "not-json{{",
        },
    }
    assert _parse_message_event(ev) is None


def test_parse_message_event_missing_sender_returns_none():
    """缺少 sender 字段时返回 None（不 crash）。"""
    ev: dict = {"message": {"chat_id": "oc_y", "message_type": "text", "content": '{"text":"hi"}'}}
    assert _parse_message_event(ev) is None


# ---------------------------------------------------------------------------
# 5. build_interactive_card
# ---------------------------------------------------------------------------

def test_build_interactive_card_structure():
    """生成的 JSON 含 elements[0].tag=markdown + content=传入文字。"""
    text = "分析结果如下：\n- 指标 A: 92%"
    card_str = build_interactive_card(text)
    card = json.loads(card_str)
    assert "elements" in card
    assert len(card["elements"]) == 1
    el = card["elements"][0]
    assert el["tag"] == "markdown"
    assert el["content"] == text


def test_build_interactive_card_valid_json():
    """含引号、换行、表情的文本不破坏 JSON 有效性。"""
    tricky = 'He said "hello"\n世界 🌍 \t end'
    card_str = build_interactive_card(tricky)
    parsed = json.loads(card_str)
    assert parsed["elements"][0]["content"] == tricky


def test_build_interactive_card_empty_text():
    """空文字也能构建有效 card（不 raise）。"""
    card_str = build_interactive_card("")
    card = json.loads(card_str)
    assert card["elements"][0]["content"] == ""


# ---------------------------------------------------------------------------
# 6. _extract_service_id
# ---------------------------------------------------------------------------

def test_extract_service_id_present():
    url = "wss://open.feishu.cn/ws?service_id=42&token=abc"
    assert _extract_service_id(url) == 42


def test_extract_service_id_absent():
    url = "wss://open.feishu.cn/ws?token=abc&other=1"
    assert _extract_service_id(url) == 0


def test_extract_service_id_no_query():
    url = "wss://open.feishu.cn/ws"
    assert _extract_service_id(url) == 0


def test_extract_service_id_malformed_value():
    url = "wss://host/ws?service_id=notanint"
    assert _extract_service_id(url) == 0


# ---------------------------------------------------------------------------
# 7. event dedup（asyncio.run 驱动，不依赖 pytest-asyncio）
# ---------------------------------------------------------------------------

def test_event_dedup_first_seen_passes():
    """首次见到的 event_id，_parse_event 不会返回 None（假设是文本消息）。"""
    adapter = FeishuAdapter(app_id="fake_id", app_secret="fake_secret", dedup_ttl=600)

    envelope = {
        "header": {"event_id": "eid-001", "event_type": "im.message.receive_v1"},
        "event": {
            "sender": {"sender_id": {"open_id": "ou_user1"}},
            "message": {
                "chat_id": "oc_chat1",
                "message_type": "text",
                "content": json.dumps({"text": "第一条消息"}),
            },
        },
    }

    result = asyncio.run(adapter._parse_event(json.dumps(envelope)))
    assert result is not None
    assert result.text == "第一条消息"


def test_event_dedup_duplicate_returns_none():
    """同一 event_id 第二次 _parse_event 返回 None（去重命中）。"""
    adapter = FeishuAdapter(app_id="fake_id", app_secret="fake_secret", dedup_ttl=600)

    envelope = {
        "header": {"event_id": "eid-dup", "event_type": "im.message.receive_v1"},
        "event": {
            "sender": {"sender_id": {"open_id": "ou_x"}},
            "message": {
                "chat_id": "oc_y",
                "message_type": "text",
                "content": json.dumps({"text": "重复"}),
            },
        },
    }

    text = json.dumps(envelope)
    r1 = asyncio.run(adapter._parse_event(text))
    r2 = asyncio.run(adapter._parse_event(text))
    assert r1 is not None
    assert r2 is None


def test_event_dedup_different_ids_both_pass():
    """不同 event_id 各自独立不互相影响。"""
    adapter = FeishuAdapter(app_id="fake_id", app_secret="fake_secret", dedup_ttl=600)

    def make_env(eid: str, text: str) -> str:
        return json.dumps({
            "header": {"event_id": eid, "event_type": "im.message.receive_v1"},
            "event": {
                "sender": {"sender_id": {"open_id": "ou_user"}},
                "message": {
                    "chat_id": "oc_c",
                    "message_type": "text",
                    "content": json.dumps({"text": text}),
                },
            },
        })

    r1 = asyncio.run(adapter._parse_event(make_env("eid-A", "消息A")))
    r2 = asyncio.run(adapter._parse_event(make_env("eid-B", "消息B")))
    assert r1 is not None and r1.text == "消息A"
    assert r2 is not None and r2.text == "消息B"


def test_event_dedup_unknown_event_type_returns_none():
    """不支持的 event_type 即使首次出现也返回 None。"""
    adapter = FeishuAdapter(app_id="fake_id", app_secret="fake_secret")

    envelope = {
        "header": {"event_id": "eid-type", "event_type": "contact.user.created_v3"},
        "event": {},
    }
    result = asyncio.run(adapter._parse_event(json.dumps(envelope)))
    assert result is None


def test_event_dedup_malformed_json_returns_none():
    """畸形 JSON 不 crash，返回 None。"""
    adapter = FeishuAdapter(app_id="fake_id", app_secret="fake_secret")
    result = asyncio.run(adapter._parse_event("{{not valid json"))
    assert result is None
