"""对话路由 - 创建会话、发送消息（SSE流式）"""
import uuid
import json
from collections import defaultdict
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.deps import get_current_user
from app.models.user import User
from app.models.conversation import Conversation, Message
from app.models.data_space import DataSpace
from app.schemas.chat import (
    ConversationCreate, ConversationResponse, MessageCreate,
    MessageResponse, ConversationDetailResponse,
)
from app.agent.loop import AgentLoop
from app.config import settings

router = APIRouter()

_active_streams: dict[str, int] = defaultdict(int)
_active_streams_global = 0
# 进程内回退：Redis 不可用时用它兜底（单 worker 内有效）。
# 多 worker 下中断信号走 Redis（见 _set_abort / _is_aborted），跨进程可见。
_abort_signals: dict[str, bool] = {}

_ABORT_TTL = 900  # 中断标记的 Redis TTL（秒），覆盖一次对话的最长时长即可


async def _set_abort(abort_key: str) -> None:
    """设置中断信号：优先 Redis（跨 worker），失败回退进程内 dict。"""
    try:
        from app.core.redis_client import get_redis
        redis = await get_redis()
        await redis.set(f"abort:{abort_key}", "1", ex=_ABORT_TTL)
        return
    except Exception:
        pass
    _abort_signals[abort_key] = True


async def _clear_abort(abort_key: str) -> None:
    """清除中断信号（对话开始/结束时）。Redis 与本地都清。"""
    try:
        from app.core.redis_client import get_redis
        redis = await get_redis()
        await redis.delete(f"abort:{abort_key}")
    except Exception:
        pass
    _abort_signals.pop(abort_key, None)


async def _is_aborted(abort_key: str) -> bool:
    """查询中断信号：Redis 优先，回退本地。"""
    try:
        from app.core.redis_client import get_redis
        redis = await get_redis()
        if await redis.get(f"abort:{abort_key}"):
            return True
    except Exception:
        pass
    return _abort_signals.get(abort_key, False)


_ACQUIRE_LUA = """
local current = tonumber(redis.call('GET', KEYS[1]) or '0')
local limit = tonumber(ARGV[1])
if current >= limit then
    return -1
end
current = redis.call('INCR', KEYS[1])
redis.call('EXPIRE', KEYS[1], tonumber(ARGV[2]))
return current
"""

_RELEASE_LUA = """
local current = tonumber(redis.call('GET', KEYS[1]) or '0')
if current <= 1 then
    redis.call('DEL', KEYS[1])
    return 0
end
return redis.call('DECR', KEYS[1])
"""


async def _redis_acquire(key: str, limit: int, ttl: int = 900) -> bool:
    from app.core.redis_client import get_redis

    redis = await get_redis()
    result = await redis.eval(_ACQUIRE_LUA, 1, key, limit, ttl)
    return int(result) >= 0


async def _redis_release(key: str) -> None:
    from app.core.redis_client import get_redis

    redis = await get_redis()
    await redis.eval(_RELEASE_LUA, 1, key)


async def _acquire_stream_slot(user_key: str) -> tuple[bool, str]:
    """跨 worker 的流式对话并发闸门；Redis 不可用时退回进程内限制。"""
    global _active_streams_global

    global_key = "streams:global"
    user_stream_key = f"streams:user:{user_key}"
    try:
        if not await _redis_acquire(global_key, settings.max_concurrent_streams_global):
            return False, "当前平台对话并发已满，请稍后再试"
        if not await _redis_acquire(user_stream_key, settings.max_concurrent_streams_per_user):
            await _redis_release(global_key)
            return False, "同时进行的对话太多，请等待当前对话完成后再试"
        return True, "redis"
    except Exception:
        if _active_streams_global >= settings.max_concurrent_streams_global:
            return False, "当前平台对话并发已满，请稍后再试"
        if _active_streams[user_key] >= settings.max_concurrent_streams_per_user:
            return False, "同时进行的对话太多，请等待当前对话完成后再试"
        _active_streams_global += 1
        _active_streams[user_key] += 1
        return True, "local"


