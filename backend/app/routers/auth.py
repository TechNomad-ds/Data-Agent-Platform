"""认证路由 - 注册、登录、刷新令牌"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.database import get_db
from app.core.security import hash_password, verify_password, create_access_token, create_refresh_token, decode_token
from app.models.user import User
from app.models.credit import CreditAccount
from app.schemas import UserRegister, UserLogin, TokenResponse, TokenRefresh, UserResponse, ChangePasswordRequest, UpdateProfileRequest
from app.deps import get_current_user
from app.config import settings

router = APIRouter()


async def _check_daily_credit_reset(user_id, db: AsyncSession):
    """检查并发放每日免费额度（委托给 credits 模块的统一实现）"""
    from app.routers.credits import _ensure_daily_credits
    await _ensure_daily_credits(user_id, db)


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(data: UserRegister, db: AsyncSession = Depends(get_db)):
    """用户注册"""
    email = data.email.lower()
    username = data.username.strip()

    # 检查邮箱是否已存在
    result = await db.execute(select(User).where(func.lower(User.email) == email))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="该邮箱已被注册")

    # 检查用户名是否已存在
    result = await db.execute(select(User).where(func.lower(User.username) == username.lower()))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="该用户名已被使用")

    user = User(
        email=email,
        username=username,
        password_hash=hash_password(data.password),
        research_consent=data.research_consent,
    )
    db.add(user)
    await db.flush()

    # 创建额度账户
    credit_account = CreditAccount(
        user_id=user.id,
        balance=settings.daily_free_credits,
        daily_free_allowance=settings.daily_free_credits,
        last_daily_reset=datetime.now(timezone.utc),
    )
    db.add(credit_account)

    await db.flush()
    await db.refresh(user)

    return user


@router.post("/login", response_model=TokenResponse)
async def login(data: UserLogin, db: AsyncSession = Depends(get_db)):
    """用户登录"""
    login_id = data.email.strip()
    login_key = login_id.lower()

    # 检查账号是否被锁定（5次失败锁15分钟）
    # 注意：限流必须 fail-closed —— Redis 不可用时拒绝登录，
    # 否则一旦 Redis 宕机，失败计数/锁定逻辑全部失效，等于放开无限次密码尝试（暴力破解）。
    from app.core.redis_client import get_redis
    try:
        redis = await get_redis()
        lock_key = f"login_lock:{login_key}"
        fail_key = f"login_fail:{login_key}"
        if await redis.get(lock_key):
            raise HTTPException(status_code=429, detail="登录失败次数过多，请 15 分钟后再试")
    except HTTPException:
        raise
    except Exception:
        import logging
        logging.getLogger("security").error("登录限流依赖 Redis 不可用，已拒绝本次登录请求")
        raise HTTPException(status_code=503, detail="登录服务暂时不可用，请稍后再试")

    # 支持邮箱或用户名登录
    from sqlalchemy import or_
    result = await db.execute(
        select(User).where(
            or_(func.lower(User.email) == login_key, func.lower(User.username) == login_key)
        )
    )
    user = result.scalar_one_or_none()

    if not user or not verify_password(data.password, user.password_hash):
        # 记录失败次数
        if redis:
            try:
                fails = await redis.get(fail_key)
                fail_count = int(fails) + 1 if fails else 1
                await redis.set(fail_key, str(fail_count), ex=900)
                if fail_count >= 5:
                    await redis.set(lock_key, "1", ex=900)
                    import logging
                    logging.getLogger("security").warning(f"账号 {login_id} 因连续 {fail_count} 次登录失败被锁定 15 分钟")
            except Exception:
                pass
        raise HTTPException(status_code=401, detail="邮箱或密码错误")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="账号已被禁用")

    # 登录成功，清除失败计数
    if redis:
        try:
            await redis.delete(fail_key, lock_key)
        except Exception:
            pass

    # 更新最后登录时间
    user.last_login_at = datetime.now(timezone.utc)

    # 检查并发放每日免费额度
    await _check_daily_credit_reset(user.id, db)

    access_token = create_access_token(data={"sub": str(user.id)})
    refresh_token = create_refresh_token(data={"sub": str(user.id)})

    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(data: TokenRefresh, db: AsyncSession = Depends(get_db)):
    """刷新访问令牌"""
    payload = decode_token(data.refresh_token)
    if payload is None or payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="无效的刷新令牌")

    user_id = payload.get("sub")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="用户不存在或已被禁用")

    access_token = create_access_token(data={"sub": str(user.id)})
    refresh_token = create_refresh_token(data={"sub": str(user.id)})

    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    """获取当前用户信息"""
    return current_user


@router.put("/password")
async def change_password(
    data: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """修改密码"""
    if not verify_password(data.old_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="旧密码不正确")

    current_user.password_hash = hash_password(data.new_password)
    return {"message": "密码已修改"}


@router.put("/profile", response_model=UserResponse)
async def update_profile(
    data: UpdateProfileRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """更新用户资料"""
    if data.username is not None:
        existing = await db.execute(
            select(User).where(User.username == data.username, User.id != current_user.id)
        )
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="该用户名已被使用")
        current_user.username = data.username

    if data.research_consent is not None:
        current_user.research_consent = data.research_consent

    return current_user
