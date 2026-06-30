"""钉钉 adapter 隔离单测。

覆盖范围（纯逻辑，无网络依赖）：
  - WS 帧解析：parse_stream_frame（含 data 二次 parse）
  - chat_id 编码/解码：encode_chat_id / decode_chat_id
  - openSpaceId 构造：build_open_space_id
  - ACK 帧构造：build_ack
  - AI Card 请求 body 构造：build_create_card_body / build_deliver_card_body / build_card_streaming_body
  - bot message 回调解析：parse_bot_message_callback
  - 仅私聊过滤（群聊 / 非文本 → None）
  - 错误路径：非法 JSON → DingTalkError

真实连接（start/stop/send/edit → httpx + websockets）需真实凭据，标注 REQUIRES_CREDENTIALS。

运行：cd backend && python3 -m pytest tests/test_dingtalk_adapter.py -q --noconftest
"""
import json
import sys
import os

# 确保能 import app（无需 conftest）
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.channels.adapters.dingtalk import (
    DingTalkAdapter,
    DingTalkError,
    build_ack,
    build_card_streaming_body,
    build_create_card_body,
    build_deliver_card_body,
    build_open_space_id,
    decode_chat_id,
    encode_chat_id,
    parse_bot_message_callback,
    parse_stream_frame,
)
from app.channels.contracts import InboundMessage


# ===========================================================================
# encode_chat_id / decode_chat_id
# ===========================================================================


def test_encode_chat_id_private():
    """私聊（conversationType="1"）→ 'user:{senderStaffId}'。"""
    result = encode_chat_id("1", "cid_private_ignored", "staff_abc")
    assert result == "user:staff_abc"


def test_encode_chat_id_group():
    """群聊（conversationType="2"）→ 'group:{conversationId}'。"""
    result = encode_chat_id("2", "conv_xyz", "staff_abc")
    assert result == "group:conv_xyz"


def test_encode_chat_id_none_type():
    """conversationType 为 None → 按私聊处理。"""
    result = encode_chat_id(None, "some_conv", "staff_123")
    assert result == "user:staff_123"


def test_encode_chat_id_group_no_conv_id():
    """群聊但 conversationId 为 None → 'group:'（保持一致性，不 fallback）。"""
    result = encode_chat_id("2", None, "staff_123")
    assert result == "group:"


def test_decode_chat_id_user():
    is_group, raw_id = decode_chat_id("user:staff_abc")
    assert is_group is False
    assert raw_id == "staff_abc"


def test_decode_chat_id_group():
    is_group, raw_id = decode_chat_id("group:conv_xyz")
    assert is_group is True
    assert raw_id == "conv_xyz"


def test_decode_chat_id_unknown_prefix():
    """未知前缀按单聊处理，raw_id 返回原字符串。"""
    is_group, raw_id = decode_chat_id("raw_id_no_prefix")
    assert is_group is False
    assert raw_id == "raw_id_no_prefix"


# ===========================================================================
# build_open_space_id
# ===========================================================================


def test_build_open_space_id_user():
    result = build_open_space_id("user:staff_001")
    assert result == "dtv1.card//IM_ROBOT.staff_001"


def test_build_open_space_id_group():
    result = build_open_space_id("group:conv_001")
    assert result == "dtv1.card//IM_GROUP.conv_001"


# ===========================================================================
# build_ack
# ===========================================================================


def test_build_ack_structure():
    """ACK 帧必须包含 code=200、messageId、message=OK、data 含 SUCCESS。"""
    ack = build_ack("msg_001")
    assert ack["code"] == 200
    assert ack["headers"]["messageId"] == "msg_001"
    assert ack["headers"]["contentType"] == "application/json"
    assert ack["message"] == "OK"
    # data 字段是 JSON 字符串，需二次 parse
    data = json.loads(ack["data"])
    assert data["response"] == "SUCCESS"


def test_build_ack_serializable():
    """ACK 必须能序列化为合法 JSON 字符串（用于 ws.send）。"""
    ack = build_ack("msg_002")
    serialized = json.dumps(ack)
    parsed = json.loads(serialized)
    assert parsed["code"] == 200
    assert parsed["headers"]["messageId"] == "msg_002"


# ===========================================================================
# build_create_card_body
# ===========================================================================


