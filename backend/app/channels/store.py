"""渠道持久化层（薄封装）

职责：save_config / get_config / list_configs / set_connected。
凭据以 dict 形式进出，内部透明地 encrypt/decrypt；调用方不碰加密文本。
失败 raise，无 fallback 兜底。
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session_factory
from app.core.security import decrypt_api_key, encrypt_api_key
from app.models.channel_config import ChannelConfig


# ---------------------------------------------------------------------------
# 内部辅助
# ---------------------------------------------------------------------------

def _encrypt_creds(creds: dict[str, Any]) -> str:
    """把凭据 dict 序列化后整体加密，返回加密字符串。"""
    return encrypt_api_key(json.dumps(creds, ensure_ascii=False))


def _decrypt_creds(encrypted: str) -> dict[str, Any]:
    """解密后反序列化为 dict，解密失败直接 raise（不兜底）。"""
    return json.loads(decrypt_api_key(encrypted))


# ---------------------------------------------------------------------------
# 公开 API
# ---------------------------------------------------------------------------

async def save_config(
    *,
    user_id: uuid.UUID,
    channel: str,
    credentials: dict[str, Any],
    enabled: bool = False,
    default_data_space_id: Optional[uuid.UUID] = None,
    default_model: Optional[str] = None,
    bot_info: Optional[dict[str, Any]] = None,
) -> ChannelConfig:
    """新建或更新渠道配置（upsert 语义：若已存在则全量覆盖可写字段）。

    凭据以明文 dict 传入，本函数负责加密后落库。
    """
    encrypted = _encrypt_creds(credentials)
    now = datetime.now(timezone.utc)

    async with get_session_factory()() as db:
        existing = await _fetch(db, user_id, channel)
        if existing is not None:
            existing.credentials_encrypted = encrypted
            existing.enabled = enabled
            existing.default_data_space_id = default_data_space_id
            existing.default_model = default_model
            existing.bot_info = bot_info
            existing.updated_at = now
            await db.commit()
            await db.refresh(existing)
            return existing

        cfg = ChannelConfig(
            user_id=user_id,
            channel=channel,
            credentials_encrypted=encrypted,
            enabled=enabled,
            default_data_space_id=default_data_space_id,
            default_model=default_model,
            bot_info=bot_info,
            created_at=now,
            updated_at=now,
        )
        db.add(cfg)
        await db.commit()
        await db.refresh(cfg)
        return cfg


async def get_config(
    user_id: uuid.UUID,
    channel: str,
) -> Optional[tuple[ChannelConfig, dict[str, Any]]]:
    """返回 (ChannelConfig, 解密后的凭据 dict)；未配置返回 None。

    解密失败 raise ValueError（不兜底）。
    """
    async with get_session_factory()() as db:
        cfg = await _fetch(db, user_id, channel)
        if cfg is None:
            return None
        creds = _decrypt_creds(cfg.credentials_encrypted) if cfg.credentials_encrypted else {}
        return cfg, creds


async def list_configs(user_id: uuid.UUID) -> list[ChannelConfig]:
    """列出该用户所有已配渠道（不返回解密凭据，供前端列表展示）。"""
    async with get_session_factory()() as db:
        result = await db.execute(
            select(ChannelConfig)
            .where(ChannelConfig.user_id == user_id)
            .order_by(ChannelConfig.channel)
        )
        return list(result.scalars().all())


async def set_connected(
    user_id: uuid.UUID,
    channel: str,
    *,
    connected: bool,
    bot_info: Optional[dict[str, Any]] = None,
) -> None:
    """由连接管理进程调用，刷新运行时连接状态和 bot 快照。

    配置不存在时 raise RuntimeError（调用方应确保先 save_config）。
    """
    async with get_session_factory()() as db:
        cfg = await _fetch(db, user_id, channel)
        if cfg is None:
            raise RuntimeError(
                f"channel_config not found: user={user_id} channel={channel}"
            )
        cfg.connected = connected
        cfg.updated_at = datetime.now(timezone.utc)
        if bot_info is not None:
            cfg.bot_info = bot_info
        await db.commit()


# ---------------------------------------------------------------------------
# 内部查询辅助（共享同一 session，不自己开 context）
# ---------------------------------------------------------------------------

async def _fetch(
    db: AsyncSession, user_id: uuid.UUID, channel: str
) -> Optional[ChannelConfig]:
    result = await db.execute(
        select(ChannelConfig).where(
            ChannelConfig.user_id == user_id,
            ChannelConfig.channel == channel,
        )
    )
    return result.scalar_one_or_none()
