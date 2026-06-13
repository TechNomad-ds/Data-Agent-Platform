"""数据库种子数据 - 从 .env 配置初始化模型"""
import asyncio
import logging
from sqlalchemy import select
from app.core.database import get_session_factory
from app.models.llm_model import LLMModel
from app.config import settings
from app.core.security import encrypt_api_key

logger = logging.getLogger("seed")


def _build_seed_models() -> list[dict]:
    """根据 .env 配置动态生成种子模型列表"""
    models = []

    if settings.llm_backend == "openai" and settings.openai_api_base and settings.openai_api_key:
        model_name = settings.openai_model or "deepseek-chat"
        model_id = model_name.replace("/", "-").lower()
        display_name = model_name.replace("-", " ").title()
        models.append({
            "id": model_id,
            "provider": "openai",
            "display_name": display_name,
            "api_base": settings.openai_api_base,
            "api_key_encrypted": encrypt_api_key(settings.openai_api_key),
            "model_name": model_name,
            "credit_multiplier": 1.0,
            "max_tokens": settings.anthropic_max_tokens,
            "is_active": True,
            "visible_to_users": True,
        })

    if settings.anthropic_api_key:
        models.append({
            "id": settings.anthropic_model.split("/")[-1],
            "provider": "anthropic",
            "display_name": settings.anthropic_model.replace("-", " ").replace("claude ", "Claude ").title(),
            "api_base": "https://api.anthropic.com",
            "api_key_encrypted": encrypt_api_key(settings.anthropic_api_key),
            "model_name": settings.anthropic_model,
            "credit_multiplier": 2.0,
            "max_tokens": settings.anthropic_max_tokens,
            "is_active": True,
            "visible_to_users": True,
        })

    return models


async def seed_admin():
    """内置管理员账号（如果不存在则创建）。

    凭据从配置（.env）读取，不再硬编码在代码里，避免随仓库泄露。
    """
    from app.models.user import User
    from app.models.credit import CreditAccount
    from app.core.security import hash_password
    from datetime import datetime, timezone

    ADMIN_EMAIL = settings.admin_email
    ADMIN_USERNAME = settings.admin_username
    ADMIN_PASSWORD = settings.admin_password

    async with get_session_factory()() as db:
        result = await db.execute(select(User).where(User.username == ADMIN_USERNAME))
        if result.scalar_one_or_none():
            return

        admin = User(
            email=ADMIN_EMAIL,
            username=ADMIN_USERNAME,
            password_hash=hash_password(ADMIN_PASSWORD),
            role="admin",
            is_active=True,
        )
        db.add(admin)
        await db.flush()

        credit = CreditAccount(
            user_id=admin.id,
            balance=settings.daily_free_credits,
            daily_free_allowance=settings.daily_free_credits,
            last_daily_reset=datetime.now(timezone.utc),
        )
        db.add(credit)
        await db.commit()
        logger.info(f"内置管理员已创建: {ADMIN_USERNAME}")


async def seed_models():
    """初始化模型配置（如果不存在则创建，从 .env 读取）"""
    await seed_admin()

    seed_models_data = _build_seed_models()
    if not seed_models_data:
        logger.info("未检测到 LLM 配置，跳过模型种子数据。请在管理后台手动添加模型。")
        return

    async with get_session_factory()() as db:
        for model_data in seed_models_data:
            result = await db.execute(
                select(LLMModel).where(LLMModel.id == model_data["id"])
            )
            if not result.scalar_one_or_none():
                model = LLMModel(**model_data)
                db.add(model)
                logger.info(f"种子模型已添加: {model_data['display_name']} ({model_data['model_name']})")
        await db.commit()


if __name__ == "__main__":
    asyncio.run(seed_models())
