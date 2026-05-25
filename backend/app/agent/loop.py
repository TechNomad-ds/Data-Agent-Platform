"""Agent ReAct 循环 - 基于 OpenAI 标准格式的流式 Agent"""
import uuid
import json
from typing import AsyncGenerator, Any

from openai import AsyncOpenAI
from sqlalchemy import select

from app.config import settings
from app.core.database import get_session_factory
from app.models.conversation import Message
from app.models.file import File
from app.models.data_space import DataSpace, DataSpaceFile
from app.agent.tools import get_tool_definitions, execute_tool


SYSTEM_PROMPT_TEMPLATE = """你是 Data Agent，一个专业的数据分析助手。你可以帮助用户理解、查询和分析他们的数据。

当前数据空间信息：
{data_space_info}

你可以使用以下工具来完成任务：
- search_data_space: 在数据空间中搜索相关内容
- read_file: 读取文件内容
- inspect_data: 查看结构化数据的 schema 和样本
- pandas_query: 对 CSV/Excel 数据执行 pandas 查询
- execute_python: 执行 Python 代码进行数据分析

工作原则：
1. 先理解用户的问题，再决定使用哪些工具
2. 对于数据分析任务，先用 inspect_data 了解数据结构，再进行分析
3. 展示分析过程和关键发现
4. 引用数据来源，让用户知道结论基于哪些文件
5. 如果遇到错误，尝试修正并重试
"""


class AgentLoop:
    """OpenAI 标准格式的 ReAct Agent 循环"""

    def __init__(self):
        self.client = AsyncOpenAI(
            api_key=settings.llm_api_key,
            base_url=settings.llm_api_base_url,
        )
        self.max_iterations = 10

    async def _get_data_space_info(self, data_space_id: uuid.UUID | None, user_id: uuid.UUID) -> str:
        """获取数据空间的上下文信息"""
        if not data_space_id:
            return "未选择数据空间。用户可以进行通用对话。"

        async with get_session_factory()() as db:
            # 获取数据空间信息
            result = await db.execute(
                select(DataSpace).where(DataSpace.id == data_space_id, DataSpace.user_id == user_id)
            )
            space = result.scalar_one_or_none()
            if not space:
                return "数据空间不存在"

            # 获取文件列表
            file_result = await db.execute(
                select(File)
                .join(DataSpaceFile, DataSpaceFile.file_id == File.id)
                .where(DataSpaceFile.data_space_id == data_space_id)
            )
            files = file_result.scalars().all()

            file_list = "\n".join(
                f"  - {f.filename} ({f.file_type}, {f.file_size} bytes)"
                for f in files
            )

            return f"""数据空间名称: {space.name}
描述: {space.description or '无'}
文件列表:
{file_list or '  (空)'}"""

    async def _get_conversation_history(self, conversation_id: uuid.UUID) -> list[dict]:
        """获取对话历史"""
        async with get_session_factory()() as db:
            result = await db.execute(
                select(Message)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.created_at)
            )
            messages = result.scalars().all()

            history = []
            for msg in messages:
                if msg.role == "user":
                    history.append({"role": "user", "content": msg.content})
                elif msg.role == "assistant" and msg.content:
                    history.append({"role": "assistant", "content": msg.content})

            return history

    async def run(
        self,
        conversation_id: uuid.UUID,
        user_id: uuid.UUID,
        data_space_id: uuid.UUID | None,
        model_id: str,
        user_message: str,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """执行 Agent 循环，流式返回事件"""
        # 构建系统提示
        data_space_info = await self._get_data_space_info(data_space_id, user_id)
        system_prompt = SYSTEM_PROMPT_TEMPLATE.format(data_space_info=data_space_info)

        # 获取对话历史
        history = await self._get_conversation_history(conversation_id)

        # 构建消息列表
        messages = [
            {"role": "system", "content": system_prompt},
            *history[-20:],  # 保留最近20条消息
            {"role": "user", "content": user_message},
        ]

        tools = get_tool_definitions()
        total_usage = {"input_tokens": 0, "output_tokens": 0}

        for iteration in range(self.max_iterations):
            try:
                response = await self.client.chat.completions.create(
                    model=model_id,
                    messages=messages,
                    tools=tools if tools else None,
                    stream=True,
                )

                # 收集流式响应
                full_content = ""
                tool_calls_data = []
                current_tool_call = None

                async for chunk in response:
                    delta = chunk.choices[0].delta if chunk.choices else None
                    if not delta:
                        continue

                    # 文本内容
                    if delta.content:
                        full_content += delta.content
                        yield {"type": "text", "delta": delta.content}

                    # 工具调用
                    if delta.tool_calls:
                        for tc in delta.tool_calls:
                            if tc.index >= len(tool_calls_data):
                                tool_calls_data.append({
                                    "id": tc.id or "",
                                    "function": {"name": "", "arguments": ""},
                                })
                            if tc.id:
                                tool_calls_data[tc.index]["id"] = tc.id
                            if tc.function:
                                if tc.function.name:
                                    tool_calls_data[tc.index]["function"]["name"] = tc.function.name
                                if tc.function.arguments:
                                    tool_calls_data[tc.index]["function"]["arguments"] += tc.function.arguments

                    # 使用量
                    if hasattr(chunk, "usage") and chunk.usage:
                        total_usage["input_tokens"] += chunk.usage.prompt_tokens or 0
                        total_usage["output_tokens"] += chunk.usage.completion_tokens or 0

                # 如果没有工具调用，Agent 完成
                if not tool_calls_data:
                    yield {
                        "type": "done",
                        "usage": total_usage,
                        "credits_used": self._calculate_credits(total_usage),
                    }
                    return

                # 有工具调用，执行工具
                # 将助手消息加入历史
                assistant_msg = {"role": "assistant", "content": full_content or None, "tool_calls": [
                    {"id": tc["id"], "type": "function", "function": tc["function"]}
                    for tc in tool_calls_data
                ]}
                messages.append(assistant_msg)

                # 执行每个工具
                for tc in tool_calls_data:
                    tool_name = tc["function"]["name"]
                    try:
                        tool_args = json.loads(tc["function"]["arguments"])
                    except json.JSONDecodeError:
                        tool_args = {}

                    yield {
                        "type": "tool_use",
                        "name": tool_name,
                        "input": tool_args,
                        "id": tc["id"],
                    }

                    # 执行工具
                    tool_result = await execute_tool(
                        tool_name=tool_name,
                        arguments=tool_args,
                        user_id=user_id,
                        data_space_id=data_space_id,
                    )

                    # 截断过长的结果
                    result_str = str(tool_result)
                    if len(result_str) > 8000:
                        result_str = result_str[:8000] + "\n...(结果已截断)"

                    yield {
                        "type": "tool_result",
                        "name": tool_name,
                        "content": result_str[:500],  # 前端预览
                        "is_error": False,
                    }

                    # 将工具结果加入消息
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": result_str,
                    })

            except Exception as e:
                yield {"type": "error", "message": f"Agent 执行出错: {str(e)}"}
                return

        # 达到最大迭代次数
        yield {"type": "text", "delta": "\n\n[已达到最大执行步数，自动停止]"}
        yield {"type": "done", "usage": total_usage, "credits_used": self._calculate_credits(total_usage)}

    def _calculate_credits(self, usage: dict) -> int:
        """根据 token 使用量计算消耗的额度"""
        # 简单计费：每 1000 token 消耗 1 点
        total_tokens = usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
        return max(1, total_tokens // 1000)