async def _release_stream_slot(user_key: str, mode: str) -> None:
    global _active_streams_global

    if mode == "redis":
        try:
            await _redis_release("streams:global")
            await _redis_release(f"streams:user:{user_key}")
            return
        except Exception:
            pass

    _active_streams_global = max(0, _active_streams_global - 1)
    _active_streams[user_key] = max(0, _active_streams[user_key] - 1)


@router.post("/conversations", response_model=ConversationResponse, status_code=201)
async def create_conversation(
    data: ConversationCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """创建新对话"""
    from sqlalchemy import func as sql_func
    from app.config import settings

    # 检查对话数量上限（管理员不限）
    if current_user.role != "admin":
        conv_count = await db.execute(
            select(sql_func.count()).select_from(Conversation).where(Conversation.user_id == current_user.id)
        )
        if (conv_count.scalar() or 0) >= settings.max_conversations_per_user:
            raise HTTPException(status_code=400, detail=f"对话数量已达上限({settings.max_conversations_per_user}个)，请删除一些旧对话")

    # 验证数据空间归属
    if data.data_space_id:
        result = await db.execute(
            select(DataSpace).where(
                DataSpace.id == data.data_space_id, DataSpace.user_id == current_user.id
            )
        )
        if not result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="数据空间不存在")

    conversation = Conversation(
        user_id=current_user.id,
        data_space_id=data.data_space_id,
        model_id=data.model_id,
        title=data.title,
    )
    db.add(conversation)
    await db.flush()
    return conversation


@router.get("/conversations", response_model=list[ConversationResponse])
async def list_conversations(
    limit: int = 50,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取当前用户的对话列表（分页）"""
    result = await db.execute(
        select(Conversation)
        .where(Conversation.user_id == current_user.id)
        .order_by(Conversation.updated_at.desc())
        .limit(min(limit, 100))
        .offset(offset)
    )
    return result.scalars().all()


@router.get("/conversations/{conv_id}", response_model=ConversationDetailResponse)
async def get_conversation(
    conv_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取对话详情（含消息历史）"""
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == conv_id, Conversation.user_id == current_user.id
        )
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="对话不存在")

    msg_result = await db.execute(
        select(Message).where(Message.conversation_id == conv_id).order_by(Message.created_at)
    )
    messages = msg_result.scalars().all()

    return ConversationDetailResponse(
        id=conv.id, data_space_id=conv.data_space_id, title=conv.title,
        model_id=conv.model_id, created_at=conv.created_at, updated_at=conv.updated_at,
        messages=[MessageResponse.model_validate(m) for m in messages],
    )


@router.patch("/conversations/{conv_id}", response_model=ConversationResponse)
async def rename_conversation(
    conv_id: uuid.UUID,
    data: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """重命名对话"""
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == conv_id, Conversation.user_id == current_user.id
        )
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="对话不存在")

    if "title" in data:
        conv.title = data["title"][:500]
    return conv


@router.delete("/conversations/{conv_id}", status_code=204)
async def delete_conversation(
    conv_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """删除对话"""
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == conv_id, Conversation.user_id == current_user.id
        )
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="对话不存在")
    await db.delete(conv)


@router.post("/conversations/{conv_id}/abort")
async def abort_conversation(
    conv_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
):
    """中断正在进行的 Agent 回复"""
    key = f"{current_user.id}:{conv_id}"
    await _set_abort(key)
    return {"message": "已发送中断信号"}


