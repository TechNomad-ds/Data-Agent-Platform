"""管理后台路由"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.database import get_db
from app.deps import get_admin_user
from app.models.user import User
from app.models.file import File
from app.models.credit import CreditAccount, CreditTransaction
from app.models.feedback import Feedback
from app.models.llm_model import LLMModel
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
    provider: str
    display_name: str
    api_base: str
    api_key: str
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
    result = await db.execute(select(LLMModel))
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
    """添加模型配置"""
    from cryptography.fernet import Fernet
    from app.config import settings

    # 加密 API key
    fernet = Fernet(settings.secret_key.encode().ljust(32)[:32].hex().encode()[:44] + b"=")
    encrypted_key = fernet.encrypt(data.api_key.encode()).decode()

    model = LLMModel(
        id=data.id, provider=data.provider, display_name=data.display_name,
        api_base=data.api_base, api_key_encrypted=encrypted_key,
        model_name=data.model_name, credit_multiplier=data.credit_multiplier,
        max_tokens=data.max_tokens, is_active=data.is_active,
        visible_to_users=data.visible_to_users,
    )
    db.add(model)
    return {"message": "模型配置已添加"}


# ===== 统计概览 =====

@router.get("/stats")
async def get_stats(
    admin: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """获取平台统计数据"""
    user_count = (await db.execute(select(func.count()).select_from(User))).scalar()
    file_count = (await db.execute(select(func.count()).select_from(File))).scalar()
    feedback_count = (await db.execute(select(func.count()).select_from(Feedback))).scalar()

    return {
        "total_users": user_count,
        "total_files": file_count,
        "total_feedback": feedback_count,
    }
