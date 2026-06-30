"""渠道配置路由（配置 / 配对 / 授权 HTTP API）

所有端点要求 JWT 登录（Depends get_current_user）。

模块级注入点（主控在 lifespan 中调用）：
  set_manager(manager)          — 连接管理器（start_one / stop_one）
  set_pairing_service(svc)      — 生产 PairingService（Redis 后端）
  register_pending_pairing(...) — 供 adapter 桥接层在 issue 后登记待配对元数据

不在本模块 include_router 到 main.py，由主控统一做。
详见 docs/channel-integration-design.md。
"""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.deps import get_current_user
from app.models.external_identity import ExternalIdentity
from app.models.user import User
from app.channels import store
from app.channels.pairing import PairingService, RedisPairingStore

router = APIRouter()

# ── 渠道名称映射 ──────────────────────────────────────────────────────────────
# 前端用 'lark'（飞书国际名），内部 / DB 用 'feishu'；其余同名。

_TO_INTERNAL: dict[str, str] = {
    "lark": "feishu",
    "dingtalk": "dingtalk",
    "weixin": "weixin",
}
_TO_FRONTEND: dict[str, str] = {v: k for k, v in _TO_INTERNAL.items()}
KNOWN_CHANNELS: list[str] = list(_TO_INTERNAL)  # ['lark', 'dingtalk', 'weixin']


def _to_internal(channel: str) -> str:
    """前端渠道名 → 内部/DB 渠道名；未知渠道 raise 404。"""
    internal = _TO_INTERNAL.get(channel)
    if internal is None:
        raise HTTPException(status_code=404, detail=f"未知渠道: {channel}")
    return internal


def _to_frontend(channel: str) -> str:
    """内部渠道名 → 前端渠道名；未知直接返回原值。"""
    return _TO_FRONTEND.get(channel, channel)


# ── Manager 注入点 ─────────────────────────────────────────────────────────────
# 连接管理进程接口：start_one(user_id, channel) / stop_one(user_id, channel)
_manager: Any = None


def set_manager(manager: Any) -> None:
    """主控在 lifespan 中注入连接管理器实例。"""
    global _manager
    _manager = manager


# ── PairingService 注入点 ─────────────────────────────────────────────────────
# 用 Redis 共享 store：配对码由 manager 进程出码、web worker 审批，必须同一份。
_pairing_svc: PairingService = PairingService(RedisPairingStore())


def set_pairing_service(svc: PairingService) -> None:
    """主控注入生产 PairingService（Redis 后端，带 TTL）。"""
    global _pairing_svc
    _pairing_svc = svc


# ── 待配对元数据 registry（模块级内存，重启清空）────────────────────────────────
# key = code, value = {user_id, platform(前端名), platform_user_id,
#                      platform_username, expires_at(ISO 字符串)}
_pending_pairings: dict[str, dict[str, Any]] = {}


def register_pending_pairing(
    *,
    code: str,
    user_id: str,
    channel: str,              # 内部名：'feishu' / 'dingtalk' / 'weixin'
    platform_user_id: str,
    platform_username: str = "",
    expires_at: datetime,
) -> None:
    """供 channel adapter 桥接层在 issue 配对码后调用，登记带 user_id 的待配对请求。

    此函数是 router 与 adapter 层的唯一结合点，adapter 桥接层按如下方式使用：
        from app.routers.channels import register_pending_pairing
        code = await pairing_svc.issue(channel, platform_user_id)
        register_pending_pairing(
            code=code, user_id=str(user_id), channel=channel,
            platform_user_id=platform_user_id, platform_username=display_name,
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=600),
        )
    """
    _pending_pairings[code] = {
        "code": code,
        "user_id": user_id,
        "platform": _to_frontend(channel),
        "platform_user_id": platform_user_id,
        "platform_username": platform_username,
        "expires_at": expires_at.isoformat(),
    }


# ── Pydantic 模型（请求 / 响应）──────────────────────────────────────────────


class ChannelStatusOut(BaseModel):
    id: str                              # 前端渠道名 'lark'/'dingtalk'/'weixin'
    enabled: bool
    connected: bool
    has_credentials: bool
    bot_info: Optional[dict[str, Any]] = None


class EnableChannelBody(BaseModel):
    # 提供凭据 → 保存并启用；省略 / 空 → 用已存凭据重新启用（开关快捷重启，不覆盖凭据）
    credentials: Optional[dict[str, str]] = None