@router.post("/conversations/{conv_id}/messages")
async def send_message(
    conv_id: uuid.UUID,
    data: MessageCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """发送消息并获取 Agent 流式回复（SSE）"""
    # 限制每用户并发流数
    user_key = str(current_user.id)
    acquired, limiter_mode_or_message = await _acquire_stream_slot(user_key)
    if not acquired:
        raise HTTPException(status_code=429, detail=limiter_mode_or_message)
    limiter_mode = limiter_mode_or_message

    try:
        # 验证对话归属
        result = await db.execute(
            select(Conversation).where(
                Conversation.id == conv_id, Conversation.user_id == current_user.id
            )
        )
        conv = result.scalar_one_or_none()
        if not conv:
            raise HTTPException(status_code=404, detail="对话不存在")

        # 检查是否是对话的第一条消息
        from sqlalchemy import func as sql_func
        msg_count_result = await db.execute(
            select(sql_func.count()).select_from(Message).where(Message.conversation_id == conv_id)
        )
        is_first_message = (msg_count_result.scalar() or 0) == 0

        # 保存用户消息
        user_message = Message(
            conversation_id=conv_id,
            role="user",
            content=data.content,
        )
        db.add(user_message)
        await db.flush()

        # 如果对话没有标题，用算法从用户消息提取标题
        needs_title = not conv.title
        if needs_title:
            conv.title = _extract_title(data.content)

        # 如果前端传了 model_id，更新对话使用的模型
        if data.model_id and data.model_id != conv.model_id:
            conv.model_id = data.model_id

        await db.commit()

        # 提前捕获需要在生成器中使用的值（db session 关闭后无法访问 ORM 对象属性）
        conv_data_space_id = conv.data_space_id
        conv_model_id = conv.model_id
        message_content = data.content
    except Exception:
        await _release_stream_slot(user_key, limiter_mode)
        raise

    # 流式返回 Agent 回复
    async def event_stream() -> AsyncGenerator[str, None]:
        from app.core.database import get_session_factory
        import time as _time
        abort_key = f"{current_user.id}:{conv_id}"
        await _clear_abort(abort_key)

        # 中断信号跨 worker 走 Redis，但 abort_check 在热循环里被同步高频调用，
        # 不能每次都 await Redis。折中：本地标志 + 节流轮询（每 ~1.5s 查一次 Redis），
        # 命中后翻转本地标志，热循环读本地标志即可。
        _abort_state = {"flag": False, "last_poll": 0.0}

        async def _refresh_abort() -> None:
            now = _time.monotonic()
            if _abort_state["flag"]:
                return
            if now - _abort_state["last_poll"] < 1.5:
                return
            _abort_state["last_poll"] = now
            if await _is_aborted(abort_key):
                _abort_state["flag"] = True

        agent = AgentLoop(abort_check=lambda: _abort_state["flag"])
        full_content = ""
        last_event: dict = {}
        segments: list = []
        turn_canonical: list = []

        try:
            try:
                async for event in agent.run(
                    conversation_id=conv_id,
                    user_id=current_user.id,
                    data_space_id=conv_data_space_id,
                    model_id=conv_model_id,
                    user_message=message_content,
                    is_admin=current_user.role == "admin",
                ):
                    await _refresh_abort()
                    last_event = event
                    if event["type"] == "text":
                        full_content += event["delta"]
                        if segments and segments[-1]["type"] == "text":
                            segments[-1]["content"] += event["delta"]
                        else:
                            segments.append({"type": "text", "content": event["delta"]})
                    elif event["type"] == "thinking":
                        if segments and segments[-1]["type"] == "thinking":
                            segments[-1]["content"] += event.get("content", "")
                        else:
                            segments.append({"type": "thinking", "content": event.get("content", "")})
                    elif event["type"] in ("tool_use", "tool_result"):
                        if segments and segments[-1]["type"] == "tools":
                            segments[-1]["events"].append(event)
                        else:
                            segments.append({"type": "tools", "events": [event]})
                    elif event["type"] == "done":
                        # 本回合完整 canonical 子序列（含工具 I/O），用于历史回放
                        turn_canonical = event.get("canonical", []) or []
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            except Exception as e:
                import traceback
                error_detail = str(e)
                traceback.print_exc()
                yield f"data: {json.dumps({'type': 'error', 'message': f'Agent 执行异常: {error_detail}'}, ensure_ascii=False)}\n\n"

            # 如果是第一条消息且 agent 没有生成任何回答，删除整个对话记录
            save_content = full_content
            if is_first_message and not save_content and not segments:
                try:
                    async with get_session_factory()() as cleanup_db:
                        from sqlalchemy import delete as sql_delete
                        await cleanup_db.execute(
                            sql_delete(Message).where(Message.conversation_id == conv_id)
                        )
                        await cleanup_db.execute(
                            sql_delete(Conversation).where(Conversation.id == conv_id)
                        )
                        await cleanup_db.commit()
                except Exception:
                    import traceback
                    traceback.print_exc()
                yield f"data: {json.dumps({'type': 'conversation_deleted', 'conversation_id': str(conv_id)}, ensure_ascii=False)}\n\n"
                yield "data: [DONE]\n\n"
                return

            # 保存助手消息：无论是正常完成还是异常中断，只要有内容就保存
            saved_message_id = None
            if save_content or segments:
                # 限制单回合 canonical 体积，防长任务把单个 JSONB 行撑大
                if turn_canonical:
                    from app.agent import context as _ctx
                    turn_canonical = _ctx.cap_canonical(
                        turn_canonical, settings.canonical_max_total_chars
                    )
                try:
                    async with get_session_factory()() as save_db:
                        assistant_message = Message(
                            conversation_id=conv_id,
                            role="assistant",
                            content=save_content or None,
                            tool_calls=segments if len(segments) > 1 else None,
                            # 完整 canonical 子序列（含工具 I/O），供后续轮次回放上下文
                            tool_results={"canonical": turn_canonical} if turn_canonical else None,
                            token_usage=last_event.get("usage") if last_event.get("type") == "done" else None,
                            credits_used=last_event.get("credits_used") if last_event.get("type") == "done" else None,
                        )
                        save_db.add(assistant_message)
                        await save_db.flush()
                        saved_message_id = str(assistant_message.id)
                        await save_db.commit()
                except Exception as save_err:
                    import traceback
                    traceback.print_exc()
                    yield f"data: {json.dumps({'type': 'error', 'message': f'消息保存失败: {str(save_err)}'}, ensure_ascii=False)}\n\n"

            # 发送 saved 事件通知前端真实消息 ID（用于反馈等功能）
            if saved_message_id:
                yield f"data: {json.dumps({'type': 'saved', 'message_id': saved_message_id}, ensure_ascii=False)}\n\n"

            yield "data: [DONE]\n\n"
        finally:
            await _release_stream_slot(user_key, limiter_mode)
            await _clear_abort(abort_key)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


import re as _re
import jieba

_FILLER_PREFIXES = (
    "请帮我", "帮我", "请你帮我", "请你", "请",
    "我想要", "我想", "我要", "我需要", "我希望",
    "能不能帮我", "能不能", "可不可以", "可以帮我", "可以",
    "能否帮我", "能否", "麻烦你帮我", "麻烦你", "麻烦",
    "你能帮我", "你能", "你可以", "帮忙", "希望你", "想请你",
)

_TRAILING_PARTICLES = {"吗", "呢", "吧", "啊", "呀", "哈", "嘛", "么", "？", "?"}

_DROP_WORDS = {"一下", "一些", "一点", "到底", "究竟", "的话"}

def _extract_title(text: str, max_len: int = 25) -> str:
    """用 jieba 分词做语句压缩，提取简短标题。"""
    t = text.strip()
    if not t:
        return "新对话"

    # 取第一个句子
    first = _re.split(r'[。！\!\n;；]', t, maxsplit=1)[0].strip()
    if not first:
        first = t
    # 问号单独处理：保留问句内容，只去掉问号本身
    first = first.rstrip("？?")

    # 去口语前缀（长匹配优先，已按长度排序）
    for prefix in _FILLER_PREFIXES:
        if first.startswith(prefix):
            first = first[len(prefix):].lstrip("，,：: ")
            break

    # jieba 分词
    words = list(jieba.cut(first))

    # 去掉尾部语气词
    while words and words[-1].strip() in _TRAILING_PARTICLES:
        words.pop()

    # 过滤中间的冗余词（"一下"、"到底"等）
    words = [w for w in words if w.strip() not in _DROP_WORDS]

    title = "".join(words).strip()
    if not title:
        return text[:max_len] if text else "新对话"

    if len(title) <= max_len:
        return title

    # 在逗号/顿号处截断
    for sep in ("，", "、", ","):
        idx = title.rfind(sep, 0, max_len)
        if idx > 4:
            return title[:idx]

    # 按分词边界截断
    result = ""
    for w in jieba.cut(title):
        if len(result) + len(w) > max_len:
            break
        result += w

    return result or title[:max_len]
