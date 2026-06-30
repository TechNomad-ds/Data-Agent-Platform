"""DingTalk 渠道 adapter — WS Stream 出站连接。

协议参考: 同类引擎/其源码/src/plugins/dingtalk/。
BYO 凭据: client_id + client_secret（钉钉企业内部应用）。

出站连接模型（免公网回调）：
  1. POST /v1.0/oauth2/accessToken → access_token（缓存 2h，提前 5min 刷）
  2. POST /v1.0/gateway/connections/open → endpoint + ticket（body 用 clientId/clientSecret，不用 token）
  3. wss://{endpoint}?ticket={ticket} → WS Stream JSON 帧
  4. 帧处理：SYSTEM/ping → ACK；CALLBACK/bot/messages → 解析 → on_inbound；EVENT → ACK
  5. 发消息：AI Card 三段（POST create → POST deliver → PUT streaming isFinalize=True）

设计决策（docs/channel-integration-design.md §1）：
- 仅处理私聊（conversationType == "1"），群聊直接丢弃
- 只发终态（AgentBridge 跑完发一条，isFinalize=True）
- 断线指数退避重连，最多 MAX_RECONNECT_ATTEMPTS 次

纯逻辑函数（parse_stream_frame / encode_chat_id / build_ack 等）只依赖 stdlib+pydantic，
可在无网络环境下隔离单测。I/O 部分（httpx / websockets）仅在运行时 import。
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine, Optional

from app.channels.contracts import InboundMessage, OutboundMessage

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DINGTALK_API_BASE = "https://api.dingtalk.com"

# AI Card 模板 ID（来自 同类引擎 plugin.rs）
AI_CARD_TEMPLATE_ID = "382e4302-551d-4880-bf29-a30acfab2e71.schema"

# token 提前 5 分钟刷
TOKEN_REFRESH_MARGIN_SECS = 300

MAX_RECONNECT_ATTEMPTS = 10
MAX_RECONNECT_DELAY_SECS = 30

# ---------------------------------------------------------------------------
# Errors（禁止 fallback 兜底，上层负责处理）
# ---------------------------------------------------------------------------


class DingTalkError(RuntimeError):
    """钉钉 adapter 运行时错误。失败 raise，不降级。"""


# ---------------------------------------------------------------------------
# Pure logic helpers（只依赖 stdlib + pydantic，隔离单测）
# ---------------------------------------------------------------------------


def encode_chat_id(
    conversation_type: Optional[str],
    conversation_id: Optional[str],
    sender_staff_id: str,
) -> str:
    """编码渠道内唯一会话 ID。

    conversationType == "2"（群聊） → 'group:{conversationId}'
    其余（私聊 "1" 或未知）         → 'user:{senderStaffId}'
    """
    if conversation_type == "2":
        return f"group:{conversation_id or ''}"
    return f"user:{sender_staff_id}"


def decode_chat_id(chat_id: str) -> tuple[bool, str]:
    """解码 chat_id → (is_group, raw_id)。"""
    if chat_id.startswith("group:"):
        return True, chat_id[len("group:"):]
    if chat_id.startswith("user:"):
        return False, chat_id[len("user:"):]
    # 未知格式：按单聊处理
    return False, chat_id


def build_open_space_id(chat_id: str) -> str:
    """构造 AI Card 投递用的 openSpaceId。

    群聊: dtv1.card//IM_GROUP.{conversationId}
    单聊: dtv1.card//IM_ROBOT.{staffId}
    """
    is_group, raw_id = decode_chat_id(chat_id)
    if is_group:
        return f"dtv1.card//IM_GROUP.{raw_id}"
    return f"dtv1.card//IM_ROBOT.{raw_id}"


def build_ack(message_id: str) -> dict[str, Any]:
    """构造 WS Stream ACK 帧（CALLBACK 和 SYSTEM/ping 均需回复）。"""
    return {
        "code": 200,
        "headers": {
            "contentType": "application/json",
            "messageId": message_id,
        },
        "message": "OK",
        "data": '{"response":"SUCCESS"}',
    }


def _generate_out_track_id() -> str:
    """生成唯一 AI Card outTrackId（时间戳 + 随机后缀）。"""
    return f"dat_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}"


def _generate_guid() -> str:
    """生成 streaming write 操作的唯一 guid。"""
    return f"{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}"


def build_create_card_body(out_track_id: str) -> dict[str, Any]:
    """构造 POST /v1.0/card/instances 请求 body。

    callbackType=STREAM 表示后续用 streaming write 推内容。
    cardParamMap 初始为空，内容由 streaming write 填充。
    """
    return {
        "cardTemplateId": AI_CARD_TEMPLATE_ID,
        "outTrackId": out_track_id,
        "callbackType": "STREAM",
        "cardData": {"cardParamMap": {}},
        "imGroupOpenSpaceModel": {"supportForward": True},
        "imRobotOpenSpaceModel": {"supportForward": True},
    }


def build_deliver_card_body(
    out_track_id: str,
    chat_id: str,
    client_id: str,
) -> dict[str, Any]:
    """构造 POST /v1.0/card/instances/deliver 请求 body。

    单聊需 imRobotOpenDeliverModel；群聊需 imGroupOpenDeliverModel + robotCode。
    """
    is_group, _ = decode_chat_id(chat_id)
    body: dict[str, Any] = {
        "outTrackId": out_track_id,
        "openSpaceId": build_open_space_id(chat_id),
        "userIdType": 1,
    }
    if is_group:
        body["imGroupOpenDeliverModel"] = {"robotCode": client_id}
    else:
        body["imRobotOpenDeliverModel"] = {"spaceType": "IM_ROBOT"}
    return body


def build_card_streaming_body(
    out_track_id: str,
    text: str,
    *,
    is_finalize: bool,
) -> dict[str, Any]:
    """构造 PUT /v1.0/card/streaming 请求 body。

    isFull=True 表示全量替换（非追加）。
    is_finalize=True 标记终态，卡片内容锁定。
    """
    return {
        "outTrackId": out_track_id,
        "key": "msgContent",
        "content": text,
        "isFull": True,
        "isFinalize": is_finalize,
        "isError": False,
        "guid": _generate_guid(),
    }


def parse_bot_message_callback(data_str: str) -> Optional[InboundMessage]:
    """解析 CALLBACK /im/bot/messages/get 的 data 字符串（二次 JSON parse）→ InboundMessage。

    过滤规则：
    - conversationType != "1"（非私聊）→ None
    - msgtype != "text" → None（忽略图片/文件等）
    - 缺少 senderStaffId 且缺少 senderId → raise DingTalkError

    Returns:
        InboundMessage if parseable private text message, else None.

    Raises:
        DingTalkError: data 不是合法 JSON，或私聊消息缺少 sender 标识。
    """
    try:
        cb: dict[str, Any] = json.loads(data_str)
    except json.JSONDecodeError as exc:
        raise DingTalkError(f"bot message data JSON parse failed: {exc}") from exc

    # 仅私聊
    conversation_type = cb.get("conversationType")
    if conversation_type != "1":
        return None

    # 取发送者 ID（senderStaffId 优先，fallback senderId）
    sender_staff_id: str = cb.get("senderStaffId") or cb.get("senderId") or ""
    if not sender_staff_id:
        raise DingTalkError("private bot message missing senderStaffId/senderId")

    # 仅处理文本消息
    msgtype = cb.get("msgtype", "text")
    if msgtype != "text":
        return None

    text_payload = cb.get("text") or {}
    text: str = text_payload.get("content", "") if isinstance(text_payload, dict) else ""

    chat_id = encode_chat_id(
        conversation_type,
        cb.get("conversationId"),
        sender_staff_id,
    )

    return InboundMessage(
        channel="dingtalk",
        platform_user_id=sender_staff_id,
        chat_id=chat_id,
        text=text,
        display_name=cb.get("senderNick"),
        raw=cb,
    )


def parse_stream_frame(
    raw_text: str,
) -> tuple[Optional[dict[str, Any]], Optional[InboundMessage]]:
    """解析一条 WS Stream JSON 文本帧。

    返回 (ack_dict | None, InboundMessage | None)：

    SYSTEM/ping   → (ack, None)            需回 ACK
    SYSTEM/other  → (None, None)           无需 ACK
    EVENT/*       → (ack, None)            需回 ACK
    CALLBACK/bot  → (ack, inbound | None)  需回 ACK，inbound 仅私聊文本非 None
    CALLBACK/其他 → (ack, None)            需回 ACK（扩展点）
    未知 type     → (None, None)

    Raises:
        DingTalkError: raw_text 不是合法 JSON，或 CALLBACK data 解析失败。
    """
    try:
        frame: dict[str, Any] = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise DingTalkError(f"stream frame JSON parse failed: {exc}") from exc

    frame_type: str = frame.get("type", "")
    headers: dict[str, Any] = frame.get("headers") or {}
    message_id: str = headers.get("messageId", "")
    topic: str = headers.get("topic", "")
    data_str: Optional[str] = frame.get("data")

    if frame_type == "SYSTEM":
        if topic == "ping":
            return build_ack(message_id), None
        # CONNECTED / DISCONNECT 等：不回 ACK
        return None, None

    if frame_type == "CALLBACK":
        ack = build_ack(message_id)
        if topic == "/v1.0/im/bot/messages/get":
            if data_str is None:
                raise DingTalkError("CALLBACK /im/bot/messages/get frame missing data field")
            inbound = parse_bot_message_callback(data_str)
            return ack, inbound
        # 其他 CALLBACK（card action 等）：仅 ACK，不转发（后续可扩展）
        return ack, None

    if frame_type == "EVENT":
        return build_ack(message_id), None

    # 未知帧类型：不 ACK（可能是未来新协议）
    return None, None


# ---------------------------------------------------------------------------
# Token cache（内存，单进程）
# ---------------------------------------------------------------------------


@dataclass
class _TokenCache:
    token: str
    acquired_at: float = field(default_factory=time.monotonic)
    expires_in_secs: int = 7200

    def is_valid(self) -> bool:
        elapsed = time.monotonic() - self.acquired_at
        return elapsed < (self.expires_in_secs - TOKEN_REFRESH_MARGIN_SECS)


# ---------------------------------------------------------------------------
# DingTalkAdapter
# ---------------------------------------------------------------------------

OnInboundT = Callable[[InboundMessage], Coroutine[Any, Any, None]]


class DingTalkAdapter:
    """钉钉渠道 adapter（WS Stream 出站连接）。

    实现 ChannelAdapter Protocol（contracts.py）：
      name / verify / parse_inbound / send / edit

    额外生命周期方法：
      await start(on_inbound)  — 启动 WS 循环，每条私聊消息调用 on_inbound
      await stop()             — 优雅停止

    凭据通过构造函数注入，与「平台统一 bot」或「BYO 每用户 bot」两种归属都兼容。
    """

    name = "dingtalk"

    def __init__(self, client_id: str, client_secret: str) -> None:
        if not client_id:
            raise DingTalkError("DingTalkAdapter requires client_id")
        if not client_secret:
            raise DingTalkError("DingTalkAdapter requires client_secret")
        self._client_id = client_id
        self._client_secret = client_secret
        self._token_cache: Optional[_TokenCache] = None
        self._on_inbound: Optional[OnInboundT] = None
        self._stop_event: asyncio.Event = asyncio.Event()
        self._ws_task: Optional[asyncio.Task[None]] = None

    # ------------------------------------------------------------------
    # ChannelAdapter Protocol: verify
    # WS Stream 模式无 HTTP 入站 webhook，无需验签；始终返回 True。
    # ------------------------------------------------------------------

    def verify(self, headers: dict[str, str], body: bytes) -> bool:  # noqa: ARG002
        return True

    # ------------------------------------------------------------------
    # ChannelAdapter Protocol: parse_inbound
    # 直接解析 CALLBACK data JSON body（主要用于单测 / 直接调用路径）。
    # ------------------------------------------------------------------

    def parse_inbound(self, headers: dict[str, str], body: bytes) -> Optional[InboundMessage]:  # noqa: ARG002
        """解析 CALLBACK data JSON（body = UTF-8 编码的 data 字段内容）。"""
        try:
            data_str = body.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise DingTalkError(f"parse_inbound body decode failed: {exc}") from exc
        return parse_bot_message_callback(data_str)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self, on_inbound: OnInboundT) -> None:
        """启动 WS Stream 后台循环。

        Args:
            on_inbound: 收到私聊文本消息时的异步回调。
        """
        self._on_inbound = on_inbound
        self._stop_event.clear()
        self._ws_task = asyncio.create_task(self._ws_loop(), name="dingtalk-ws-loop")

    async def stop(self) -> None:
        """停止 WS Stream 循环，等待后台任务退出（最多 5 秒）。"""
        self._stop_event.set()
        if self._ws_task is not None:
            try:
                await asyncio.wait_for(self._ws_task, timeout=5.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._ws_task.cancel()
            self._ws_task = None

    # ------------------------------------------------------------------
    # ChannelAdapter Protocol: send
    # AI Card 三段：create → deliver → streaming write(isFinalize=True)
    # ------------------------------------------------------------------

    async def send(self, chat_id: str, msg: OutboundMessage) -> str:
        """创建并投递 AI Card，写入终态内容。返回 outTrackId（即 message_id）。

        流程：
          POST /v1.0/card/instances          # 创建卡片实例
          POST /v1.0/card/instances/deliver  # 投递到会话
          PUT  /v1.0/card/streaming          # 写终态内容（isFinalize=msg.is_final）

        Raises:
            DingTalkError: 任一 HTTP 请求失败或平台返回 success=false。
        """
        import httpx  # 运行时依赖，单测不走此路径

        out_track_id = _generate_out_track_id()
        token = await self._get_token()

        headers = {
            "x-acs-dingtalk-access-token": token,
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            # 1. 创建 AI Card 实例
            create_body = build_create_card_body(out_track_id)
            resp = await client.post(
                f"{DINGTALK_API_BASE}/v1.0/card/instances",
                headers=headers,
                content=json.dumps(create_body),
            )
            _raise_for_status(resp, "create card")
            create_data: dict[str, Any] = resp.json()
            if not create_data.get("success"):
                raise DingTalkError(f"DingTalk create card returned success=false: {create_data}")

            # 2. 投递卡片到会话
            deliver_body = build_deliver_card_body(out_track_id, chat_id, self._client_id)
            resp = await client.post(
                f"{DINGTALK_API_BASE}/v1.0/card/instances/deliver",
                headers=headers,
                content=json.dumps(deliver_body),
            )
            _raise_for_status(resp, "deliver card")

            # 3. 写内容（终态）
            streaming_body = build_card_streaming_body(
                out_track_id, msg.text, is_finalize=msg.is_final
            )
            resp = await client.put(
                f"{DINGTALK_API_BASE}/v1.0/card/streaming",
                headers=headers,
                content=json.dumps(streaming_body),
            )
            _raise_for_status(resp, "streaming write")

        return out_track_id

    # ------------------------------------------------------------------
    # ChannelAdapter Protocol: edit
    # streaming write 更新已投递的 AI Card 内容
    # ------------------------------------------------------------------

    async def edit(self, chat_id: str, message_id: str, msg: OutboundMessage) -> None:  # noqa: ARG002
        """用 PUT /v1.0/card/streaming 更新已发 AI Card 的内容。

        message_id 即 send() 返回的 outTrackId。
        is_final=True 时 isFinalize=True，锁定卡片终态。

        Raises:
            DingTalkError: HTTP 请求失败。
        """
        import httpx  # 运行时依赖

        token = await self._get_token()
        streaming_body = build_card_streaming_body(
            message_id, msg.text, is_finalize=msg.is_final
        )

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.put(
                f"{DINGTALK_API_BASE}/v1.0/card/streaming",
                headers={
                    "x-acs-dingtalk-access-token": token,
                    "Content-Type": "application/json",
                },
                content=json.dumps(streaming_body),
            )
            _raise_for_status(resp, "edit streaming write")

    # ------------------------------------------------------------------
    # Token management
    # ------------------------------------------------------------------

    async def _get_token(self) -> str:
        if self._token_cache is not None and self._token_cache.is_valid():
            return self._token_cache.token
        return await self._refresh_token()

    async def _refresh_token(self) -> str:
        """POST /v1.0/oauth2/accessToken → access_token。

        Raises:
            DingTalkError: 网络失败或平台返回错误码。
        """
        import httpx  # 运行时依赖

        url = f"{DINGTALK_API_BASE}/v1.0/oauth2/accessToken"
        body = {"appKey": self._client_id, "appSecret": self._client_secret}

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                resp = await client.post(url, json=body)
            except httpx.RequestError as exc:
                raise DingTalkError(f"DingTalk token request failed: {exc}") from exc

        _raise_for_status(resp, "accessToken")
        data: dict[str, Any] = resp.json()

        errcode = data.get("errcode")
        if errcode is not None and errcode != 0:
            raise DingTalkError(
                f"DingTalk token error (code={errcode}): {data.get('errmsg', 'unknown')}"
            )

        token: Optional[str] = data.get("accessToken")
        if not token:
            raise DingTalkError("DingTalk token response missing accessToken field")

        expires_in = int(data.get("expireIn", 7200))
        self._token_cache = _TokenCache(token=token, expires_in_secs=expires_in)
        return token

    # ------------------------------------------------------------------
    # WS Stream loop
    # ------------------------------------------------------------------

    async def _ws_loop(self) -> None:
        """WS Stream 主循环，断线指数退避重连（上限 MAX_RECONNECT_ATTEMPTS）。

        Raises:
            DingTalkError: 超过最大重连次数。
        """
        consecutive_errors = 0

        while not self._stop_event.is_set():
            # 1. 注册 Stream 连接，获取 endpoint + ticket
            try:
                endpoint, ticket = await self._register_stream()
                consecutive_errors = 0
            except Exception as exc:
                consecutive_errors += 1
                if consecutive_errors >= MAX_RECONNECT_ATTEMPTS:
                    raise DingTalkError(
                        f"DingTalk stream registration failed {consecutive_errors} times, giving up"
                    ) from exc
                delay = min(2 ** consecutive_errors, MAX_RECONNECT_DELAY_SECS)
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=float(delay))
                except asyncio.TimeoutError:
                    pass
                continue

            # 2. 连 WS 并监听帧
            ws_url = f"{endpoint}?ticket={ticket}"
            try:
                await self._ws_connect(ws_url)
                if self._stop_event.is_set():
                    break  # 正常 stop 信号退出
            except Exception as exc:
                consecutive_errors += 1
                if consecutive_errors >= MAX_RECONNECT_ATTEMPTS:
                    raise DingTalkError(
                        f"DingTalk WS failed {consecutive_errors} times, giving up"
                    ) from exc
                delay = min(2 ** consecutive_errors, MAX_RECONNECT_DELAY_SECS)
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=float(delay))
                except asyncio.TimeoutError:
                    pass

    async def _register_stream(self) -> tuple[str, str]:
        """POST /v1.0/gateway/connections/open → (endpoint, ticket)。

        注意：此端点用 clientId/clientSecret in body，不用 access token。
        必须带 Accept: application/json，否则可能返回 XML。

        Raises:
            DingTalkError: HTTP 失败或响应缺少 endpoint/ticket。
        """
        import httpx  # 运行时依赖

        url = f"{DINGTALK_API_BASE}/v1.0/gateway/connections/open"
        body = {
            "clientId": self._client_id,
            "clientSecret": self._client_secret,
            "subscriptions": [
                {"type": "EVENT", "topic": "*"},
                {"type": "CALLBACK", "topic": "/v1.0/im/bot/messages/get"},
                {"type": "CALLBACK", "topic": "/v1.0/card/instances/callback"},
            ],
            "ua": "datamind-channel/1.0",
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                resp = await client.post(
                    url,
                    headers={
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                    },
                    content=json.dumps(body),
                )
            except httpx.RequestError as exc:
                raise DingTalkError(f"DingTalk stream registration request failed: {exc}") from exc

        _raise_for_status(resp, "register stream")
        data: dict[str, Any] = resp.json()

        endpoint: Optional[str] = data.get("endpoint")
        ticket: Optional[str] = data.get("ticket")
        if not endpoint or not ticket:
            raise DingTalkError(
                f"DingTalk stream registration missing endpoint/ticket: {data}"
            )
        return endpoint, ticket

    async def _ws_connect(self, ws_url: str) -> None:
        """连接 WS 并持续接收帧，直到断开或收到 stop 信号。

        每收到一帧：
        - 调用 parse_stream_frame 解析
        - 若有 ACK 则发回
        - 若有 InboundMessage 则调度 on_inbound 协程

        Raises:
            DingTalkError: parse_stream_frame 失败（框架级错误）。
            websockets 异常: 连接建立失败（由 _ws_loop 捕获重连）。
        """
        import websockets  # 运行时依赖

        async with websockets.connect(ws_url) as ws:
            while not self._stop_event.is_set():
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=30.0)
                except asyncio.TimeoutError:
                    # 30s 无帧，继续等（ping 由平台发，不需要客户端主动 ping）
                    continue
                except Exception:
                    # 连接断开类异常，退出让 _ws_loop 重连
                    break

                if not isinstance(raw, str):
                    continue  # 忽略 binary 帧

                try:
                    ack, inbound = parse_stream_frame(raw)
                except DingTalkError:
                    # 单帧解析失败不中断 WS 连接（协议健壮性）
                    # 真实系统应在此记录 log
                    continue

                if ack is not None:
                    try:
                        await ws.send(json.dumps(ack))
                    except Exception:
                        break  # 发 ACK 失败 → 连接已坏，退出重连

                if inbound is not None and self._on_inbound is not None:
                    asyncio.create_task(self._on_inbound(inbound))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _raise_for_status(resp: Any, operation: str) -> None:
    """对 httpx.Response 检查状态码，失败 raise DingTalkError。"""
    if resp.status_code >= 400:
        try:
            body_preview = resp.text[:200]
        except Exception:
            body_preview = "<unreadable>"
        raise DingTalkError(
            f"DingTalk {operation} HTTP {resp.status_code}: {body_preview}"
        )