class TestChannelBody(BaseModel):
    credentials: dict[str, str]


class TestChannelResponse(BaseModel):
    ok: bool
    bot_username: Optional[str] = None
    error: Optional[str] = None


class PairingCodeBody(BaseModel):
    code: str


class RevokeUserBody(BaseModel):
    id: str


class ChannelSettingsOut(BaseModel):
    default_data_space_id: Optional[str] = None
    default_model: Optional[str] = None


class ChannelSettingsIn(BaseModel):
    default_data_space_id: Optional[str] = None
    default_model: Optional[str] = None


# ── Endpoints ─────────────────────────────────────────────────────────────────
# 静态路径（/pairings, /authorized-users, /weixin/login）在动态路径（/{channel}/…）
# 之前注册，确保 FastAPI 路由优先级正确。


@router.get("", response_model=list[ChannelStatusOut])
async def list_channel_statuses(
    current_user: User = Depends(get_current_user),
) -> list[ChannelStatusOut]:
    """返回当前用户三条渠道的状态（无论是否已配置）。"""
    configs = await store.list_configs(current_user.id)
    config_map = {c.channel: c for c in configs}

    result: list[ChannelStatusOut] = []
    for frontend_name in KNOWN_CHANNELS:
        internal_name = _TO_INTERNAL[frontend_name]
        cfg = config_map.get(internal_name)
        result.append(
            ChannelStatusOut(
                id=frontend_name,
                enabled=cfg.enabled if cfg else False,
                connected=cfg.connected if cfg else False,
                has_credentials=bool(cfg and cfg.credentials_encrypted),
                bot_info=cfg.bot_info if cfg else None,
            )
        )
    return result


@router.get("/pairings")
async def list_pairings(
    current_user: User = Depends(get_current_user),
) -> list[dict[str, Any]]:
    """当前用户名下的待配对请求列表（按 user_id 隔离）。"""
    now = datetime.now(timezone.utc)
    user_id = str(current_user.id)
    return [
        v
        for v in _pending_pairings.values()
        if v["user_id"] == user_id
        and datetime.fromisoformat(v["expires_at"]) > now
    ]


