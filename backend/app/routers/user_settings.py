"""用户设置路由 - API 模式切换 + API 配置 + 模型映射"""
import re
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.redis_client import get_redis
from app.deps import get_current_user
from app.models.user import User
from app.models.user_api_key import UserApiKey
from app.models.llm_model import LLMModel
from app.core.security import encrypt_api_key
from app.schemas.user_settings import ModelOption

router = APIRouter()


def _mask_key(key: str) -> str:
    if len(key) <= 8:
        return "***"
    return key[:4] + "..." + key[-4:]


# ── API 模式切换 ────────────────────────────────

@router.get("/api-mode")
async def get_api_mode(current_user: User = Depends(get_current_user)):
    redis = await get_redis()
    mode = await redis.get(f"user_pref:{current_user.id}:api_mode")
    return {"mode": mode or "credits"}


@router.put("/api-mode")
async def set_api_mode(
    data: dict,
    current_user: User = Depends(get_current_user),
):
    mode = data.get("mode", "credits")
    if mode not in ("credits", "own_api"):
        raise HTTPException(status_code=400, detail="无效的模式")
    redis = await get_redis()
    await redis.set(f"user_pref:{current_user.id}:api_mode", mode)
    return {"mode": mode}


# ── API 配置（一个用户一个） ──────────────────────

class ApiConfigSave(BaseModel):
    api_base_url: str = Field(..., min_length=1)
    api_key: str = Field(..., min_length=5)


@router.get("/api-config")
async def get_api_config(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(UserApiKey).where(UserApiKey.user_id == current_user.id, UserApiKey.is_active == True)
    )
    key = result.scalars().first()
    if not key:
        return {"configured": False}
    return {
        "configured": True,
        "api_base_url": key.api_base_url,
        "api_key_masked": _mask_key(key.api_key_encrypted),
        "model_mappings": key.model_mappings or {},
    }


@router.put("/api-config")
async def save_api_config(
    data: ApiConfigSave,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # 自动补全 /v1
    base_url = data.api_base_url.rstrip("/")
    if re.match(r'^https?://[^/]+(:\d+)?$', base_url):
        base_url += "/v1"

    # 查找已有配置
    result = await db.execute(
        select(UserApiKey).where(UserApiKey.user_id == current_user.id)
    )
    key = result.scalars().first()

    if key:
        key.api_key_encrypted = encrypt_api_key(data.api_key)
        key.api_base_url = base_url
        key.is_active = True
    else:
        key = UserApiKey(
            user_id=current_user.id,
            provider="openai",
            api_key_encrypted=encrypt_api_key(data.api_key),
            api_base_url=base_url,
            model_name="",
            display_name="我的 API",
            model_mappings={},
        )
        db.add(key)

    await db.flush()
    return {
        "configured": True,
        "api_base_url": key.api_base_url,
        "api_key_masked": _mask_key(key.api_key_encrypted),
        "model_mappings": key.model_mappings or {},
    }


@router.delete("/api-config", status_code=204)
async def delete_api_config(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(UserApiKey).where(UserApiKey.user_id == current_user.id)
    )
    key = result.scalars().first()
    if key:
        await db.delete(key)
        await db.flush()
    # 切回额度模式
    redis = await get_redis()
    await redis.set(f"user_pref:{current_user.id}:api_mode", "credits")


# ── 模型映射 ──────────────────────────────────────

class MappingAdd(BaseModel):
    platform_model_id: str = Field(..., min_length=1)
    api_model_name: str = Field(..., min_length=1)


@router.post("/api-config/mappings")
async def add_mapping(
    data: MappingAdd,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(UserApiKey).where(UserApiKey.user_id == current_user.id, UserApiKey.is_active == True)
    )
    key = result.scalars().first()
    if not key:
        raise HTTPException(status_code=400, detail="请先配置 API")

    # 验证平台模型存在
    model_result = await db.execute(
        select(LLMModel).where(LLMModel.id == data.platform_model_id, LLMModel.is_active == True)
    )
    if not model_result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="平台模型不存在")

    # 验证连通性：用用户的 API + 映射的模型名试一下
    from app.core.security import decrypt_api_key
    await _test_api_connection(key.api_base_url, decrypt_api_key(key.api_key_encrypted), data.api_model_name)

    mappings = dict(key.model_mappings or {})
    mappings[data.platform_model_id] = data.api_model_name
    key.model_mappings = mappings
    await db.flush()
    return {"model_mappings": key.model_mappings}


@router.delete("/api-config/mappings/{model_id}")
async def delete_mapping(
    model_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(UserApiKey).where(UserApiKey.user_id == current_user.id, UserApiKey.is_active == True)
    )
    key = result.scalars().first()
    if not key:
        raise HTTPException(status_code=404)

    mappings = dict(key.model_mappings or {})
    mappings.pop(model_id, None)
    key.model_mappings = mappings
    await db.flush()
    return {"model_mappings": key.model_mappings}


# ── 可用模型列表 ──────────────────────────────────

@router.get("/models", response_model=list[ModelOption])
async def list_available_models(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """返回平台可用模型"""
    models: list[ModelOption] = []
    result = await db.execute(
        select(LLMModel).where(LLMModel.is_active == True, LLMModel.visible_to_users == True)
    )
    for m in result.scalars().all():
        # 防御：跳过 id / display_name / model_name 为空（或全空白）的脏记录，
        # 避免前端模型下拉框出现一个能选中却空白的项。
        if not (m.id or "").strip() or not (m.display_name or "").strip() or not (m.model_name or "").strip():
            continue
        models.append(ModelOption(
            id=m.id,
            display_name=m.display_name,
            model_name=m.model_name,
            provider=m.provider,
            source="platform",
            credit_multiplier=float(m.credit_multiplier),
        ))
    return models


# ── 工具函数 ──────────────────────────────────────

async def _test_api_connection(api_base_url: str, api_key: str, model_name: str):
    from openai import AsyncOpenAI

    try:
        client = AsyncOpenAI(api_key=api_key, base_url=api_base_url, timeout=15)
        await client.chat.completions.create(
            model=model_name,
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=1,
        )
    except Exception as e:
        error_msg = str(e)
        if "401" in error_msg or "Unauthorized" in error_msg:
            raise HTTPException(status_code=400, detail="API Key 无效，请检查后重试")
        elif "404" in error_msg or "model" in error_msg.lower():
            raise HTTPException(status_code=400, detail=f"模型 '{model_name}' 不存在，请检查模型名称")
        elif "connect" in error_msg.lower() or "timeout" in error_msg.lower() or "resolve" in error_msg.lower():
            raise HTTPException(status_code=400, detail=f"无法连接到 {api_base_url}，请检查 API 地址")
        else:
            raise HTTPException(status_code=400, detail=f"API 验证失败: {error_msg[:200]}")
