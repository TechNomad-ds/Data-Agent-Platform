"""Agent 记忆服务 - 存储和召回"""
import uuid
from typing import List, Dict, Any, Optional

from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session_factory
from app.models.memory import AgentMemory


async def store_memory(
    user_id: uuid.UUID,
    content: str,
    scope: str = "session",
    kind: str = "fact",
    data_space_id: Optional[uuid.UUID] = None,
    session_id: Optional[str] = None,
    importance: int = 5,
) -> str:
    """存储一条记忆"""
    async with get_session_factory()() as db:
        memory = AgentMemory(
            user_id=user_id,
            data_space_id=data_space_id,
            session_id=session_id,
            scope=scope,
            kind=kind,
            content=content,
            importance=importance,
        )
        db.add(memory)
        await db.commit()
        return str(memory.id)


async def recall(
    user_id: uuid.UUID,
    query: str,
    data_space_id: Optional[uuid.UUID] = None,
    session_id: Optional[str] = None,
    limit: int = 8,
) -> List[Dict[str, Any]]:
    """召回相关记忆（按 scope 分层）"""
    async with get_session_factory()() as db:
        memories = []

        if session_id:
            result = await db.execute(
                select(AgentMemory)
                .where(
                    AgentMemory.user_id == user_id,
                    AgentMemory.scope == "session",
                    AgentMemory.session_id == session_id,
                )
                .order_by(desc(AgentMemory.created_at))
                .limit(3)
            )
            memories.extend(result.scalars().all())

        if data_space_id:
            result = await db.execute(
                select(AgentMemory)
                .where(
                    AgentMemory.user_id == user_id,
                    AgentMemory.scope == "space",
                    AgentMemory.data_space_id == data_space_id,
                )
                .order_by(desc(AgentMemory.importance), desc(AgentMemory.created_at))
                .limit(3)
            )
            memories.extend(result.scalars().all())

        result = await db.execute(
            select(AgentMemory)
            .where(
                AgentMemory.user_id == user_id,
                AgentMemory.scope == "global",
            )
            .order_by(desc(AgentMemory.importance), desc(AgentMemory.created_at))
            .limit(2)
        )
        memories.extend(result.scalars().all())

    seen_ids = set()
    unique = []
    for m in memories:
        if m.id not in seen_ids:
            seen_ids.add(m.id)
            unique.append({
                "id": str(m.id),
                "scope": m.scope,
                "kind": m.kind,
                "content": m.content,
                "importance": m.importance,
            })

    return unique[:limit]


async def forget(memory_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    """删除一条记忆"""
    async with get_session_factory()() as db:
        result = await db.execute(
            select(AgentMemory).where(
                AgentMemory.id == memory_id,
                AgentMemory.user_id == user_id,
            )
        )
        memory = result.scalar_one_or_none()
        if memory:
            await db.delete(memory)
            await db.commit()
            return True
        return False
