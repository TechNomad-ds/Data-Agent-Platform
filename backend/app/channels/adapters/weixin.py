"""微信 iLink Bot 适配器（官方 iLink 协议，HTTP 长轮询）。

协议来源：docs/channel-integration-design.md §2 微信 + Rust 参考实现
  其源码

BYO 凭据：bot_token + account_id + base_url，扫码登录（login_stream()）后获得，
由调用方持久化并在构造 WeixinAdapter 时注入。

协议要点：
  - 登录：GET get_bot_qrcode?bot_type=3 → 2s 轮询 get_qrcode_status
  - 长轮询：POST getupdates，游标 get_updates_buf，服务端 hold 40s
  - 发消息：POST sendmessage，必须携带 context_token（24h 窗口）
  - 不支持编辑消息：edit() 内部降级为 send()
  - 认证头：AuthorizationType + Authorization:Bearer + X-WECHAT-UIN

本模块的纯逻辑函数（parse_*/build_*/extract_*）可在不 import httpx 的环境下隔离测试。
真实 HTTP 调用仅在 WeixinAdapter 的 start/send/login_stream 等方法里懒加载 httpx。
_http_client 构造参数用于依赖注入（单测传入 fake client，生产传 None 延迟创建）。
"""
from __future__ import annotations

import asyncio
import base64
import os
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any, AsyncGenerator, Callable, Optional

from app.channels.contracts import InboundMessage, OutboundMessage

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LOGIN_BASE_URL: str = "https://ilinkai.weixin.qq.com"
QR_POLL_INTERVAL: float = 2.0        # 扫码状态轮询间隔（秒）
QR_LOGIN_TIMEOUT: float = 300.0      # 二维码有效期上限（秒）
POLL_TIMEOUT: int = 40               # getupdates 服务端 hold 时长（秒）
_POLL_CLIENT_TIMEOUT: int = 55       # 客户端硬超时，必须 > POLL_TIMEOUT
API_TIMEOUT: int = 10                # sendmessage 等短调用超时（秒）
MAX_RETRIES: int = 3                 # 连续失败 N 次后进入 backoff
RETRY_DELAY: float = 2.0             # 普通重试等待（秒）
BACKOFF_DELAY: float = 30.0          # backoff 等待（秒）

ITEM_TYPE_TEXT: int = 1
ITEM_TYPE_VOICE: int = 3


# ---------------------------------------------------------------------------
# 登录事件（login_stream async generator 的 yield 单元）
# ---------------------------------------------------------------------------

class LoginEventKind(str, Enum):
    QR = "qr"
    SCANNED = "scanned"
    DONE = "done"
    ERROR = "error"


@dataclass
class LoginEvent:
    """SSE 事件载体，供前端渲染扫码登录状态机。

    字段按 kind 按需填写；SSE 路由层调用 to_sse_data() 序列化为 JSON。
    """

    kind: LoginEventKind
    # QR
    qr_img_content: Optional[str] = None  # 二维码图片 URL / base64，前端渲染
    qr_ticket: Optional[str] = None       # iLink ticket（内部用于轮询，不发前端）
    # DONE
    bot_token: Optional[str] = None
    account_id: Optional[str] = None
    base_url: Optional[str] = None
    # ERROR
    error: Optional[str] = None

    def to_sse_data(self) -> dict[str, Any]:
        """序列化为 SSE JSON payload（camelCase，与 Rust SseXxxEvent 字段一致）。"""
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
        # ERROR
        return {"message": self.error or ""}


# ---------------------------------------------------------------------------
# 纯逻辑函数（无 I/O，可在 stdlib-only 环境隔离测试）
# ---------------------------------------------------------------------------

