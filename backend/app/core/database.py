"""数据库连接与会话管理"""
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


class Base(DeclarativeBase):
    pass


def _create_engine():
    return create_async_engine(
        settings.database_url,
        echo=False,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_pre_ping=True,
        pool_recycle=3600,
    )


def _create_session_factory(eng=None):
    if eng is None:
        eng = _create_engine()
    return async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)


# 延迟初始化：仅在实际使用时创建
_engine = None
_session_factory = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = _create_engine()
    return _engine


def get_session_factory():
    global _session_factory
    if _session_factory is None:
        _session_factory = _create_session_factory(get_engine())
    return _session_factory


# 兼容旧引用
@property
def engine():
    return get_engine()


async_session_factory = None


def _get_async_session_factory():
    return get_session_factory()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """获取数据库会话的依赖注入"""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