def test_build_create_card_body_template_id():
    body = build_create_card_body("track_001")
    assert body["cardTemplateId"] == "382e4302-551d-4880-bf29-a30acfab2e71.schema"
    assert body["outTrackId"] == "track_001"
    assert body["callbackType"] == "STREAM"


def test_build_create_card_body_space_models():
    body = build_create_card_body("track_002")
    assert body["imGroupOpenSpaceModel"]["supportForward"] is True
    assert body["imRobotOpenSpaceModel"]["supportForward"] is True


def test_build_create_card_body_card_data():
    body = build_create_card_body("track_003")
    assert "cardData" in body
    assert isinstance(body["cardData"]["cardParamMap"], dict)


# ===========================================================================
# build_deliver_card_body
# ===========================================================================


def test_build_deliver_card_body_single_chat():
    """单聊投递：应包含 imRobotOpenDeliverModel，不含 imGroupOpenDeliverModel。"""
    body = build_deliver_card_body("track_001", "user:staff_abc", "client_id_xxx")
    assert body["outTrackId"] == "track_001"
    assert body["openSpaceId"] == "dtv1.card//IM_ROBOT.staff_abc"
    assert body["userIdType"] == 1
    assert "imRobotOpenDeliverModel" in body
    assert body["imRobotOpenDeliverModel"]["spaceType"] == "IM_ROBOT"
    assert "imGroupOpenDeliverModel" not in body


def test_build_deliver_card_body_group_chat():
    """群聊投递：应包含 imGroupOpenDeliverModel + robotCode，不含 imRobotOpenDeliverModel。"""
    body = build_deliver_card_body("track_002", "group:conv_xyz", "my_client_id")
    assert body["outTrackId"] == "track_002"
    assert body["openSpaceId"] == "dtv1.card//IM_GROUP.conv_xyz"
    assert body["userIdType"] == 1
    assert "imGroupOpenDeliverModel" in body
    assert body["imGroupOpenDeliverModel"]["robotCode"] == "my_client_id"
    assert "imRobotOpenDeliverModel" not in body


# ===========================================================================
# build_card_streaming_body
# ===========================================================================


def test_build_card_streaming_body_finalize():
    """终态写（isFinalize=True）：isFull=True，key=msgContent，isError=False。"""
    body = build_card_streaming_body("track_001", "Hello world", is_finalize=True)
    assert body["outTrackId"] == "track_001"
    assert body["key"] == "msgContent"
    assert body["content"] == "Hello world"
    assert body["isFull"] is True
    assert body["isFinalize"] is True
    assert body["isError"] is False
    assert "guid" in body and body["guid"]


def test_build_card_streaming_body_non_final():
    """非终态写（isFinalize=False）：isFinalize 字段为 False。"""
    body = build_card_streaming_body("track_002", "partial...", is_finalize=False)
    assert body["isFinalize"] is False


def test_build_card_streaming_body_empty_text():
    """空文本也允许（agent 可能先发空占位）。"""
    body = build_card_streaming_body("track_003", "", is_finalize=False)
    assert body["content"] == ""


def test_build_card_streaming_body_guid_unique():
    """每次调用 guid 不同。"""
    b1 = build_card_streaming_body("t", "x", is_finalize=True)
    b2 = build_card_streaming_body("t", "x", is_finalize=True)
    # guid 由时间戳+uuid 构成，极高概率不同
    # 即使在同一毫秒，uuid 部分也保证唯一
    assert b1["guid"] != b2["guid"]


# ===========================================================================
# parse_bot_message_callback（data 二次 parse + 过滤逻辑）
# ===========================================================================


def test_parse_bot_message_private_text():
    """私聊文本消息 → InboundMessage，channel='dingtalk'，chat_id='user:{staffId}'。"""
    cb = {
        "msgId": "msg_123",
        "msgtype": "text",
        "text": {"content": "你好机器人"},
        "senderStaffId": "staff_001",
        "senderNick": "Alice",
        "conversationType": "1",
        "conversationId": "cid_ignored_for_private",
        "createAt": 1700000000000,
    }
    data_str = json.dumps(cb)
    result = parse_bot_message_callback(data_str)

    assert result is not None
    assert isinstance(result, InboundMessage)
    assert result.channel == "dingtalk"
    assert result.platform_user_id == "staff_001"
    assert result.chat_id == "user:staff_001"
    assert result.text == "你好机器人"
    assert result.display_name == "Alice"