def extract_text(item_list: list[dict[str, Any]]) -> str:
    """从 item_list 提取可读文本。

    type=1(text_item.text) 与 type=3(voice_item.text，ASR 转写) 均提取；
    多项非空部分用 '\\n\\n' 拼接；其他 type 忽略。
    """
    parts: list[str] = []
    for item in item_list:
        t = item.get("type")
        if t == ITEM_TYPE_TEXT:
            raw = (item.get("text_item") or {}).get("text") or ""
        elif t == ITEM_TYPE_VOICE:
            raw = (item.get("voice_item") or {}).get("text") or ""
        else:
            continue
        stripped = raw.strip()
        if stripped:
            parts.append(stripped)
    return "\n\n".join(parts)


def parse_raw_message(raw: dict[str, Any]) -> Optional[InboundMessage]:
    """单条 WeixinRawMessage dict → InboundMessage。

    from_user_id 缺失或无可读文本时返回 None（跳过，不 raise）。
    """
    from_user_id = raw.get("from_user_id") or ""
    if not from_user_id:
        return None
    text = extract_text(raw.get("item_list") or [])
    if not text:
        return None
    return InboundMessage(
        channel="weixin",
        platform_user_id=from_user_id,
        chat_id=from_user_id,   # iLink 私聊：chat_id == from_user_id
        text=text,
        raw=raw,
    )


def parse_getupdates_response(
    data: dict[str, Any],
) -> tuple[list[InboundMessage], str, dict[str, str]]:
    """解析 POST /ilink/bot/getupdates 响应。

    返回 (inbound_messages, new_buf, context_token_updates)。
    ret != 0 或 errcode != 0 时 raise RuntimeError（禁止 fallback）。
    context_token_updates: from_user_id → context_token（调用方写入 _context_tokens）。
    """
    ret = data.get("ret")
    errcode = data.get("errcode")
    if (ret is not None and ret != 0) or (errcode is not None and errcode != 0):
        errmsg = data.get("errmsg", "")
        raise RuntimeError(
            f"getupdates error: ret={ret} errcode={errcode} errmsg={errmsg!r}"
        )

    new_buf: str = data.get("get_updates_buf") or ""
    messages: list[InboundMessage] = []
    ctx_updates: dict[str, str] = {}

    for raw in data.get("msgs") or []:
        from_user_id = raw.get("from_user_id") or ""
        ctx = raw.get("context_token") or ""
        if from_user_id and ctx:
            ctx_updates[from_user_id] = ctx
        msg = parse_raw_message(raw)
        if msg is not None:
            messages.append(msg)

    return messages, new_buf, ctx_updates


def build_sendmessage_body(
    to_user_id: str,
    text: str,
    context_token: Optional[str] = None,
    client_id: Optional[str] = None,
) -> dict[str, Any]:
    """构造 POST /ilink/bot/sendmessage 请求体（纯逻辑，不发 HTTP）。

    context_token 为空字符串或 None 时均不写入请求体（iLink 要求必须有才带）。
    """
    if client_id is None:
        client_id = str(uuid.uuid4())
    msg: dict[str, Any] = {
        "to_user_id": to_user_id,
        "client_id": client_id,
        "message_type": 2,
        "message_state": 2,
        "item_list": [{"type": ITEM_TYPE_TEXT, "text_item": {"text": text}}],
    }
    if context_token:
        msg["context_token"] = context_token
    return {"msg": msg, "base_info": {}}


def parse_login_qr_response(data: dict[str, Any]) -> tuple[str, str]:
    """解析 get_bot_qrcode 响应 → (ticket, qrcode_img_content)。

    支持直连格式 {qrcode, qrcode_img_content} 和包装格式 {code, data: {...}}。
    字段缺失 raise RuntimeError（调用方在 login_stream 里捕获并 yield ERROR）。
    """
    if "data" in data:
        data = data.get("data") or {}
    ticket: str = data.get("qrcode") or ""
    img: str = data.get("qrcode_img_content") or ""
    if not ticket:
        raise RuntimeError("get_bot_qrcode: 响应缺少 qrcode ticket")
    if not img:
        raise RuntimeError("get_bot_qrcode: 响应缺少 qrcode_img_content")
    return ticket, img


