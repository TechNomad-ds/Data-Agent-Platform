#!/usr/bin/env python3
"""DataMind Analyst CLI 管理工具

用法:
    python manage.py create-admin          创建管理员账号
    python manage.py reset-password EMAIL  重置用户密码
    python manage.py stats                 查看平台统计
    python manage.py list-models           列出模型配置
    python manage.py seed                  初始化种子数据
"""
import asyncio
import sys
import getpass

from sqlalchemy import select, func


async def create_admin():
    """交互式创建管理员账号"""
    from app.core.database import get_session_factory
    from app.models.user import User
    from app.models.credit import CreditAccount
    from app.core.security import hash_password
    from app.config import settings
    from datetime import datetime, timezone

    print("=== 创建管理员账号 ===\n")
    email = input("邮箱: ").strip()
    if not email:
        print("错误: 邮箱不能为空")
        return

    username = input("用户名: ").strip()
    if not username:
        print("错误: 用户名不能为空")
        return

    password = getpass.getpass("密码 (至少6位): ")
    if len(password) < 6:
        print("错误: 密码至少6位")
        return

    confirm = getpass.getpass("确认密码: ")
    if password != confirm:
        print("错误: 两次密码不一致")
        return

    async with get_session_factory()() as db:
        existing = await db.execute(select(User).where(User.email == email))
        if existing.scalar_one_or_none():
            print(f"错误: 邮箱 {email} 已存在")
            return

        existing_name = await db.execute(select(User).where(User.username == username))
        if existing_name.scalar_one_or_none():
            print(f"错误: 用户名 {username} 已存在")
            return

        user = User(
            email=email,
            username=username,
            password_hash=hash_password(password),
            role="admin",
            is_active=True,
        )
        db.add(user)
        await db.flush()

        credit_account = CreditAccount(
            user_id=user.id,
            balance=settings.daily_free_credits,
            daily_free_allowance=settings.daily_free_credits,
            last_daily_reset=datetime.now(timezone.utc),
        )
        db.add(credit_account)
        await db.commit()

    print(f"\n✓ 管理员创建成功")
    print(f"  邮箱: {email}")
    print(f"  用户名: {username}")
    print(f"  角色: admin")


async def reset_password(email: str):
    """重置指定用户的密码"""
    from app.core.database import get_session_factory
    from app.models.user import User
    from app.core.security import hash_password

    new_password = getpass.getpass("新密码 (至少6位): ")
    if len(new_password) < 6:
        print("错误: 密码至少6位")
        return

    async with get_session_factory()() as db:
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
        if not user:
            print(f"错误: 用户 {email} 不存在")
            return

        user.password_hash = hash_password(new_password)
        await db.commit()

    print(f"✓ 用户 {email} 的密码已重置")


async def show_stats():
    """显示平台统计"""
    from app.core.database import get_session_factory
    from app.models.user import User
    from app.models.file import File
    from app.models.conversation import Conversation, Message
    from app.models.data_space import DataSpace
    from app.models.llm_model import LLMModel

    async with get_session_factory()() as db:
        users = (await db.execute(select(func.count()).select_from(User))).scalar()
        admins = (await db.execute(select(func.count()).select_from(User).where(User.role == "admin"))).scalar()
        spaces = (await db.execute(select(func.count()).select_from(DataSpace))).scalar()
        files = (await db.execute(select(func.count()).select_from(File))).scalar()
        convs = (await db.execute(select(func.count()).select_from(Conversation))).scalar()
        msgs = (await db.execute(select(func.count()).select_from(Message))).scalar()
        models = (await db.execute(select(func.count()).select_from(LLMModel).where(LLMModel.is_active == True))).scalar()

    print("=== DataMind Analyst 统计 ===\n")
    print(f"  用户: {users} (管理员: {admins})")
    print(f"  数据空间: {spaces}")
    print(f"  文件: {files}")
    print(f"  对话: {convs}")
    print(f"  消息: {msgs}")
    print(f"  活跃模型: {models}")


async def list_models():
    """列出所有模型配置"""
    from app.core.database import get_session_factory
    from app.models.llm_model import LLMModel

    async with get_session_factory()() as db:
        result = await db.execute(select(LLMModel))
        models = result.scalars().all()

    if not models:
        print("暂无模型配置。请在管理后台添加，或运行 python manage.py seed")
        return

    print("=== 模型配置 ===\n")
    print(f"  {'ID':<25} {'显示名称':<20} {'API模型名':<25} {'供应商':<12} {'状态':<8} {'倍率'}")
    print("  " + "-" * 100)
    for m in models:
        status = "✓ 启用" if m.is_active else "✗ 停用"
        print(f"  {m.id:<25} {m.display_name:<20} {m.model_name:<25} {m.provider:<12} {status:<8} {float(m.credit_multiplier)}")


async def seed():
    """初始化种子数据"""
    from app.seed import seed_models
    await seed_models()
    print("✓ 种子数据已初始化")
    await list_models()


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return

    command = sys.argv[1]

    if command == "create-admin":
        asyncio.run(create_admin())
    elif command == "reset-password":
        if len(sys.argv) < 3:
            print("用法: python manage.py reset-password EMAIL")
            return
        asyncio.run(reset_password(sys.argv[2]))
    elif command == "stats":
        asyncio.run(show_stats())
    elif command == "list-models":
        asyncio.run(list_models())
    elif command == "seed":
        asyncio.run(seed())
    else:
        print(f"未知命令: {command}")
        print(__doc__)


if __name__ == "__main__":
    main()
