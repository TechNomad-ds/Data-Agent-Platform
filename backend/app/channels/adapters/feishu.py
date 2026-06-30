"""飞书 Lark 渠道 adapter — WSS 出站长连接 + 分片 protobuf 帧处理。

纯 Python 实现 PbFrame / PbHeader 编解码（不依赖 protobuf 库）。
HTTP 调用用 httpx.AsyncClient；WSS 连接用 websockets 库（ALPN 强制 http/1.1）。
详见 docs/channel-integration-design.md §2。

REQUIRES_CREDENTIALS（联调项）：
  - _get_token()      → POST /auth/v3/tenant_access_token/internal 需真实 app_id/app_secret
  - _get_ws_endpoint() → POST /callback/ws/endpoint 同上
  - send()            → POST /im/v1/messages 需有效 tenant_access_token + 真实 chat_id
  - edit()            → PATCH /im/v1/messages/{id} 同上
  - test_connection() → GET /bot/v3/info 验证凭据有效性
  - start()           → 建立 WSS 长连接（wss://open.feishu.cn）需真实 URL
"""
from __future__ import annotations

import asyncio
import json
import logging
import ssl
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

import httpx
import websockets

from app.channels.contracts import InboundMessage, OutboundMessage

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

FEISHU_OPEN_API = "https://open.feishu.cn/open-apis"
FEISHU_BASE = "https://open.feishu.cn"

TOKEN_REFRESH_MARGIN = 5 * 60   # 提前 5min 刷 token（秒）
EVENT_DEDUP_TTL = 10 * 60       # event_id 去重 TTL（秒）
FRAG_CLEANUP_TTL = 5 * 60       # 等待分片超时清理（秒）
MAX_RECONNECT_ATTEMPTS = 10
MAX_BACKOFF_SECS = 30

METHOD_CONTROL = 0
METHOD_DATA = 1

_WIRE_VARINT = 0
_WIRE_LEN = 2

# ---------------------------------------------------------------------------
# 纯 Python protobuf — PbFrame / PbHeader
# ---------------------------------------------------------------------------
#
# 字段对应关系（参考 同类引擎 其源码）：
#   PbFrame: seq_id=1(u64) log_id=2(u64) service=3(i32) method=4(i32)
#            headers=5(repeated PbHeader) payload_encoding=6(str) payload_type=7(str)
#            payload=8(bytes) log_id_new=9(str)
#   PbHeader: key=1(str) value=2(str)


@dataclass
class PbHeader:
    key: str = ""
    value: str = ""


@dataclass
class PbFrame:
    seq_id: int = 0
    log_id: int = 0
    service: int = 0
    method: int = 0
    headers: list[PbHeader] = field(default_factory=list)
    payload_encoding: str = ""
    payload_type: str = ""
    payload: bytes = b""
    log_id_new: str = ""


# -------- varint 编解码 --------

def _encode_varint(n: int) -> bytes:
    """把非负整数编码为 protobuf varint（LEB128）。有符号值用 unsigned 64-bit 截断处理。"""
    n = n & 0xFFFF_FFFF_FFFF_FFFF
    result = bytearray()
    while True:
        byte = n & 0x7F
        n >>= 7
        if n:
            byte |= 0x80
        result.append(byte)
        if not n:
            break
    return bytes(result)