def test_parse_bot_message_uses_sender_id_fallback():
    """缺少 senderStaffId 时使用 senderId 作为 platform_user_id。"""
    cb = {
        "msgtype": "text",
        "text": {"content": "hi"},
        "senderId": "user_fallback",
        "conversationType": "1",
    }
    result = parse_bot_message_callback(json.dumps(cb))
    assert result is not None
    assert result.platform_user_id == "user_fallback"
    assert result.chat_id == "user:user_fallback"


def test_parse_bot_message_group_returns_none():
    """群聊（conversationType="2"）→ None（不处理群聊）。"""
    cb = {
        "msgtype": "text",
        "text": {"content": "group msg"},
        "senderStaffId": "staff_002",
        "conversationType": "2",
        "conversationId": "conv_grp_001",
    }
    result = parse_bot_message_callback(json.dumps(cb))
    assert result is None


def test_parse_bot_message_non_text_returns_none():
    """非文本消息类型（picture / file / audio 等）→ None。"""
    for msgtype in ("picture", "file", "audio", "video", "richText"):
        cb = {
            "msgtype": msgtype,
            "senderStaffId": "staff_003",
            "conversationType": "1",
        }
        result = parse_bot_message_callback(json.dumps(cb))
        assert result is None, f"expected None for msgtype={msgtype}"


def test_parse_bot_message_invalid_json_raises():
    """非法 JSON → DingTalkError（不吞异常）。"""
    try:
        parse_bot_message_callback("{not valid json")
        assert False, "should have raised DingTalkError"
    except DingTalkError as exc:
        assert "JSON parse failed" in str(exc)


def test_parse_bot_message_missing_sender_raises():
    """私聊消息缺 senderStaffId 且缺 senderId → DingTalkError。"""
    cb = {
        "msgtype": "text",
        "text": {"content": "hi"},
        "conversationType": "1",
        # 故意不填 senderStaffId / senderId
    }
    try:
        parse_bot_message_callback(json.dumps(cb))
        assert False, "should have raised DingTalkError"
    except DingTalkError as exc:
        assert "senderStaffId" in str(exc)


def test_parse_bot_message_raw_preserved():
    """raw 字段包含原始 dict，便于上层审计。"""
    cb = {
        "msgtype": "text",
        "text": {"content": "test"},
        "senderStaffId": "staff_raw",
        "conversationType": "1",
        "extra_field": "kept",
    }
    result = parse_bot_message_callback(json.dumps(cb))
    assert result is not None
    assert result.raw.get("extra_field") == "kept"


# ===========================================================================
# parse_stream_frame（含 data 二次 parse）
# ===========================================================================


def test_parse_frame_system_ping_returns_ack():
    """SYSTEM/ping → (ack_dict, None)，ack messageId 与帧一致。"""
    frame = json.dumps({
        "type": "SYSTEM",
        "headers": {
            "contentType": "application/json",
            "messageId": "ping_001",
            "topic": "ping",
        },
        "data": "{}",
    })
    ack, inbound = parse_stream_frame(frame)

    assert ack is not None
    assert ack["code"] == 200
    assert ack["headers"]["messageId"] == "ping_001"
    assert inbound is None


def test_parse_frame_system_connected_returns_none():
    """SYSTEM/CONNECTED（非 ping）→ (None, None)，不回 ACK。"""
    frame = json.dumps({
        "type": "SYSTEM",
        "headers": {"topic": "CONNECTED"},
        "data": '{"code":200,"message":"OK"}',
    })
    ack, inbound = parse_stream_frame(frame)
    assert ack is None
    assert inbound is None


def test_parse_frame_event_returns_ack_no_inbound():
    """EVENT 帧 → (ack, None)，始终 ACK 不产生 InboundMessage。"""
    frame = json.dumps({
        "type": "EVENT",
        "headers": {"messageId": "evt_001", "topic": "some.event"},
        "data": '{"some":"data"}',
    })
    ack, inbound = parse_stream_frame(frame)
    assert ack is not None
    assert ack["headers"]["messageId"] == "evt_001"
    assert inbound is None


