"""管理后台路由"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.config import settings
from app.core.database import get_db
from app.deps import get_admin_user
from app.models.user import User
from app.models.file import File
from app.models.credit import CreditAccount, CreditTransaction
from app.models.feedback import Feedback
from app.models.llm_model import LLMModel
from app.models.conversation import Conversation, Message
from app.schemas import UserResponse

router = APIRouter()


# ===== 用户管理 =====

@router.get("/users", response_model=list[UserResponse])
async def list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    admin: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """获取用户列表"""
    result = await db.execute(
        select(User).order_by(User.created_at.desc())
        .offset((page - 1) * page_size).limit(page_size)
    )
    return result.scalars().all()


class UserStatusUpdate(BaseModel):
    is_active: bool | None = None
    role: str | None = None


@router.put("/users/{user_id}")
async def update_user_status(
    user_id: uuid.UUID,
    data: UserStatusUpdate,
    admin: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """更新用户状态"""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    if data.is_active is not None:
        user.is_active = data.is_active
    if data.role is not None:
        user.role = data.role

    return {"message": "用户状态已更新"}


# ===== 额度管理 =====

class CreditGrant(BaseModel):
    user_id: uuid.UUID
    amount: int
    description: str = "管理员手动调整"


@router.post("/credits/grant")
async def grant_credits(
    data: CreditGrant,
    admin: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """管理员手动增减额度"""
    result = await db.execute(
        select(CreditAccount).where(CreditAccount.user_id == data.user_id)
    )
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="用户额度账户不存在")

    account.balance += data.amount
    transaction = CreditTransaction(
        user_id=data.user_id,
        amount=data.amount,
        balance_after=account.balance,
        transaction_type="admin_grant",
        description=data.description,
    )
    db.add(transaction)

    return {"message": f"已调整额度 {data.amount}，当前余额 {account.balance}"}


# ===== 模型配置 =====

class ModelConfigCreate(BaseModel):
    id: str
    provider: str = "openai"
    display_name: str
    api_base: str = ""
    api_key: str = ""
    model_name: str
    credit_multiplier: float = 1.0
    max_tokens: int = 4096
    is_active: bool = True
    visible_to_users: bool = True


@router.get("/models")
async def list_models(
    admin: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """获取模型配置列表"""
    result = await db.execute(select(LLMModel).order_by(LLMModel.id))
    models = result.scalars().all()
    return [
        {
            "id": m.id, "provider": m.provider, "display_name": m.display_name,
            "api_base": m.api_base, "model_name": m.model_name,
            "credit_multiplier": float(m.credit_multiplier),
            "max_tokens": m.max_tokens, "is_active": m.is_active,
            "visible_to_users": m.visible_to_users,
        }
        for m in models
    ]


@router.post("/models", status_code=201)
async def create_model(
    data: ModelConfigCreate,
    admin: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """添加模型配置（API 地址和 Key 留空则自动用全局配置）"""
    from app.core.security import encrypt_api_key
    api_base = data.api_base or settings.openai_api_base
    api_key = data.api_key or settings.openai_api_key
    if not api_key:
        raise HTTPException(status_code=400, detail="请先在「全局 API」中配置 API Key")
    encrypted_key = encrypt_api_key(api_key)

    model = LLMModel(
        id=data.id, provider=data.provider, display_name=data.display_name,
        api_base=api_base, api_key_encrypted=encrypted_key,
        model_name=data.model_name, credit_multiplier=data.credit_multiplier,
        max_tokens=data.max_tokens, is_active=data.is_active,
        visible_to_users=data.visible_to_users,
    )
    db.add(model)
    return {"message": "模型配置已添加"}


class ModelConfigUpdate(BaseModel):
    display_name: str | None = None
    provider: str | None = None
    api_base: str | None = None
    api_key: str | None = None
    model_name: str | None = None
    credit_multiplier: float | None = None
    max_tokens: int | None = None
    is_active: bool | None = None
    visible_to_users: bool | None = None


@router.put("/models/{model_id}")
async def update_model(
    model_id: str,
    data: ModelConfigUpdate,
    admin: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """编辑模型配置"""
    result = await db.execute(select(LLMModel).where(LLMModel.id == model_id))
    model = result.scalar_one_or_none()
    if not model:
        raise HTTPException(status_code=404, detail="模型不存在")

    if data.display_name is not None:
        model.display_name = data.display_name
    if data.provider is not None:
        model.provider = data.provider
    if data.api_base is not None:
        model.api_base = data.api_base
    if data.api_key is not None:
        from app.core.security import encrypt_api_key
        model.api_key_encrypted = encrypt_api_key(data.api_key)
    if data.model_name is not None:
        model.model_name = data.model_name
    if data.credit_multiplier is not None:
        model.credit_multiplier = data.credit_multiplier
    if data.max_tokens is not None:
        model.max_tokens = data.max_tokens
    if data.is_active is not None:
        model.is_active = data.is_active
    if data.visible_to_users is not None:
        model.visible_to_users = data.visible_to_users

    return {"message": "模型配置已更新"}


@router.delete("/models/{model_id}", status_code=204)
async def delete_model(
    model_id: str,
    admin: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """删除模型配置"""
    result = await db.execute(select(LLMModel).where(LLMModel.id == model_id))
    model = result.scalar_one_or_none()
    if not model:
        raise HTTPException(status_code=404, detail="模型不存在")
    await db.delete(model)


@router.post("/models/test")
async def test_model_connection(
    data: ModelConfigCreate,
    admin: User = Depends(get_admin_user),
):
    """测试模型连通性"""
    from openai import AsyncOpenAI
    api_key = data.api_key if data.api_key and data.api_key != "use-saved" else settings.openai_api_key
    api_base = data.api_base or settings.openai_api_base
    if not api_key:
        return {"status": "error", "message": "未配置 API Key，请先保存全局 API 配置"}
    try:
        client = AsyncOpenAI(api_key=api_key, base_url=api_base, timeout=15)
        response = await client.chat.completions.create(
            model=data.model_name,
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=1,
        )
        return {"status": "ok", "message": f"连接成功，模型 {data.model_name} 可用"}
    except Exception as e:
        error = str(e)
        if "401" in error or "Unauthorized" in error:
            return {"status": "error", "message": "API Key 无效"}
        elif "404" in error:
            return {"status": "error", "message": f"模型 {data.model_name} 不存在"}
        elif "connect" in error.lower() or "timeout" in error.lower():
            return {"status": "error", "message": f"无法连接到 {data.api_base}"}
        return {"status": "error", "message": f"测试失败: {error[:200]}"}


# ===== 系统设置（运行时可调） =====

RUNTIME_CONFIG_KEYS = {
    "daily_free_credits": {"type": "int", "label": "每日免费额度", "default": 20, "min": 0, "max": 10000},
    "max_credits_per_run": {"type": "int", "label": "单次对话最大消耗", "default": 50, "min": 1, "max": 500},
    "max_spaces_per_user": {"type": "int", "label": "每用户最大空间数", "default": 20, "min": 1, "max": 100},
    "max_conversations_per_user": {"type": "int", "label": "每用户最大对话数", "default": 200, "min": 10, "max": 5000},
    "max_files_per_space": {"type": "int", "label": "每空间最大文件数", "default": 50, "min": 1, "max": 500},
    "graph_auto_extract": {"type": "bool", "label": "上传时自动构建知识图谱", "default": True},
    "enable_prompt_caching": {"type": "bool", "label": "启用 Prompt 缓存", "default": True},
}


@router.get("/global-api")
async def get_global_api(admin: User = Depends(get_admin_user)):
    """获取全局 API 配置"""
    from app.core.redis_client import get_redis
    redis = await get_redis()
    api_base = await redis.get("global:api_base") or settings.openai_api_base or ""
    api_key_set = bool(await redis.get("global:api_key") or settings.openai_api_key)
    return {"api_base": api_base, "api_key_set": api_key_set}


class GlobalApiUpdate(BaseModel):
    api_base: str = ""
    api_key: str = ""


@router.put("/global-api")
async def update_global_api(
    data: GlobalApiUpdate,
    admin: User = Depends(get_admin_user),
):
    """更新全局 API 配置，同步到所有模型"""
    from app.core.redis_client import get_redis
    from app.core.security import encrypt_api_key
    from app.core.database import get_session_factory
    redis = await get_redis()

    if data.api_base:
        base = data.api_base.rstrip("/")
        await redis.set("global:api_base", base)
        settings.openai_api_base = base

    if data.api_key:
        await redis.set("global:api_key", data.api_key)
        settings.openai_api_key = data.api_key

    # 同步到所有模型
    if data.api_base or data.api_key:
        try:
            async with get_session_factory()() as db:
                result = await db.execute(select(LLMModel))
                for model in result.scalars().all():
                    if data.api_base:
                        model.api_base = data.api_base.rstrip("/")
                    if data.api_key:
                        model.api_key_encrypted = encrypt_api_key(data.api_key)
                await db.commit()
        except Exception as e:
            import logging
            logging.getLogger("admin").error(f"同步模型失败: {e}", exc_info=True)

    return {"message": "全局 API 配置已更新，所有模型已同步"}


# ===== OCR 配置（PaddleOCR-VL，用于 PDF/图片解析） =====

@router.get("/ocr-config")
async def get_ocr_config(admin: User = Depends(get_admin_user)):
    """获取 OCR 配置"""
    from app.core.redis_client import get_redis
    redis = await get_redis()
    ocr_base = await redis.get("global:ocr_base") or settings.ocr_api_base or ""
    ocr_model = await redis.get("global:ocr_model") or settings.ocr_model or ""
    token_set = bool(await redis.get("global:ocr_token") or settings.ocr_api_key)
    return {"ocr_base": ocr_base, "ocr_model": ocr_model, "ocr_token_set": token_set}


class OcrConfigUpdate(BaseModel):
    ocr_base: str = ""
    ocr_token: str = ""
    ocr_model: str = ""


@router.put("/ocr-config")
async def update_ocr_config(
    data: OcrConfigUpdate,
    admin: User = Depends(get_admin_user),
):
    """更新 OCR 配置（存入 Redis，即时生效）"""
    from app.core.redis_client import get_redis
    redis = await get_redis()

    if data.ocr_base:
        base = data.ocr_base.rstrip("/")
        await redis.set("global:ocr_base", base)
        settings.ocr_api_base = base
    if data.ocr_token:
        await redis.set("global:ocr_token", data.ocr_token)
        settings.ocr_api_key = data.ocr_token
    if data.ocr_model:
        await redis.set("global:ocr_model", data.ocr_model)
        settings.ocr_model = data.ocr_model

    return {"message": "OCR 配置已更新"}


@router.get("/config")
async def get_runtime_config(
    admin: User = Depends(get_admin_user),
):
    """获取运行时系统配置"""
    from app.core.redis_client import get_redis
    redis = await get_redis()
    result = {}
    for key, meta in RUNTIME_CONFIG_KEYS.items():
        cached = await redis.get(f"config:{key}")
        if cached is not None:
            if meta["type"] == "bool":
                value = cached.lower() in ("true", "1")
            else:
                value = int(cached)
        else:
            value = getattr(settings, key, meta["default"])
        result[key] = {"value": value, **meta}
    return result


class ConfigUpdate(BaseModel):
    key: str
    value: str


@router.put("/config")
async def update_runtime_config(
    data: ConfigUpdate,
    admin: User = Depends(get_admin_user),
):
    """更新运行时配置（即时生效，存入 Redis）"""
    if data.key not in RUNTIME_CONFIG_KEYS:
        raise HTTPException(status_code=400, detail=f"不支持的配置项: {data.key}")

    meta = RUNTIME_CONFIG_KEYS[data.key]
    from app.core.redis_client import get_redis
    redis = await get_redis()

    if meta["type"] == "int":
        try:
            val = int(data.value)
        except ValueError:
            raise HTTPException(status_code=400, detail="请输入数字")
        if "min" in meta and val < meta["min"]:
            raise HTTPException(status_code=400, detail=f"最小值为 {meta['min']}")
        if "max" in meta and val > meta["max"]:
            raise HTTPException(status_code=400, detail=f"最大值为 {meta['max']}")
        await redis.set(f"config:{data.key}", str(val))
        setattr(settings, data.key, val)

        # 改每日额度时同步更新所有用户
        if data.key == "daily_free_credits":
            from app.core.database import get_session_factory
            from sqlalchemy import update
            async with get_session_factory()() as db:
                await db.execute(
                    update(CreditAccount).values(daily_free_allowance=val)
                )
                await db.commit()

    elif meta["type"] == "bool":
        val = data.value.lower() in ("true", "1")
        await redis.set(f"config:{data.key}", str(val))
        setattr(settings, data.key, val)

    return {"message": f"{meta['label']} 已更新为 {data.value}"}


# ===== 用户详情 =====

@router.get("/users/{user_id}/detail")
async def get_user_detail(
    user_id: uuid.UUID,
    admin: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """获取用户详细信息（空间、文件、对话、额度）"""
    from app.models.data_space import DataSpace, DataSpaceFile

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    spaces_result = await db.execute(
        select(DataSpace).where(DataSpace.user_id == user_id).order_by(DataSpace.updated_at.desc())
    )
    spaces = spaces_result.scalars().all()

    file_count = (await db.execute(
        select(func.count()).select_from(File).where(File.user_id == user_id)
    )).scalar() or 0

    conv_count = (await db.execute(
        select(func.count()).select_from(Conversation).where(Conversation.user_id == user_id)
    )).scalar() or 0

    msg_count = (await db.execute(
        select(func.count()).select_from(Message)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(Conversation.user_id == user_id)
    )).scalar() or 0

    credit_result = await db.execute(
        select(CreditAccount).where(CreditAccount.user_id == user_id)
    )
    credit = credit_result.scalar_one_or_none()

    return {
        "user": {
            "id": str(user.id), "email": user.email, "username": user.username,
            "role": user.role, "is_active": user.is_active,
            "created_at": user.created_at.isoformat() if user.created_at else None,
            "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
        },
        "spaces": [{"id": str(s.id), "name": s.name, "updated_at": s.updated_at.isoformat() if s.updated_at else None} for s in spaces],
        "file_count": file_count,
        "conversation_count": conv_count,
        "message_count": msg_count,
        "credit_balance": credit.balance if credit else 0,
        "daily_allowance": credit.daily_free_allowance if credit else 0,
    }


# ===== 统计概览 =====

@router.get("/stats")
async def get_stats(
    admin: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """获取平台统计数据"""
    from datetime import datetime, timezone, timedelta
    from app.models.data_space import DataSpace

    user_count = (await db.execute(select(func.count()).select_from(User))).scalar()
    file_count = (await db.execute(select(func.count()).select_from(File))).scalar()
    feedback_count = (await db.execute(select(func.count()).select_from(Feedback))).scalar()
    conversation_count = (await db.execute(select(func.count()).select_from(Conversation))).scalar()
    message_count = (await db.execute(select(func.count()).select_from(Message))).scalar()
    space_count = (await db.execute(select(func.count()).select_from(DataSpace))).scalar()

    now = datetime.now(timezone.utc)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_ago = today - timedelta(days=7)

    active_today = (await db.execute(
        select(func.count(func.distinct(Conversation.user_id)))
        .where(Conversation.updated_at >= today)
    )).scalar()

    new_users_week = (await db.execute(
        select(func.count()).select_from(User).where(User.created_at >= week_ago)
    )).scalar()

    messages_today = (await db.execute(
        select(func.count()).select_from(Message).where(Message.created_at >= today)
    )).scalar()

    total_credits_used = (await db.execute(
        select(func.sum(func.abs(CreditTransaction.amount)))
        .where(CreditTransaction.transaction_type == "usage")
    )).scalar() or 0

    return {
        "total_users": user_count,
        "total_files": file_count,
        "total_feedback": feedback_count,
        "total_conversations": conversation_count,
        "total_messages": message_count,
        "total_spaces": space_count,
        "active_users_today": active_today,
        "new_users_week": new_users_week,
        "messages_today": messages_today,
        "total_credits_consumed": total_credits_used,
    }


@router.get("/stats/daily")
async def get_daily_stats(
    days: int = Query(7, ge=1, le=30),
    admin: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """获取每日统计趋势"""
    from datetime import datetime, timezone, timedelta
    from sqlalchemy import cast, Date

    now = datetime.now(timezone.utc)
    start = now - timedelta(days=days)

    user_daily = await db.execute(
        select(
            cast(User.created_at, Date).label("date"),
            func.count().label("count"),
        )
        .where(User.created_at >= start)
        .group_by(cast(User.created_at, Date))
        .order_by(cast(User.created_at, Date))
    )

    msg_daily = await db.execute(
        select(
            cast(Message.created_at, Date).label("date"),
            func.count().label("count"),
        )
        .where(Message.created_at >= start)
        .group_by(cast(Message.created_at, Date))
        .order_by(cast(Message.created_at, Date))
    )

    return {
        "new_users": [{"date": str(r.date), "count": r.count} for r in user_daily],
        "messages": [{"date": str(r.date), "count": r.count} for r in msg_daily],
    }


@router.get("/conversations")
async def list_all_conversations(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    admin: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """列出所有对话（管理员）"""
    total = (await db.execute(select(func.count()).select_from(Conversation))).scalar()
    result = await db.execute(
        select(Conversation, User.username, User.email)
        .join(User, User.id == Conversation.user_id)
        .order_by(Conversation.updated_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = result.all()
    return {
        "total": total,
        "conversations": [
            {
                "id": str(conv.id),
                "title": conv.title,
                "model_id": conv.model_id,
                "user_id": str(conv.user_id),
                "username": username,
                "email": email,
                "created_at": conv.created_at.isoformat() if conv.created_at else None,
                "updated_at": conv.updated_at.isoformat() if conv.updated_at else None,
            }
            for conv, username, email in rows
        ],
    }


# ===== 安全管理 =====

@router.post("/security/block-ip")
async def block_ip(
    data: dict,
    admin: User = Depends(get_admin_user),
):
    """封禁 IP 地址"""
    ip = data.get("ip", "").strip()
    hours = data.get("hours", 24)
    reason = data.get("reason", "管理员手动封禁")
    if not ip:
        raise HTTPException(status_code=400, detail="请提供 IP 地址")

    from app.core.redis_client import get_redis
    redis = await get_redis()
    await redis.set(f"ip_block:{ip}", reason, ex=int(hours * 3600))

    import logging
    logging.getLogger("security").warning(f"IP {ip} 被管理员封禁 {hours}h，原因: {reason}")
    return {"message": f"已封禁 {ip}，时长 {hours} 小时"}


@router.post("/security/unblock-ip")
async def unblock_ip(
    data: dict,
    admin: User = Depends(get_admin_user),
):
    """解封 IP 地址"""
    ip = data.get("ip", "").strip()
    if not ip:
        raise HTTPException(status_code=400, detail="请提供 IP 地址")

    from app.core.redis_client import get_redis
    redis = await get_redis()
    await redis.delete(f"ip_block:{ip}")
    return {"message": f"已解封 {ip}"}


@router.post("/security/unlock-account")
async def unlock_account(
    data: dict,
    admin: User = Depends(get_admin_user),
):
    """解锁被锁定的账号"""
    email = data.get("email", "").strip()
    if not email:
        raise HTTPException(status_code=400, detail="请提供邮箱")

    from app.core.redis_client import get_redis
    redis = await get_redis()
    await redis.delete(f"login_lock:{email}", f"login_fail:{email}")
    return {"message": f"已解锁 {email}"}


# ===== 研究数据导出 =====

@router.get("/research/export")
async def export_research_data(
    format: str = Query("json", pattern="^(json|csv)$"),
    consent_only: bool = Query(True, description="是否只导出已授权用户的数据"),
    admin: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """一键导出研究数据（按对话组织，包含完整上下文）"""
    import json as json_mod
    from app.models.data_space import DataSpace
    from fastapi.responses import StreamingResponse
    import io

    # 查询符合条件的对话
    conv_query = (
        select(Conversation, User.username, User.email, User.research_consent)
        .join(User, User.id == Conversation.user_id)
    )
    if consent_only:
        conv_query = conv_query.where(User.research_consent == True)

    conv_result = await db.execute(conv_query.order_by(Conversation.created_at))
    conversations = conv_result.all()

    export_rows = []
    for conv, username, email, consented in conversations:
        # 获取该对话的所有消息
        msg_result = await db.execute(
            select(Message)
            .where(Message.conversation_id == conv.id)
            .order_by(Message.created_at)
        )
        messages = msg_result.scalars().all()
        if not messages:
            continue

        # 匿名化：用 hash 替代真实 ID
        anon_user = str(uuid.uuid5(uuid.NAMESPACE_DNS, str(conv.user_id)))[:12]
        anon_conv = str(uuid.uuid5(uuid.NAMESPACE_DNS, str(conv.id)))[:12]

        # 获取数据空间名
        space_name = None
        if conv.data_space_id:
            space_result = await db.execute(select(DataSpace).where(DataSpace.id == conv.data_space_id))
            space = space_result.scalar_one_or_none()
            space_name = space.name if space else None

        turns = []
        for msg in messages:
            turn = {
                "role": msg.role,
                "content": msg.content,
                "token_usage": msg.token_usage,
                "credits_used": msg.credits_used,
                "created_at": msg.created_at.isoformat() if msg.created_at else None,
            }
            if msg.tool_calls:
                turn["tool_calls"] = msg.tool_calls
            turns.append(turn)

        export_rows.append({
            "conversation_id": anon_conv,
            "user_id": anon_user,
            "research_consent": consented,
            "title": conv.title,
            "model_id": conv.model_id,
            "data_space": space_name,
            "created_at": conv.created_at.isoformat() if conv.created_at else None,
            "turn_count": len(turns),
            "turns": turns,
        })

    if format == "csv":
        # CSV: 平铺每条消息为一行
        output = io.StringIO()
        import csv
        writer = csv.writer(output)
        writer.writerow(["conversation_id", "user_id", "title", "model", "data_space", "turn_index", "role", "content", "tokens_in", "tokens_out", "credits", "timestamp"])
        for row in export_rows:
            for i, turn in enumerate(row["turns"]):
                usage = turn.get("token_usage") or {}
                writer.writerow([
                    row["conversation_id"], row["user_id"], row["title"], row["model_id"], row["data_space"],
                    i, turn["role"], (turn["content"] or "")[:2000],
                    usage.get("input_tokens", ""), usage.get("output_tokens", ""),
                    turn.get("credits_used", ""), turn["created_at"],
                ])
        content = output.getvalue()
        return StreamingResponse(
            io.BytesIO(content.encode("utf-8-sig")),
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="datamind_research_export.csv"'},
        )
    else:
        # JSONL: 每行一个完整对话
        lines = [json_mod.dumps(row, ensure_ascii=False) for row in export_rows]
        content = "\n".join(lines)
        return StreamingResponse(
            io.BytesIO(content.encode("utf-8")),
            media_type="application/jsonl",
            headers={"Content-Disposition": 'attachment; filename="datamind_research_export.jsonl"'},
        )


@router.get("/research/stats")
async def research_data_stats(
    admin: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """研究数据概览统计"""
    consented_users = (await db.execute(
        select(func.count()).select_from(User).where(User.research_consent == True)
    )).scalar() or 0
    total_users = (await db.execute(select(func.count()).select_from(User))).scalar() or 0

    consented_convs = (await db.execute(
        select(func.count()).select_from(Conversation)
        .join(User, User.id == Conversation.user_id)
        .where(User.research_consent == True)
    )).scalar() or 0

    consented_msgs = (await db.execute(
        select(func.count()).select_from(Message)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .join(User, User.id == Conversation.user_id)
        .where(User.research_consent == True)
    )).scalar() or 0

    return {
        "consented_users": consented_users,
        "total_users": total_users,
        "consent_rate": round(consented_users / total_users * 100, 1) if total_users > 0 else 0,
        "consented_conversations": consented_convs,
        "consented_messages": consented_msgs,
    }