def _decode_varint(data: bytes, pos: int) -> tuple[int, int]:
    """从 data[pos] 开始解码 varint，返回 (value, new_pos)。"""
    result = 0
    shift = 0
    while pos < len(data):
        byte = data[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        shift += 7
        if not (byte & 0x80):
            return result, pos
    raise ValueError(f"截断的 varint（pos={pos} len={len(data)}）")


# -------- 字段编码工具 --------

def _field_tag(field_num: int, wire_type: int) -> bytes:
    return _encode_varint((field_num << 3) | wire_type)


def _len_prefix(data: bytes) -> bytes:
    return _encode_varint(len(data)) + data


def _str_field(num: int, s: str) -> bytes:
    b = s.encode("utf-8")
    return _field_tag(num, _WIRE_LEN) + _len_prefix(b)


def _bytes_field(num: int, b: bytes) -> bytes:
    return _field_tag(num, _WIRE_LEN) + _len_prefix(b)


def _varint_field(num: int, v: int) -> bytes:
    return _field_tag(num, _WIRE_VARINT) + _encode_varint(v)


# -------- PbHeader 编解码 --------

def _encode_header(h: PbHeader) -> bytes:
    buf = bytearray()
    if h.key:
        buf.extend(_str_field(1, h.key))
    if h.value:
        buf.extend(_str_field(2, h.value))
    return bytes(buf)


def _decode_header(data: bytes) -> PbHeader:
    h = PbHeader()
    pos = 0
    while pos < len(data):
        tag_wire, pos = _decode_varint(data, pos)
        field_num = tag_wire >> 3
        wire_type = tag_wire & 0x7
        if wire_type == _WIRE_LEN:
            length, pos = _decode_varint(data, pos)
            fb = data[pos: pos + length]
            pos += length
            if field_num == 1:
                h.key = fb.decode("utf-8")
            elif field_num == 2:
                h.value = fb.decode("utf-8")
        elif wire_type == _WIRE_VARINT:
            _, pos = _decode_varint(data, pos)
        else:
            raise ValueError(f"PbHeader 不支持的 wire type {wire_type}")
    return h


# -------- PbFrame 编解码（公开接口）--------

def encode_frame(frame: PbFrame) -> bytes:
    """把 PbFrame 编码为 protobuf wire format 字节序列。"""
    buf = bytearray()
    if frame.seq_id:
        buf.extend(_varint_field(1, frame.seq_id))
    if frame.log_id:
        buf.extend(_varint_field(2, frame.log_id))
    if frame.service:
        buf.extend(_varint_field(3, frame.service))
    if frame.method:
        buf.extend(_varint_field(4, frame.method))
    for h in frame.headers:
        hb = _encode_header(h)
        buf.extend(_field_tag(5, _WIRE_LEN) + _len_prefix(hb))
    if frame.payload_encoding:
        buf.extend(_str_field(6, frame.payload_encoding))
    if frame.payload_type:
        buf.extend(_str_field(7, frame.payload_type))
    if frame.payload:
        buf.extend(_bytes_field(8, frame.payload))
    if frame.log_id_new:
        buf.extend(_str_field(9, frame.log_id_new))
    return bytes(buf)


def decode_frame(data: bytes) -> PbFrame:
    """从字节流解码 PbFrame；畸形输入 raise ValueError。空字节返回全默认 PbFrame。"""
    frame = PbFrame()
    pos = 0
    while pos < len(data):
        tag_wire, pos = _decode_varint(data, pos)
        field_num = tag_wire >> 3
        wire_type = tag_wire & 0x7
        if wire_type == _WIRE_VARINT:
            value, pos = _decode_varint(data, pos)
            if field_num == 1:
                frame.seq_id = value
            elif field_num == 2:
                frame.log_id = value
            elif field_num == 3:
                frame.service = value
            elif field_num == 4:
                frame.method = value
        elif wire_type == _WIRE_LEN:
            length, pos = _decode_varint(data, pos)
            fb = data[pos: pos + length]
            pos += length
            if field_num == 5:
                frame.headers.append(_decode_header(fb))
            elif field_num == 6:
                frame.payload_encoding = fb.decode("utf-8")
            elif field_num == 7:
                frame.payload_type = fb.decode("utf-8")
            elif field_num == 8:
                frame.payload = fb
            elif field_num == 9:
                frame.log_id_new = fb.decode("utf-8")
        else:
            raise ValueError(f"decode_frame: 不支持的 wire type {wire_type}（field {field_num}）")
    return frame


# -------- 工具函数 --------

def get_header(headers: list[PbHeader], key: str) -> Optional[str]:
    """在 headers 列表中按 key 查 value；未找到返回 None。"""
    for h in headers:
        if h.key == key:
            return h.value
    return None


def build_ping_frame(service_id: int) -> PbFrame:
    """构建 ping 控制帧（method=CONTROL，type=ping）。"""
    return PbFrame(
        service=service_id,
        method=METHOD_CONTROL,
        headers=[PbHeader(key="type", value="ping")],
    )


def build_ack_frame(original: PbFrame) -> PbFrame:
    """根据原始帧构造 ACK 帧，保留 type/message_id/trace_id，payload={code:200}。"""
    keep = {"type", "message_id", "trace_id"}
    ack_headers = [
        PbHeader(key=h.key, value=h.value)
        for h in original.headers
        if h.key in keep
    ]
    ack_headers.append(PbHeader(key="biz_rt", value="0"))
    return PbFrame(
        seq_id=original.seq_id,
        log_id=original.log_id,
        service=original.service,
        method=METHOD_DATA,
        headers=ack_headers,
        payload=b'{"code":200}',
        log_id_new=original.log_id_new,
    )


# ---------------------------------------------------------------------------
# 分片重组缓存
# ---------------------------------------------------------------------------

@dataclass
class _FragEntry:
    sum: int
    fragments: list[Optional[bytes]]
    created_at: float = field(default_factory=time.monotonic)


class FragmentCache:
    """按 message_id + seq/sum 重组分片。全部到齐后返回合并 payload，并清除缓存条目。"""

    def __init__(self) -> None:
        self._entries: dict[str, _FragEntry] = {}

    def push(self, message_id: str, sum_: int, seq: int, data: bytes) -> Optional[bytes]:
        entry = self._entries.get(message_id)
        if entry is None:
            entry = _FragEntry(sum=sum_, fragments=[None] * sum_)
            self._entries[message_id] = entry
        if 0 <= seq < entry.sum:
            entry.fragments[seq] = data
        if all(f is not None for f in entry.fragments):
            merged = b"".join(f for f in entry.fragments)  # type: ignore[misc]
            del self._entries[message_id]
            return merged
        return None

    def cleanup(self, ttl: float) -> None:
        """清理超过 ttl 秒未完成的分片条目。"""
        now = time.monotonic()
        stale = [k for k, e in self._entries.items() if now - e.created_at > ttl]
        for k in stale:
            del self._entries[k]


# ---------------------------------------------------------------------------
# Interactive card builder
# ---------------------------------------------------------------------------

def build_interactive_card(text: str) -> str:
    """构建飞书 interactive card JSON 字符串（单 markdown element）。
    返回值作为 msg_type=interactive 消息的 content 字段。
    """
    card: dict[str, Any] = {
        "elements": [{"tag": "markdown", "content": text}]
    }
    return json.dumps(card, ensure_ascii=False)


# ---------------------------------------------------------------------------
# FeishuAdapter
# ---------------------------------------------------------------------------

_OnMessage = Callable[[InboundMessage], Awaitable[None]]


class FeishuAdapter:
    """飞书 Lark 渠道适配器（WSS 出站长连接模式）。

    ChannelAdapter Protocol 实现：
      verify()       — WS 模式不用 webhook 回调，永远返回 True（留桩）
      parse_inbound() — WS 模式不走 HTTP 回调，永远返回 None（留桩）
      send()         — POST /im/v1/messages 发 interactive card，返回 message_id
      edit()         — PATCH /im/v1/messages/{id} 更新已发消息

    额外方法：
      start(on_message) — 在后台启动 WSS 长连接 loop，每条消息回调 on_message
      stop()            — 关闭连接并等待 loop 结束
      test_connection() — GET /bot/v3/info 校验凭据（需真实 app_id/app_secret）
    """

    name = "feishu"
    supports_edit = True  # 飞书可 patch 卡片 → 支持流式编辑

    def __init__(
        self,
        app_id: str,
        app_secret: str,
        *,
        dedup_ttl: float = EVENT_DEDUP_TTL,
        http_timeout: float = 30.0,
    ) -> None:
        if not app_id:
            raise ValueError("FeishuAdapter: app_id 不能为空")
        if not app_secret:
            raise ValueError("FeishuAdapter: app_secret 不能为空")
        self._app_id = app_id
        self._app_secret = app_secret
        self._dedup_ttl = dedup_ttl

        # Token 缓存
        self._token_lock = asyncio.Lock()
        self._token: Optional[str] = None
        self._token_acquired_at: float = 0.0
        self._token_expires_in: float = 0.0

        # Event 去重：event_id → seen_at (monotonic)
        # 插入即按时间序，过期清理从最旧端弹出（O(k)），避免每条消息全表 O(n) 扫描
        self._dedup: "OrderedDict[str, float]" = OrderedDict()
        self._dedup_lock = asyncio.Lock()

        # 共享 HTTP 客户端
        self._http = httpx.AsyncClient(timeout=http_timeout)

        # WSS 连接管理
        self._ws_task: Optional[asyncio.Task] = None  # type: ignore[type-arg]
        self._stop_event: Optional[asyncio.Event] = None

    # ------------------------------------------------------------------
    # ChannelAdapter Protocol stubs
    # ------------------------------------------------------------------

    def verify(self, headers: dict[str, str], body: bytes) -> bool:
        """WS 模式不验 webhook 签名，留桩始终返回 True。"""
        return True

    def parse_inbound(self, headers: dict[str, str], body: bytes) -> Optional[InboundMessage]:
        """WS 模式通过 WSS 推送事件，不走 HTTP 回调，留桩返回 None。"""
        return None

    # ------------------------------------------------------------------
    # Token 管理
    # ------------------------------------------------------------------

    def _token_still_valid(self) -> bool:
        if not self._token:
            return False
        elapsed = time.monotonic() - self._token_acquired_at
        return elapsed + TOKEN_REFRESH_MARGIN < self._token_expires_in

    async def _get_token(self) -> str:
        async with self._token_lock:
            if self._token_still_valid():
                return self._token  # type: ignore[return-value]
            return await self._refresh_token()

    async def _refresh_token(self) -> str:
        # REQUIRES_CREDENTIALS: 真实 app_id / app_secret
        url = f"{FEISHU_OPEN_API}/auth/v3/tenant_access_token/internal"
        resp = await self._http.post(
            url,
            json={"app_id": self._app_id, "app_secret": self._app_secret},
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("code", -1) != 0:
            raise RuntimeError(
                f"飞书 token 获取失败 code={data.get('code')} msg={data.get('msg')}"
            )
        token = data.get("tenant_access_token")
        if not token:
            raise RuntimeError("飞书 token 响应缺少 tenant_access_token 字段")
        expires_in = float(data.get("expire", 7200))
        self._token = token
        self._token_acquired_at = time.monotonic()
        self._token_expires_in = expires_in
        logger.debug("飞书 tenant_access_token 已刷新 expire_secs=%s", expires_in)
        return token

    # ------------------------------------------------------------------
    # WSS endpoint 获取
    # ------------------------------------------------------------------

    async def _get_ws_endpoint(self) -> str:
        # REQUIRES_CREDENTIALS
        url = f"{FEISHU_BASE}/callback/ws/endpoint"
        resp = await self._http.post(
            url,
            json={"AppID": self._app_id, "AppSecret": self._app_secret},
            headers={"locale": "zh"},
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("code", -1) != 0:
            raise RuntimeError(
                f"飞书 WS endpoint 获取失败 code={data.get('code')} msg={data.get('msg')}"
            )
        ws_url = (data.get("data") or {}).get("URL")
        if not ws_url:
            raise RuntimeError("飞书 WS endpoint 响应缺少 data.URL 字段")
        return ws_url

    # ------------------------------------------------------------------
    # 发/改消息
    # ------------------------------------------------------------------

    async def send(self, chat_id: str, msg: OutboundMessage) -> str:
        """发一条 interactive card 消息，返回 message_id。REQUIRES_CREDENTIALS + 真实 chat_id。"""
        token = await self._get_token()
        card = build_interactive_card(msg.text)
        url = f"{FEISHU_OPEN_API}/im/v1/messages?receive_id_type=chat_id"
        resp = await self._http.post(
            url,
            headers={"Authorization": f"Bearer {token}"},
            json={"receive_id": chat_id, "msg_type": "interactive", "content": card},
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("code", -1) != 0:
            raise RuntimeError(
                f"飞书 send 失败 code={data.get('code')} msg={data.get('msg')}"
            )
        message_id = (data.get("data") or {}).get("message_id")
        if not message_id:
            raise RuntimeError("飞书 send 响应缺少 data.message_id 字段")
        return message_id

    async def edit(self, chat_id: str, message_id: str, msg: OutboundMessage) -> None:
        """更新已发的 interactive card 消息。REQUIRES_CREDENTIALS。"""
        token = await self._get_token()
        card = build_interactive_card(msg.text)
        url = f"{FEISHU_OPEN_API}/im/v1/messages/{message_id}"
        resp = await self._http.patch(
            url,
            headers={"Authorization": f"Bearer {token}"},
            json={"content": card},
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("code", -1) != 0:
            raise RuntimeError(
                f"飞书 edit 失败 code={data.get('code')} msg={data.get('msg')}"
            )

    # ------------------------------------------------------------------
    # 测连（凭据校验）
    # ------------------------------------------------------------------

    async def test_connection(self) -> dict[str, str]:
        """GET /bot/v3/info 校验凭据，返回 {app_name, open_id}。REQUIRES_CREDENTIALS。"""
        token = await self._get_token()
        resp = await self._http.get(
            f"{FEISHU_OPEN_API}/bot/v3/info",
            headers={"Authorization": f"Bearer {token}"},
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("code", -1) != 0:
            raise RuntimeError(
                f"飞书 bot info 失败 code={data.get('code')} msg={data.get('msg')}"
            )
        bot = data.get("bot") or {}
        return {"app_name": bot.get("app_name", ""), "open_id": bot.get("open_id", "")}

    # ------------------------------------------------------------------
    # WSS 连接生命周期
    # ------------------------------------------------------------------

    async def start(self, on_message: _OnMessage) -> None:
        """启动 WSS 长连接后台 task。REQUIRES_CREDENTIALS + 网络。"""
        if self._ws_task and not self._ws_task.done():
            raise RuntimeError("FeishuAdapter: WSS 已在运行，请先 stop()")
        self._stop_event = asyncio.Event()
        self._ws_task = asyncio.create_task(
            self._ws_loop(on_message), name="feishu_ws_loop"
        )

    async def stop(self) -> None:
        """发送停止信号并等待 WSS loop 退出（最多 5s）。"""
        if self._stop_event:
            self._stop_event.set()
        if self._ws_task:
            try:
                await asyncio.wait_for(self._ws_task, timeout=5.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._ws_task.cancel()
                try:
                    await self._ws_task
                except asyncio.CancelledError:
                    pass
        await self._http.aclose()

    # ------------------------------------------------------------------
    # WSS loop（需真实网络）
    # ------------------------------------------------------------------

    async def _ws_loop(self, on_message: _OnMessage) -> None:
        assert self._stop_event is not None
        consecutive_errors = 0

        while not self._stop_event.is_set():
            try:
                ws_url = await self._get_ws_endpoint()
            except Exception as exc:
                consecutive_errors += 1
                logger.warning(
                    "飞书 WS endpoint 获取失败 attempt=%d: %s", consecutive_errors, exc
                )
                if consecutive_errors >= MAX_RECONNECT_ATTEMPTS:
                    logger.error("飞书 WS 达到最大重连次数，退出")
                    break
                await self._backoff(consecutive_errors)
                continue

            service_id = _extract_service_id(ws_url)
            logger.debug("飞书 WS 连接 url=%s service_id=%d", ws_url, service_id)

            try:
                await self._connect_and_listen(ws_url, service_id, on_message)
                # 干净退出（stop_event 已设置）
                break
            except Exception as exc:
                consecutive_errors += 1
                logger.warning(
                    "飞书 WS 断开 attempt=%d: %s", consecutive_errors, exc
                )
                if consecutive_errors >= MAX_RECONNECT_ATTEMPTS:
                    logger.error("飞书 WS 达到最大重连次数，退出")
                    break
                await self._backoff(consecutive_errors)

        logger.info("飞书 WSS loop 已退出")

    async def _backoff(self, attempt: int) -> None:
        """带 stop_event 短路的指数退避。"""
        assert self._stop_event is not None
        delay = float(min(2 ** attempt, MAX_BACKOFF_SECS))
        try:
            await asyncio.wait_for(
                asyncio.shield(self._stop_event.wait()), timeout=delay
            )
        except asyncio.TimeoutError:
            pass

    async def _connect_and_listen(
        self, ws_url: str, service_id: int, on_message: _OnMessage
    ) -> None:
        assert self._stop_event is not None
        # ALPN 强制 http/1.1，与 Rust 端一致（飞书 WSS 不支持 h2）
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.set_alpn_protocols(["http/1.1"])

        async with websockets.connect(ws_url, ssl=ssl_ctx) as ws:
            logger.info("飞书 WebSocket 已连接")
            fragment_cache = FragmentCache()
            ping_interval = 120.0  # 服务端 pong 可能更新此值

            while not self._stop_event.is_set():
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=ping_interval)
                except asyncio.TimeoutError:
                    # 超时未收到数据 → 主动 ping + 清理过期分片
                    ping = build_ping_frame(service_id)
                    await ws.send(encode_frame(ping))
                    logger.debug("飞书 ping 已发送")
                    fragment_cache.cleanup(FRAG_CLEANUP_TTL)
                    continue

                if isinstance(raw, str):
                    continue  # 飞书 WS 只发 binary 帧

                try:
                    frame = decode_frame(bytes(raw))
                except (ValueError, UnicodeDecodeError) as exc:
                    logger.warning("飞书 frame 解码失败: %s", exc)
                    continue

                if frame.method == METHOD_CONTROL:
                    frame_type = get_header(frame.headers, "type") or ""
                    if frame_type == "pong" and frame.payload:
                        try:
                            pong = json.loads(frame.payload)
                            pi = pong.get("PingInterval")
                            if pi:
                                ping_interval = float(pi)
                                logger.debug("飞书 ping_interval 更新为 %s", ping_interval)
                        except Exception:
                            pass
                    # 飞书客户端主动 ping，服务端发 pong。如果服务端发 ping，不需要回复。

                elif frame.method == METHOD_DATA:
                    # 先回 ACK
                    try:
                        await ws.send(encode_frame(build_ack_frame(frame)))
                    except Exception as exc:
                        logger.warning("飞书 ACK 发送失败: %s", exc)

                    # 分片重组
                    message_id = get_header(frame.headers, "message_id") or ""
                    try:
                        sum_ = int(get_header(frame.headers, "sum") or "1")
                        seq = int(get_header(frame.headers, "seq") or "0")
                    except ValueError:
                        sum_, seq = 1, 0

                    merged = fragment_cache.push(message_id, sum_, seq, frame.payload)
                    if merged is None:
                        continue  # 等待更多分片

                    frame_type = get_header(frame.headers, "type") or ""
                    if frame_type != "event":
                        logger.debug("飞书 忽略非 event 帧 type=%s", frame_type)
                        continue

                    try:
                        text = merged.decode("utf-8")
                    except UnicodeDecodeError:
                        logger.warning("飞书 event payload 非 UTF-8，跳过")
                        continue

                    inbound = await self._parse_event(text)
                    if inbound is not None:
                        try:
                            await on_message(inbound)
                        except Exception as exc:
                            logger.exception("飞书 on_message 回调异常: %s", exc)

    # ------------------------------------------------------------------
    # 事件解析
    # ------------------------------------------------------------------

    async def _parse_event(self, text: str) -> Optional[InboundMessage]:
        try:
            envelope = json.loads(text)
        except json.JSONDecodeError as exc:
            logger.warning("飞书 event JSON 解析失败: %s", exc)
            return None

        header = envelope.get("header") or {}
        event_id: Optional[str] = header.get("event_id")
        event_type: str = header.get("event_type", "")

        # event_id TTL 去重
        if event_id:
            async with self._dedup_lock:
                now = time.monotonic()
                # 从最旧端弹出过期 entry（插入即时间序），O(k) 而非每条消息全表 O(n) 扫描
                while self._dedup:
                    oldest_id, oldest_t = next(iter(self._dedup.items()))
                    if now - oldest_t > self._dedup_ttl:
                        self._dedup.popitem(last=False)
                    else:
                        break
                if event_id in self._dedup:
                    logger.debug("飞书 重复事件 event_id=%s，跳过", event_id)
                    return None
                self._dedup[event_id] = now

        if event_type != "im.message.receive_v1":
            logger.debug("飞书 不处理事件类型 %s", event_type)
            return None

        return _parse_message_event(envelope.get("event") or {})


# ---------------------------------------------------------------------------
# im.message.receive_v1 解析（纯函数，便于单测）
# ---------------------------------------------------------------------------

def _parse_message_event(event: dict[str, Any]) -> Optional[InboundMessage]:
    """把 im.message.receive_v1 event 体解析为 InboundMessage。非文本/缺字段返回 None。"""
    try:
        sender = event.get("sender") or {}
        sender_id = sender.get("sender_id") or {}
        open_id: str = sender_id.get("open_id") or ""
        if not open_id:
            logger.warning("飞书消息缺少 sender.sender_id.open_id")
            return None

        message = event.get("message") or {}
        chat_id: str = message.get("chat_id") or ""
        message_type: str = message.get("message_type") or ""
        content_raw: str = message.get("content") or "{}"

        if message_type != "text":
            logger.debug("飞书忽略非文本消息类型 %s", message_type)
            return None

        content = json.loads(content_raw)
        text: str = content.get("text") or ""
        if not text:
            return None

        return InboundMessage(
            channel="feishu",
            platform_user_id=open_id,
            chat_id=chat_id,
            text=text,
            raw=event,
        )
    except Exception as exc:
        logger.warning("飞书 _parse_message_event 异常: %s", exc)
        return None


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def _extract_service_id(ws_url: str) -> int:
    """从 WSS URL query string 提取 service_id 参数。"""
    query = ws_url.split("?", 1)[1] if "?" in ws_url else ""
    for param in query.split("&"):
        if "=" in param:
            k, v = param.split("=", 1)
            if k == "service_id":
                try:
                    return int(v)
                except ValueError:
                    pass
    return 0