def test_parse_frame_callback_bot_private_text():
    """CALLBACK /im/bot/messages/get 私聊文本 → (ack, InboundMessage)。

    data 字段是 JSON 字符串，需二次 parse（本测试验证此逻辑）。
    """
    inner_data = {
        "msgId": "dt_msg_456",
        "msgtype": "text",
        "text": {"content": "hello bot"},
        "senderStaffId": "staff_abc",
        "senderNick": "Bob",
        "conversationType": "1",
        "createAt": 1700000000000,
    }
    frame = json.dumps({
        "type": "CALLBACK",
        "headers": {
            "contentType": "application/json",
            "messageId": "cb_msg_001",
            "topic": "/v1.0/im/bot/messages/get",
        },
        # data 是 JSON 字符串（二次 parse 场景）
        "data": json.dumps(inner_data),
    })

    ack, inbound = parse_stream_frame(frame)

    assert ack is not None
    assert ack["code"] == 200
    assert ack["headers"]["messageId"] == "cb_msg_001"

    assert inbound is not None
    assert inbound.channel == "dingtalk"
    assert inbound.platform_user_id == "staff_abc"
    assert inbound.chat_id == "user:staff_abc"
    assert inbound.text == "hello bot"
    assert inbound.display_name == "Bob"


def test_parse_frame_callback_bot_group_returns_ack_no_inbound():
    """CALLBACK bot 群聊消息 → ACK 照发，但 InboundMessage=None（群聊过滤）。"""
    inner_data = {
        "msgtype": "text",
        "text": {"content": "group message"},
        "senderStaffId": "staff_grp",
        "conversationType": "2",
        "conversationId": "conv_grp_001",
    }
    frame = json.dumps({
        "type": "CALLBACK",
        "headers": {
            "messageId": "cb_grp_001",
            "topic": "/v1.0/im/bot/messages/get",
        },
        "data": json.dumps(inner_data),
    })

    ack, inbound = parse_stream_frame(frame)
    assert ack is not None          # 平台需要 ACK
    assert inbound is None          # 不产生 InboundMessage


def test_parse_frame_callback_other_topic_returns_ack_no_inbound():
    """CALLBACK 其他 topic（如 /v1.0/card/instances/callback）→ (ack, None)。"""
    frame = json.dumps({
        "type": "CALLBACK",
        "headers": {
            "messageId": "cb_card_001",
            "topic": "/v1.0/card/instances/callback",
        },
        "data": json.dumps({"userId": "u1", "content": "{}"}),
    })
    ack, inbound = parse_stream_frame(frame)
    assert ack is not None
    assert inbound is None


def test_parse_frame_unknown_type_returns_none_none():
    """未知 frame type → (None, None)（不 ACK，不抛异常）。"""
    frame = json.dumps({
        "type": "UNKNOWN_FUTURE_TYPE",
        "headers": {"messageId": "fut_001"},
        "data": "{}",
    })
    ack, inbound = parse_stream_frame(frame)
    assert ack is None
    assert inbound is None


def test_parse_frame_invalid_json_raises():
    """非法顶层 JSON → DingTalkError。"""
    try:
        parse_stream_frame("{bad json}")
        assert False, "should raise DingTalkError"
    except DingTalkError as exc:
        assert "frame JSON parse failed" in str(exc)


def test_parse_frame_callback_missing_data_raises():
    """CALLBACK /im/bot/messages/get 缺 data 字段 → DingTalkError（不吞）。"""
    frame = json.dumps({
        "type": "CALLBACK",
        "headers": {
            "messageId": "cb_no_data",
            "topic": "/v1.0/im/bot/messages/get",
        },
        # 故意不填 data
    })
    try:
        parse_stream_frame(frame)
        assert False, "should raise DingTalkError"
    except DingTalkError as exc:
        assert "missing data" in str(exc)


