"""额度相关的请求/响应模型"""
import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class CreditBalanceResponse(BaseModel):
    balance: int
    daily_free_allowance: int
    last_daily_reset: Optional[datetime] = None


class CreditTransactionResponse(BaseModel):
    id: uuid.UUID
    amount: int
    balance_after: int
    transaction_type: str
    description: Optional[str] = None
    metadata_: dict = {}
    created_at: datetime

    class Config:
        from_attributes = True


class CreditHistoryResponse(BaseModel):
    transactions: list[CreditTransactionResponse]
    total: int
