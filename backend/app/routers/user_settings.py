"""用户设置路由 - API Key 管理 + 可用模型列表"""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.deps import get_current_user
from app.models.user import User
from app.models.user_api_key import UserApiKey
from app.models.llm_model import LLMModel
from app.schemas.user_settings import ApiKeyCreate, ApiKeyUpdate, ApiKeyResponse, ModelOption

router = APIRouter()


def _mask_key(key: str) -> str:
    if len(key) <= 8:
        return "***"
    return key[:4] + "..." + key[-4:]


@router.get("/api-keys", response_model=list[ApiKeyResponse])
async def list_api_keys(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(UserApiKey).where(UserApiKey.user_id == current_user.id).order_by(UserApiKey.created_at.desc())
    )
    keys = result.scalars().all()
    return [
        ApiKeyResponse(
            id=str(k.id),
            provider=k.provider,
            api_key_masked=_mask_key(k.api_key_encrypted),
            api_base_url=k.api_base_url,
            model_name=k.model_name,
            display_name=k.display_name,
            is_active=k.is_active,
            created_at=k.created_at,
        )
        for k in keys
    ]


@router.post("/api-keys", response_model=ApiKeyResponse, status_code=201)
async def create_api_key(
    data: ApiKeyCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    key = UserApiKey(
        user_id=current_user.id,
        provider=data.provider,
        api_key_encrypted=data.api_key,
        api_base_url=data.api_base_url,
        model_name=data.model_name,
        display_name=data.display_name,
    )
    db.add(key)
    await db.commit()
    await db.refresh(key)
    return ApiKeyResponse(
        id=str(key.id),
        provider=key.provider,
        api_key_masked=_mask_key(key.api_key_encrypted),
        api_base_url=key.api_base_url,
        model_name=key.model_name,
        display_name=key.display_name,
        is_active=key.is_active,
        created_at=key.created_at,
    )


@router.put("/api-keys/{key_id}", response_model=ApiKeyResponse)
async def update_api_key(
    key_id: uuid.UUID,
    data: ApiKeyUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(UserApiKey).where(UserApiKey.id == key_id, UserApiKey.user_id == current_user.id)
    )
    key = result.scalar_one_or_none()
    if not key:
        raise HTTPException(status_code=404, detail="API Key 不存在")

    if data.api_key is not None:
        key.api_key_encrypted = data.api_key
    if data.api_base_url is not None:
        key.api_base_url = data.api_base_url
    if data.model_name is not None:
        key.model_name = data.model_name
    if data.display_name is not None:
        key.display_name = data.display_name
    if data.is_active is not None:
        key.is_active = data.is_active

    await db.commit()
    await db.refresh(key)
    return ApiKeyResponse(
        id=str(key.id),
        provider=key.provider,
        api_key_masked=_mask_key(key.api_key_encrypted),
        api_base_url=key.api_base_url,
        model_name=key.model_name,
        display_name=key.display_name,
        is_active=key.is_active,
        created_at=key.created_at,
    )


@router.delete("/api-keys/{key_id}", status_code=204)
async def delete_api_key(
    key_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(UserApiKey).where(UserApiKey.id == key_id, UserApiKey.user_id == current_user.id)
    )
    key = result.scalar_one_or_none()
    if not key:
        raise HTTPException(status_code=404, detail="API Key 不存在")
    await db.delete(key)
    await db.commit()


@router.get("/models", response_model=list[ModelOption])
async def list_available_models(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """返回用户可用的所有模型（平台 + 自己的）"""
    models: list[ModelOption] = []

    # 平台模型
    result = await db.execute(
        select(LLMModel).where(LLMModel.is_active == True, LLMModel.visible_to_users == True)
    )
    for m in result.scalars().all():
        models.append(ModelOption(
            id=m.id,
            display_name=m.display_name,
            model_name=m.model_name,
            provider=m.provider,
            source="platform",
            credit_multiplier=float(m.credit_multiplier),
        ))

    # 用户自己的模型
    result = await db.execute(
        select(UserApiKey).where(UserApiKey.user_id == current_user.id, UserApiKey.is_active == True)
    )
    for k in result.scalars().all():
        models.append(ModelOption(
            id=f"user_{k.id}",
            display_name=k.display_name,
            model_name=k.model_name,
            provider=k.provider,
            source="user",
            credit_multiplier=None,
        ))

    return models
