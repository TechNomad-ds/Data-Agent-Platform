"""额度路由"""
import uuid
from datetime import datetime, timezone, date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.database import get_db
from app.deps import get_current_user
from app.models.user import User
from app.models.credit import CreditAccount, CreditTransaction
from app.schemas.credit import CreditBalanceResponse, CreditTransactionResponse, CreditHistoryResponse

router = APIRouter()


async def _ensure_daily_credits(user_id: uuid.UUID, db: AsyncSession) -> None:
    """确保今日额度已发放"""
    result = await db.execute(
        select(CreditAccount).where(CreditAccount.user_id == user_id)
    )
    account = result.scalar_one_or_none()
    if not account:
        return

    today = date.today()
    last_reset = account.last_daily_reset.date() if account.last_daily_reset else None

    if last_reset != today:
        grant_amount = account.daily_free_allowance
        account.balance += grant_amount
        account.last_daily_reset = datetime.now(timezone.utc)
        transaction = CreditTransaction(
            user_id=user_id,
            amount=grant_amount,
            balance_after=account.balance,
            transaction_type="daily_grant",
            description=f"每日免费额度发放 ({today.isoformat()})",
        )
        db.add(transaction)
        await db.flush()


@router.get("/balance", response_model=CreditBalanceResponse)
async def get_balance(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取当前额度余额"""
    await _ensure_daily_credits(current_user.id, db)

    result = await db.execute(
        select(CreditAccount).where(CreditAccount.user_id == current_user.id)
    )
    account = result.scalar_one_or_none()
    if not account:
        return CreditBalanceResponse(balance=0, daily_free_allowance=0)

    return CreditBalanceResponse(
        balance=account.balance,
        daily_free_allowance=account.daily_free_allowance,
        last_daily_reset=account.last_daily_reset,
    )


@router.get("/history", response_model=CreditHistoryResponse)
async def get_history(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取额度使用记录"""
    count_result = await db.execute(
        select(func.count()).select_from(CreditTransaction)
        .where(CreditTransaction.user_id == current_user.id)
    )
    total = count_result.scalar()

    result = await db.execute(
        select(CreditTransaction)
        .where(CreditTransaction.user_id == current_user.id)
        .order_by(CreditTransaction.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    transactions = result.scalars().all()

    return CreditHistoryResponse(transactions=transactions, total=total)