def parse_login_status_response(data: dict[str, Any]) -> dict[str, Optional[str]]:
    """解析 get_qrcode_status 响应。

    支持直连/包装两种格式。
    返回 {status, bot_token, ilink_bot_id, baseurl}，缺失字段值为 None。
    注意：iLink API 返回 'scaned'（少一个 n）——保留原始拼写。
    """
    if "data" in data:
        data = data.get("data") or {}
    return {
        "status": data.get("status"),
        "bot_token": data.get("bot_token"),
        "ilink_bot_id": data.get("ilink_bot_id"),
        "baseurl": data.get("baseurl"),
    }


def make_wechat_uin() -> str:
    """生成实例级固定 X-WECHAT-UIN header 值（4 随机字节 → base64，8 字符）。"""
    return base64.b64encode(os.urandom(4)).decode()


# ---------------------------------------------------------------------------
# WeixinAdapter（ChannelAdapter Protocol 实现）
# ---------------------------------------------------------------------------

class WeixinAdapter:
    """微信 iLink Bot 适配器。

    生命周期::

        # 扫码获凭据（SSE 路由层消费）
        async for event in WeixinAdapter.create_login_stream():
            ...  # event.kind in (QR, SCANNED, DONE, ERROR)
            if event.kind == LoginEventKind.DONE:
                # 持久化 event.bot_token / account_id / base_url 到 DB

        # 凭据就绪后创建实例，启动长轮询
        adapter = WeixinAdapter(bot_token=..., account_id=..., base_url=...)
        await adapter.start(on_message=agent_bridge.dispatch)
        ...
        await adapter.stop()

    _http_client 参数仅用于单测依赖注入；生产传 None（运行时懒建 httpx.AsyncClient）。
    """

    name: str = "weixin"
    supports_edit: bool = False  # iLink 只能发新消息，不能编辑 → 桥接层只发终态一条

    def __init__(
        self,
        bot_token: str,
        account_id: str,
        base_url: str = LOGIN_BASE_URL,
        *,
        _http_client: Any = None,
    ) -> None:
        if not bot_token:
            raise ValueError("WeixinAdapter: bot_token 不能为空")
        if not account_id:
            raise ValueError("WeixinAdapter: account_id 不能为空")

        self._bot_token: str = bot_token
        self._account_id: str = account_id
        self._base_url: str = base_url.rstrip("/")
        self._wechat_uin: str = make_wechat_uin()        # 实例级固定，随机 4 字节 base64
        self._context_tokens: dict[str, str] = {}         # from_user_id → context_token
        self._poll_task: Optional[asyncio.Task[None]] = None
        self._shutdown_event: asyncio.Event = asyncio.Event()
        self._http_client: Any = _http_client             # None = 运行时创建 httpx

    # ------------------------------------------------------------------
    # ChannelAdapter Protocol（iLink 长轮询，无 webhook 入站路径）
    # ------------------------------------------------------------------

    def verify(self, headers: dict[str, str], body: bytes) -> bool:
        """iLink 走出站长轮询，无入站 webhook，始终返回 False。"""
        return False

    def parse_inbound(self, headers: dict[str, str], body: bytes) -> Optional[InboundMessage]:
        """iLink 走出站长轮询，无入站 webhook，始终返回 None。"""
        return None

    async def send(self, chat_id: str, msg: OutboundMessage) -> str:
        """向微信用户发送文本消息，自动携带已缓存的 context_token。

        iLink sendmessage 不返回 message_id，固定返回空串。
        """
        ctx = self._context_tokens.get(chat_id)
        body = build_sendmessage_body(chat_id, msg.text, ctx)
        await self._do_post("ilink/bot/sendmessage", body, timeout=API_TIMEOUT)
        return ""

    async def edit(self, chat_id: str, message_id: str, msg: OutboundMessage) -> None:
        """微信不支持编辑消息；降级为发一条新消息。"""
        await self.send(chat_id, msg)

    # ------------------------------------------------------------------
    # 扫码登录（async generator，由 SSE 路由层通过 async for 消费）
    # ------------------------------------------------------------------

    async def login_stream(
        self,
        *,
        poll_interval: float = QR_POLL_INTERVAL,
        timeout: float = QR_LOGIN_TIMEOUT,
        _client: Any = None,          # 注入 fake client 供单测
    ) -> AsyncGenerator[LoginEvent, None]:
        """扫码登录 async 生成器，依序 yield: QR → [SCANNED] → DONE | ERROR。

        DONE / ERROR 后生成器结束。调用方示例（SSE 路由层）::

            async for event in adapter.login_stream():
                await sse_send(event.kind.value, json.dumps(event.to_sse_data()))
        """
        own_client = _client is None
        if own_client:
            import httpx
            # get_qrcode_status 是长轮询：服务端挂起约 30s 才返回 {"status":"wait"}，
            # 读超时必须 > 30s，否则每次轮询都 ReadTimeout。
            client = httpx.AsyncClient(timeout=httpx.Timeout(40.0, connect=10.0))
        else:
            client = _client

        try:
            # Step 1: 拿二维码
            try:
                resp = await client.get(
                    f"{self._base_url}/ilink/bot/get_bot_qrcode",
                    params={"bot_type": "3"},
                    headers={"iLink-App-ClientVersion": "1"},
                )
                resp.raise_for_status()
                ticket, img_content = parse_login_qr_response(resp.json())
            except Exception as exc:
                yield LoginEvent(kind=LoginEventKind.ERROR, error=f"QR fetch failed: {exc}")
                return

            yield LoginEvent(kind=LoginEventKind.QR, qr_ticket=ticket, qr_img_content=img_content)

            # Step 2: 轮询扫码状态（每 2s，最多 5min）
            loop = asyncio.get_event_loop()
            deadline = loop.time() + timeout
            scanned_sent = False

            while True:
                if loop.time() >= deadline:
                    yield LoginEvent(kind=LoginEventKind.ERROR, error="QR code login timeout")
                    return

                await asyncio.sleep(poll_interval)

                try:
                    resp = await client.get(
                        f"{self._base_url}/ilink/bot/get_qrcode_status",
                        params={"qrcode": ticket},
                        headers={"iLink-App-ClientVersion": "1"},
                    )
                    resp.raise_for_status()
                    st = parse_login_status_response(resp.json())
                except Exception as exc:
                    import httpx
                    err_lower = str(exc).lower()
                    # 长轮询正常超时即继续等。注意 httpx 超时异常 str() 常为空，
                    # 必须按异常类型判断，不能只靠字符串匹配（否则空消息会被误判为真错误）。
                    if (
                        isinstance(exc, httpx.TimeoutException)
                        or "timeout" in err_lower
                        or "timed out" in err_lower
                    ):
                        continue
                    yield LoginEvent(kind=LoginEventKind.ERROR, error=f"Status poll failed: {exc!r}")
                    return

                status = st.get("status") or "wait"

                if status == "scaned" and not scanned_sent:
                    # 注意：iLink API 故意拼 "scaned"（非 "scanned"）
                    scanned_sent = True
                    yield LoginEvent(kind=LoginEventKind.SCANNED)
                elif status == "confirmed":
                    yield LoginEvent(
                        kind=LoginEventKind.DONE,
                        bot_token=st.get("bot_token") or "",
                        account_id=st.get("ilink_bot_id") or "",
                        base_url=st.get("baseurl") or LOGIN_BASE_URL,
                    )
                    return
                elif status == "expired":
                    yield LoginEvent(kind=LoginEventKind.ERROR, error="QR code expired")
                    return
                # wait / scaned (已发送) → 继续轮询

        finally:
            if own_client and hasattr(client, "aclose"):
                await client.aclose()

    # ------------------------------------------------------------------
    # 长轮询生命周期
    # ------------------------------------------------------------------

    async def start(self, on_message: Callable[[InboundMessage], Any]) -> None:
        """启动长轮询 asyncio Task。

        on_message 支持普通函数或协程函数；调用方负责把 InboundMessage 路由到 AgentBridge。
        """
        self._shutdown_event.clear()
        self._poll_task = asyncio.create_task(
            self._poll_loop(on_message),
            name="weixin_poll_loop",
        )

    async def stop(self) -> None:
        """优雅停止长轮询 Task（最多等 5s，超时后 cancel）。"""
        self._shutdown_event.set()
        if self._poll_task is not None:
            try:
                await asyncio.wait_for(self._poll_task, timeout=5.0)
            except (asyncio.TimeoutError, asyncio.CancelledError, Exception):
                self._poll_task.cancel()
            self._poll_task = None

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _auth_headers(self) -> dict[str, str]:
        """构造 iLink Bot 认证 headers（实例级固定 X-WECHAT-UIN）。"""
        return {
            "Content-Type": "application/json",
            "AuthorizationType": "ilink_bot_token",
            "Authorization": f"Bearer {self._bot_token}",
            "X-WECHAT-UIN": self._wechat_uin,
        }

    async def _do_post(
        self, path: str, body: dict[str, Any], timeout: int = API_TIMEOUT
    ) -> dict[str, Any]:
        """HTTP POST（注入的 _http_client 优先；None 时懒建 httpx.AsyncClient）。"""
        url = f"{self._base_url}/{path}"
        if self._http_client is not None:
            resp = await self._http_client.post(
                url, json=body, headers=self._auth_headers(), timeout=timeout
            )
            resp.raise_for_status()
            return resp.json()
        import httpx
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                url, json=body, headers=self._auth_headers(), timeout=timeout
            )
            resp.raise_for_status()
            return resp.json()

    async def _poll_loop(self, on_message: Callable[[InboundMessage], Any]) -> None:
        """长轮询主循环（在 asyncio Task 里跑，直到 _shutdown_event 被 set）。

        - 成功：更新游标 buf + context_tokens，逐条回调 on_message
        - HTTP 异常 / API error：重试 MAX_RETRIES 次后 backoff
        - asyncio.TimeoutError：iLink 40s hold 超时属正常，直接 continue
        """
        buf: str = ""
        consecutive_failures: int = 0

        client = self._http_client
        own_client = client is None
        if own_client:
            import httpx
            client = httpx.AsyncClient(timeout=httpx.Timeout(_POLL_CLIENT_TIMEOUT))

        try:
            while not self._shutdown_event.is_set():
                try:
                    body = {"get_updates_buf": buf, "base_info": {}}
                    resp = await client.post(
                        f"{self._base_url}/ilink/bot/getupdates",
                        json=body,
                        headers=self._auth_headers(),
                        timeout=_POLL_CLIENT_TIMEOUT,
                    )
                    resp.raise_for_status()
                    data: dict[str, Any] = resp.json()
                except asyncio.TimeoutError:
                    continue  # 正常 hold 超时，继续
                except Exception:
                    consecutive_failures += 1
                    await self._wait_or_shutdown(consecutive_failures)
                    if consecutive_failures >= MAX_RETRIES:
                        consecutive_failures = 0
                    continue

                try:
                    messages, new_buf, ctx_updates = parse_getupdates_response(data)
                except RuntimeError:
                    consecutive_failures += 1
                    await self._wait_or_shutdown(consecutive_failures)
                    if consecutive_failures >= MAX_RETRIES:
                        consecutive_failures = 0
                    continue

                consecutive_failures = 0
                if new_buf:
                    buf = new_buf
                self._context_tokens.update(ctx_updates)

                for msg in messages:
                    try:
                        result = on_message(msg)
                        if asyncio.iscoroutine(result):
                            await result
                    except Exception:
                        pass  # 单条消息处理异常不中断轮询

        finally:
            if own_client and hasattr(client, "aclose"):
                await client.aclose()

    async def _wait_or_shutdown(self, consecutive_failures: int) -> None:
        """失败后等待重试/backoff 时长，shutdown_event 可提前唤醒。"""
        delay = BACKOFF_DELAY if consecutive_failures >= MAX_RETRIES else RETRY_DELAY
        try:
            await asyncio.wait_for(self._shutdown_event.wait(), timeout=delay)
        except asyncio.TimeoutError:
            pass
