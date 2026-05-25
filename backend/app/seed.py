"""数据库种子数据 - 初始化模型配置"""
import asyncio
from sqlalchemy import select
from app.core.database import get_session_factory
from app.models.llm_model import LLMModel
from app.config import settings


SEED_MODELS = [
    {
        "id": "deepseek-v4-flash",
        "provider": "deepseek",
        "display_name": "DeepSeek V4 Flash",
        "api_base": settings.llm_api_base_url,
        "api_key_encrypted": settings.llm_api_key,
        "model_name": "deepseek-v4-flash",
        "credit_multiplier": 1.0,
        "max_tokens": 8192,
        "is_active": True,
        "visible_to_users": True,
    },
    {
        "id": "qwen3.5-flash",
        "provider": "qwen",
        "display_name": "Qwen 3.5 Flash",
        "api_base": settings.llm_api_base_url,
        "api_key_encrypted": settings.llm_api_key,
        "model_name": "qwen3.5-flash",
        "credit_multiplier": 1.5,
        "max_tokens": 8192,
        "is_active": True,
        "visible_to_users": True,
    },
    {
        "id": "claude-haiku-4-5-20251001",
        "provider": "anthropic",
        "display_name": "Claude Haiku 4.5",
        "api_base": settings.llm_api_base_url,
        "api_key_encrypted": settings.llm_api_key,
        "model_name": "claude-haiku-4-5-20251001",
        "credit_multiplier": 3.0,
        "max_tokens": 8192,
        "is_active": True,
        "visible_to_users": True,
    },
]


async def seed_models():
    """初始化模型配置（如果不存在则创建）"""
    async with get_session_factory()() as db:
        for model_data in SEED_MODELS:
            result = await db.execute(
                select(LLMModel).where(LLMModel.id == model_data["id"])
            )
            if not result.scalar_one_or_none():
                model = LLMModel(**model_data)
                db.add(model)
        await db.commit()


if __name__ == "__main__":
    asyncio.run(seed_models())