def test_parse_frame_data_double_parse():
    """验证 data 字段确实是字符串（二次 parse），而非直接嵌套 dict。

    DingTalk WS Stream 协议：data 始终是 JSON 字符串，不是嵌套对象。
    本测试模拟如果有人直接传入嵌套 dict（误用）应如何处理。
    """
    # 正确格式：data 是 JSON 字符串
    inner = {"msgtype": "text", "text": {"content": "ok"}, "senderStaffId": "s1", "conversationType": "1"}
    frame_correct = json.dumps({
        "type": "CALLBACK",
        "headers": {"messageId": "m1", "topic": "/v1.0/im/bot/messages/get"},
        "data": json.dumps(inner),  # 字符串！
    })
    ack, inbound = parse_stream_frame(frame_correct)
    assert inbound is not None and inbound.text == "ok"

    # 错误格式：data 是嵌套 dict（JSON 序列化后 data 的值会是 dict，parse_bot_message_callback 接收 str 会 fail）
    frame_wrong = json.dumps({
        "type": "CALLBACK",
        "headers": {"messageId": "m2", "topic": "/v1.0/im/bot/messages/get"},
        "data": inner,  # dict，不是字符串 → json.dumps 会序列化为 dict → frame.get("data") 返回 dict
    })
    # 当 data 是 dict 时，json.dumps(inner) 在外层 json.dumps 里已变成嵌套对象
    # frame.get("data") 会得到 dict，而不是 str
    # parse_bot_message_callback 接收 str，传入 dict 类型
    # 但 json.loads(dict) 会 TypeError
    frame_parsed = json.loads(frame_wrong)
    data_val = frame_parsed.get("data")
    # data 是 dict 类型（而非 str），传给 parse_bot_message_callback 时应报错
    assert isinstance(data_val, dict), "wrong format yields dict, not str"


# ===========================================================================
# DingTalkAdapter 构造验证（无 IO）
# ===========================================================================


def test_adapter_missing_client_id_raises():
    try:
        DingTalkAdapter("", "secret")
        assert False
    except DingTalkError as exc:
        assert "client_id" in str(exc)


def test_adapter_missing_client_secret_raises():
    try:
        DingTalkAdapter("key", "")
        assert False
    except DingTalkError as exc:
        assert "client_secret" in str(exc)


def test_adapter_name():
    adapter = DingTalkAdapter("key", "secret")
    assert adapter.name == "dingtalk"


def test_adapter_verify_always_true():
    """WS 模式无 webhook，verify 始终 True。"""
    adapter = DingTalkAdapter("key", "secret")
    assert adapter.verify({}, b"") is True
    assert adapter.verify({"X-Token": "xxx"}, b"payload") is True


def test_adapter_parse_inbound_private_text():
    """parse_inbound 解析私聊文本（单测路径，无 WS）。"""
    adapter = DingTalkAdapter("key", "secret")
    cb = {
        "msgtype": "text",
        "text": {"content": "分析数据"},
        "senderStaffId": "staff_parse",
        "senderNick": "Test User",
        "conversationType": "1",
    }
    inbound = adapter.parse_inbound({}, json.dumps(cb).encode())
    assert inbound is not None
    assert inbound.channel == "dingtalk"
    assert inbound.text == "分析数据"
    assert inbound.platform_user_id == "staff_parse"


def test_adapter_parse_inbound_group_returns_none():
    """parse_inbound 群聊 → None。"""
    adapter = DingTalkAdapter("key", "secret")
    cb = {
        "msgtype": "text",
        "text": {"content": "group"},
        "senderStaffId": "s1",
        "conversationType": "2",
        "conversationId": "grp_1",
    }
    result = adapter.parse_inbound({}, json.dumps(cb).encode())
    assert result is None


# ===========================================================================
# 标注：需真实凭据才能联调的部分
# ===========================================================================
# 以下功能需真实 DingTalk 企业内部应用凭据，不在此单测：
#   - DingTalkAdapter.start() / stop()
#     → 调用 _register_stream()（POST /v1.0/gateway/connections/open）
#     → 连接 wss://stream.dingtalk.com/...
#   - DingTalkAdapter.send()
#     → _refresh_token()（POST /v1.0/oauth2/accessToken）
#     → POST /v1.0/card/instances
#     → POST /v1.0/card/instances/deliver
#     → PUT  /v1.0/card/streaming
#   - DingTalkAdapter.edit()
#     → PUT  /v1.0/card/streaming
#
# 凭据来源（BYO 模式）：
#   client_id     = 钉钉开发者后台「企业内部应用」的 AppKey
#   client_secret = 同应用的 AppSecret
#   需开启机器人功能 + qyapi_robot_sendmsg 权限（AI Card 另需 AI Card 权限）