@router.post("/pairings/approve", status_code=200)
async def approve_pairing(
    body: PairingCodeBody,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """批准配对码：把外部身份写入 external_identities，绑定到当前登录用户。"""
    code = body.code.strip()
    if not code:
        raise HTTPException(status_code=422, detail="配对码不能为空")

    # registry 优先（有 user_id 归属校验）
    entry = _pending_pairings.pop(code, None)
    # pairing service 作为次级 store（保证两端消费同步）
    svc_result = await _pairing_svc.approve(code)

    if entry is None and svc_result is None:
        raise HTTPException(status_code=404, detail="配对码不存在或已过期")

    if entry is not None:
        # 校验归属：只有 bot 属于当前用户才能批准
        if entry["user_id"] != str(current_user.id):
            raise HTTPException(status_code=403, detail="无权操作此配对码")
        # 过期双保险（registry 没有 TTL，手动检查）
        if datetime.fromisoformat(entry["expires_at"]) <= datetime.now(timezone.utc):
            raise HTTPException(status_code=404, detail="配对码已过期")
        channel = _TO_INTERNAL.get(entry["platform"], entry["platform"])
        platform_user_id: str = entry["platform_user_id"]
        platform_username: Optional[str] = entry.get("platform_username") or None
    else:
        # fallback：仅 pairing service 有记录（registry 丢失，如重启后）
        assert svc_result is not None
        channel, platform_user_id = svc_result
        platform_username = None

    now = datetime.now(timezone.utc)
    existing = await db.execute(
        select(ExternalIdentity).where(
            ExternalIdentity.channel == channel,
            ExternalIdentity.platform_user_id == platform_user_id,
        )
    )
    ei = existing.scalar_one_or_none()
    if ei is not None:
        # 重新绑定到当前用户（支持换绑）
        ei.user_id = current_user.id
        ei.authorized_at = now
        if platform_username:
            ei.display_name = platform_username
    else:
        ei = ExternalIdentity(
            user_id=current_user.id,
            channel=channel,
            platform_user_id=platform_user_id,
            display_name=platform_username,
            authorized_at=now,
        )
        db.add(ei)
    await db.commit()
    return {"ok": True}


@router.post("/pairings/reject", status_code=200)
async def reject_pairing(
    body: PairingCodeBody,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """拒绝配对码：从 registry 和 pairing service 中消费掉该码。"""
    code = body.code.strip()
    if not code:
        raise HTTPException(status_code=422, detail="配对码不能为空")

    _pending_pairings.pop(code, None)
    await _pairing_svc.approve(code)  # 一次性消费，避免他人批准
    return {"ok": True}


@router.get("/authorized-users")
async def list_authorized_users(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """当前用户已绑定的外部平台身份列表。"""
    result = await db.execute(
        select(ExternalIdentity)
        .where(ExternalIdentity.user_id == current_user.id)
        .order_by(ExternalIdentity.authorized_at.desc())
    )
    items = result.scalars().all()
    return [
        {
            "id": str(item.id),
            "platform": _to_frontend(item.channel),
            "platform_user_id": item.platform_user_id,
            "platform_username": item.display_name,
            "authorized_at": (
                item.authorized_at.isoformat() if item.authorized_at else None
            ),
        }
        for item in items
    ]


@router.post("/authorized-users/revoke", status_code=200)
async def revoke_authorized_user(
    body: RevokeUserBody,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """撤销外部身份授权（只能撤销自己名下的）。"""
    try:
        target_id = uuid.UUID(body.id)
    except ValueError:
        raise HTTPException(status_code=422, detail="无效的 id 格式（需为 UUID）")

    result = await db.execute(
        select(ExternalIdentity).where(
            ExternalIdentity.id == target_id,
            ExternalIdentity.user_id == current_user.id,
        )
    )
    ei = result.scalar_one_or_none()
    if ei is None:
        raise HTTPException(status_code=404, detail="授权记录不存在或无权操作")
    await db.delete(ei)
    await db.commit()
    return {"ok": True}


@router.get("/weixin/login")
async def weixin_login_sse(
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """微信扫码登录 SSE 流。

    驱动 WeixinAdapter.login_stream()，依次 yield SSE 事件：
      event: qr      data: {"qrcodeData": "<base64 img>"}
      event: scanned data: {}
      event: done    data: {"accountId": "...", "botToken": "...", "baseUrl": "..."}
      event: error   data: {"message": "..."}

    done 时自动把凭据存入 store（enabled=True）。
    微信只能扫码登录，无独立 test_connection；扫码成功即凭据有效。
    """
    from app.channels.adapters.weixin import WeixinAdapter, LoginEventKind, LOGIN_BASE_URL

    user_id = current_user.id

    async def event_stream() -> AsyncGenerator[str, None]:
        # login_stream 是实例方法，但不使用 bot_token/account_id（仅用 base_url）
        # 传占位符以通过构造函数验证
        temp_adapter = WeixinAdapter(
            bot_token="__login_placeholder__",
            account_id="__login_placeholder__",
        )
        try:
            async for event in temp_adapter.login_stream():
                sse_data = json.dumps(event.to_sse_data(), ensure_ascii=False)
                yield f"event: {event.kind.value}\ndata: {sse_data}\n\n"

                if event.kind == LoginEventKind.DONE:
                    if event.bot_token and event.account_id:
                        await store.save_config(
                            user_id=user_id,
                            channel="weixin",
                            credentials={
                                "bot_token": event.bot_token,
                                "account_id": event.account_id,
                                "base_url": event.base_url or LOGIN_BASE_URL,
                            },
                            enabled=True,
                        )
                    return
                elif event.kind == LoginEventKind.ERROR:
                    return
        except Exception as exc:
            err_data = json.dumps({"message": str(exc)}, ensure_ascii=False)
            yield f"event: error\ndata: {err_data}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/{channel}/enable", status_code=200)
async def enable_channel(
    channel: str,
    body: EnableChannelBody,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """保存凭据并启用渠道；未提供凭据时用已存凭据重新启用（触发连接管理器 start_one）。"""
    internal = _to_internal(channel)
    if body.credentials:
        await store.save_config(
            user_id=current_user.id,
            channel=internal,
            credentials=body.credentials,
            enabled=True,
        )
    else:
        # 开关快捷重启用：复用已保存凭据，不覆盖（凭据为空会清空配置，故须先存在）
        result = await store.get_config(current_user.id, internal)
        if result is None or not result[0].credentials_encrypted:
            raise HTTPException(status_code=400, detail="请先填写并保存凭据后再启用")
        await store.set_enabled(current_user.id, internal, enabled=True)
    if _manager is not None:
        try:
            await _manager.start_one(current_user.id, internal)
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail=f"渠道连接启动失败: {exc}",
            )
    return {"ok": True}


@router.post("/{channel}/disable", status_code=200)
async def disable_channel(
    channel: str,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """停止连接并把 enabled 置 false（保留凭据）。"""
    internal = _to_internal(channel)
    if await store.get_config(current_user.id, internal) is None:
        raise HTTPException(status_code=404, detail="渠道未配置")

    if _manager is not None:
        try:
            await _manager.stop_one(current_user.id, internal)
        except Exception:
            pass  # 停止失败不阻塞 disable（容错）

    await store.set_enabled(current_user.id, internal, enabled=False)
    return {"ok": True}


@router.post("/{channel}/test", response_model=TestChannelResponse)
async def test_channel(
    channel: str,
    body: TestChannelBody,
    current_user: User = Depends(get_current_user),
) -> TestChannelResponse:
    """用提供的凭据测试连接，返回 {ok, bot_username?, error?}。

    飞书：GET /bot/v3/info（需真实 app_id / app_secret 及网络）。
    钉钉：POST /v1.0/oauth2/accessToken 取 token（凭据即校验）。
    微信：走扫码登录，无法 test_connection，返回 400。
    """
    internal = _to_internal(channel)
    try:
        if internal == "feishu":
            from app.channels.adapters.feishu import FeishuAdapter

            app_id = body.credentials.get("app_id")
            app_secret = body.credentials.get("app_secret")
            if not app_id or not app_secret:
                raise HTTPException(
                    status_code=422, detail="飞书凭据必须包含 app_id 和 app_secret"
                )
            adapter = FeishuAdapter(app_id=app_id, app_secret=app_secret)
            info = await adapter.test_connection()
            return TestChannelResponse(ok=True, bot_username=info.get("app_name") or None)

        elif internal == "dingtalk":
            from app.channels.adapters.dingtalk import DingTalkAdapter

            client_id = body.credentials.get("client_id")
            client_secret = body.credentials.get("client_secret")
            if not client_id or not client_secret:
                raise HTTPException(
                    status_code=422, detail="钉钉凭据必须包含 client_id 和 client_secret"
                )
            adapter = DingTalkAdapter(client_id=client_id, client_secret=client_secret)
            # 钉钉无 test_connection()；成功取 token 即凭据有效（需真实网络）
            await adapter._get_token()
            return TestChannelResponse(ok=True)

        else:
            # 微信走扫码登录，无法主动测连
            raise HTTPException(
                status_code=400,
                detail="微信渠道不支持 test_connection，请通过扫码登录验证凭据",
            )
    except HTTPException:
        raise
    except Exception as exc:
        return TestChannelResponse(ok=False, error=str(exc))


@router.get("/{channel}/settings", response_model=ChannelSettingsOut)
async def get_channel_settings(
    channel: str,
    current_user: User = Depends(get_current_user),
) -> ChannelSettingsOut:
    """查询渠道的默认数据空间 / 模型设置。"""
    internal = _to_internal(channel)
    result = await store.get_config(current_user.id, internal)
    if result is None:
        return ChannelSettingsOut()
    cfg, _ = result
    return ChannelSettingsOut(
        default_data_space_id=(
            str(cfg.default_data_space_id) if cfg.default_data_space_id else None
        ),
        default_model=cfg.default_model,
    )


@router.put("/{channel}/settings", response_model=ChannelSettingsOut)
async def update_channel_settings(
    channel: str,
    body: ChannelSettingsIn,
    current_user: User = Depends(get_current_user),
) -> ChannelSettingsOut:
    """更新渠道的默认数据空间 / 模型设置（渠道须已配置）。"""
    internal = _to_internal(channel)
    if await store.get_config(current_user.id, internal) is None:
        raise HTTPException(status_code=404, detail="渠道未配置，请先启用后再设置")

    new_space_id: Optional[uuid.UUID] = None
    if body.default_data_space_id:
        try:
            new_space_id = uuid.UUID(body.default_data_space_id)
        except ValueError:
            raise HTTPException(
                status_code=422, detail="default_data_space_id 格式无效（需为 UUID）"
            )

    await store.set_settings(
        current_user.id,
        internal,
        default_data_space_id=new_space_id,
        default_model=body.default_model,
    )
    return ChannelSettingsOut(
        default_data_space_id=body.default_data_space_id,
        default_model=body.default_model,
    )
