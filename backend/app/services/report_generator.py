"""报告生成服务 - 将对话导出为 Markdown/PDF"""
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session_factory
from app.models.conversation import Conversation, Message
from app.models.data_space import DataSpace


async def generate_report(
    conversation_id: uuid.UUID,
    user_id: uuid.UUID,
    format: str = "markdown",
) -> dict:
    """生成对话分析报告"""
    async with get_session_factory()() as db:
        conv_result = await db.execute(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.user_id == user_id,
            )
        )
        conv = conv_result.scalar_one_or_none()
        if not conv:
            return {"error": "对话不存在"}

        msg_result = await db.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at)
        )
        messages = msg_result.scalars().all()

        space_name = "未关联数据空间"
        if conv.data_space_id:
            space_result = await db.execute(
                select(DataSpace).where(DataSpace.id == conv.data_space_id)
            )
            space = space_result.scalar_one_or_none()
            if space:
                space_name = space.name

    md_content = _build_markdown(conv, messages, space_name)

    # 文件名可能含中文，统一在路由层做 RFC 5987 编码；这里只产出原始名
    safe_title = (conv.title or "analysis").strip().replace("/", "_").replace("\\", "_")
    filename = f"report_{safe_title}_{datetime.now().strftime('%Y%m%d')}.md"

    if format == "markdown":
        return {
            "content": md_content,
            "filename": filename,
            "content_type": "text/markdown; charset=utf-8",
        }
    else:
        return {
            "content": md_content,
            "filename": filename,
            "content_type": "text/markdown; charset=utf-8",
        }


def _build_markdown(conv, messages, space_name: str) -> str:
    """构建 Markdown 报告"""
    lines = []
    lines.append(f"# 数据分析报告")
    lines.append("")
    lines.append(f"**主题**: {conv.title or '数据分析'}")
    lines.append(f"**数据空间**: {space_name}")
    lines.append(f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"**对话轮次**: {len([m for m in messages if m.role == 'user'])}")
    lines.append("")
    lines.append("---")
    lines.append("")

    for msg in messages:
        if msg.role == "user":
            lines.append(f"## 问题")
            lines.append("")
            lines.append(f"> {msg.content}")
            lines.append("")
        elif msg.role == "assistant" and msg.content:
            lines.append(f"## 分析结果")
            lines.append("")
            lines.append(msg.content)
            lines.append("")

            if msg.tool_calls and isinstance(msg.tool_calls, list):
                tool_segments = [s for s in msg.tool_calls if isinstance(s, dict) and s.get("type") == "tools"]
                if tool_segments:
                    lines.append("<details>")
                    lines.append("<summary>工具调用详情</summary>")
                    lines.append("")
                    for seg in tool_segments:
                        for event in seg.get("events", []):
                            if event.get("type") == "tool_use":
                                lines.append(f"- **{event.get('name', '?')}**: `{str(event.get('input', ''))[:100]}`")
                    lines.append("")
                    lines.append("</details>")
                    lines.append("")

            lines.append("---")
            lines.append("")

    lines.append("")
    lines.append("*本报告由 DataMind Platform 自动生成*")

    return "\n".join(lines)
