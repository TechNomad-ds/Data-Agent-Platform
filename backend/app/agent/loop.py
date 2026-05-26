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
from app.models.llm_model import LLMModel
from app.models.credit import CreditAccount, CreditTransaction
from app.agent.tools import get_tool_definitions, execute_tool


SYSTEM_PROMPT_TEMPLATE = """你是 Data Agent，一个专业的数据分析助手。你帮助普通用户理解、查询和分析他们的数据。用户可能不懂技术，请用通俗易懂的语言解释分析结果。

当前数据空间信息：
{data_space_info}

{memory_context}

你可以使用以下工具：
- search_data_space: 语义搜索数据空间中的内容
- read_file: 读取文件内容
- inspect_data: 查看数据结构和跨文件 join 关系（不传 filename 则检查所有文件）
- pandas_query: 对数据执行 pandas 查询
- sqlite_query: 用 SQL 查询数据（表名=文件名去扩展名小写）
- execute_python: 执行 Python 代码分析数据
- generate_chart: 生成可视化图表（bar/line/pie/scatter/heatmap）
- save_memory: 保存重要发现到记忆系统

工作原则：
1. 先用 inspect_data（不传文件名）了解整体数据结构和 join 关系
2. 对于简单查询用 pandas_query，复杂多表查询用 sqlite_query
3. 主动生成图表帮助用户理解数据（用 generate_chart）
4. 用通俗语言解释发现，避免技术术语
5. 如果发现重要模式或用户偏好，用 save_memory 记住
6. 引用数据来源，让用户知道结论基于哪些文件
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
            result = await db.execute(
                select(DataSpace).where(DataSpace.id == data_space_id, DataSpace.user_id == user_id)
            )
            space = result.scalar_one_or_none()
            if not space:
                return "数据空间不存在"

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

    async def _resolve_model(self, model_id: str) -> tuple[str, float]:
        """从数据库查找模型名称和倍率"""
        async with get_session_factory()() as db:
            result = await db.execute(select(LLMModel).where(LLMModel.id == model_id))
            model = result.scalar_one_or_none()
            if model and model.model_name:
                return model.model_name, float(model.credit_multiplier)
        return settings.llm_default_model, 1.0

    async def _check_balance(self, user_id: uuid.UUID) -> int:
        """检查用户余额，返回当前余额"""
        async with get_session_factory()() as db:
            result = await db.execute(
                select(CreditAccount).where(CreditAccount.user_id == user_id)
            )
            account = result.scalar_one_or_none()
            return account.balance if account else 0

    async def _deduct_credits(self, user_id: uuid.UUID, credits: int, model_name: str) -> None:
        """从用户账户扣减额度"""
        async with get_session_factory()() as db:
            result = await db.execute(
                select(CreditAccount).where(CreditAccount.user_id == user_id)
            )
            account = result.scalar_one_or_none()
            if not account:
                return

            account.balance = max(0, account.balance - credits)
            transaction = CreditTransaction(
                user_id=user_id,
                amount=-credits,
                balance_after=account.balance,
                transaction_type="usage",
                description=f"对话消耗 (模型: {model_name})",
            )
            db.add(transaction)
            await db.commit()

    async def run(
        self,
        conversation_id: uuid.UUID,
        user_id: uuid.UUID,
        data_space_id: uuid.UUID | None,
        model_id: str,
        user_message: str,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """执行 Agent 循环，流式返回事件"""
        # 检查余额
        balance = await self._check_balance(user_id)
        if balance <= 0:
            yield {"type": "error", "message": "额度不足，请充值或等待每日免费额度发放"}
            return

        # 解析实际模型名称和倍率
        actual_model_name, credit_multiplier = await self._resolve_model(model_id)

        # 构建系统提示
        data_space_info = await self._get_data_space_info(data_space_id, user_id)

        # 召回相关记忆
        memory_context = ""
        try:
            from app.services.memory import recall
            memories = await recall(user_id, user_message, data_space_id=data_space_id)
            if memories:
                memory_lines = [f"- [{m['scope']}/{m['kind']}] {m['content']}" for m in memories]
                memory_context = "相关记忆：\n" + "\n".join(memory_lines)
        except Exception:
            pass

        system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
            data_space_info=data_space_info,
            memory_context=memory_context,
        )

        # 获取对话历史
        history = await self._get_conversation_history(conversation_id)

        # 构建消息列表
        messages = [
            {"role": "system", "content": system_prompt},
            *history[-20:],
            {"role": "user", "content": user_message},
        ]

        tools = get_tool_definitions()
        total_usage = {"input_tokens": 0, "output_tokens": 0}
        tool_calls_log = []

        yield {"type": "thinking", "content": "正在分析问题..."}

        for iteration in range(self.max_iterations):
            # 检查是否超过单次最大消耗
            current_credits = self._calculate_credits(total_usage, credit_multiplier)
            if current_credits >= settings.max_credits_per_run:
                yield {"type": "text", "delta": "\n\n[已达到本次最大额度消耗上限，自动停止]"}
                break

            try:
                response = await self.client.chat.completions.create(
                    model=actual_model_name,
                    messages=messages,
                    tools=tools if tools else None,
                    stream=True,
                )

                full_content = ""
                tool_calls_data = []

                async for chunk in response:
                    delta = chunk.choices[0].delta if chunk.choices else None
                    if not delta:
                        continue

                    if delta.content:
                        full_content += delta.content
                        yield {"type": "text", "delta": delta.content}

                    if delta.tool_calls:
                        for tc in delta.tool_calls:
                            while tc.index >= len(tool_calls_data):
                                tool_calls_data.append({
                                    "id": "",
                                    "function": {"name": "", "arguments": ""},
                                })
                            if tc.id:
                                tool_calls_data[tc.index]["id"] = tc.id
                            if tc.function:
                                if tc.function.name:
                                    tool_calls_data[tc.index]["function"]["name"] = tc.function.name
                                if tc.function.arguments:
                                    tool_calls_data[tc.index]["function"]["arguments"] += tc.function.arguments

                    if hasattr(chunk, "usage") and chunk.usage:
                        total_usage["input_tokens"] += chunk.usage.prompt_tokens or 0
                        total_usage["output_tokens"] += chunk.usage.completion_tokens or 0

                # 如果没有工具调用，Agent 完成
                if not tool_calls_data:
                    if total_usage["input_tokens"] == 0:
                        total_usage = self._estimate_tokens(messages, full_content)
                    credits_used = self._calculate_credits(total_usage, credit_multiplier)
                    credits_used = max(1, credits_used)
                    await self._deduct_credits(user_id, credits_used, actual_model_name)
                    yield {
                        "type": "done",
                        "usage": total_usage,
                        "credits_used": credits_used,
                        "tool_calls_log": tool_calls_log,
                    }
                    return

                # 有工具调用，执行工具
                assistant_msg = {"role": "assistant", "content": full_content or None, "tool_calls": [
                    {"id": tc["id"], "type": "function", "function": tc["function"]}
                    for tc in tool_calls_data
                ]}
                messages.append(assistant_msg)

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

                    tool_result = await execute_tool(
                        tool_name=tool_name,
                        arguments=tool_args,
                        user_id=user_id,
                        data_space_id=data_space_id,
                    )

                    result_str = str(tool_result)
                    if len(result_str) > 8000:
                        result_str = result_str[:8000] + "\n...(结果已截断)"

                    tool_calls_log.append({
                        "name": tool_name,
                        "input": tool_args,
                        "output_preview": result_str[:200],
                    })

                    yield {
                        "type": "tool_result",
                        "name": tool_name,
                        "content": result_str[:500],
                        "is_error": False,
                    }

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": result_str,
                    })

            except Exception as e:
                yield {"type": "error", "message": f"Agent 执行出错: {str(e)}"}
                return

        # 达到最大迭代次数
        if total_usage["input_tokens"] == 0:
            total_usage = self._estimate_tokens(messages, "")
        credits_used = self._calculate_credits(total_usage, credit_multiplier)
        credits_used = max(1, credits_used)
        await self._deduct_credits(user_id, credits_used, actual_model_name)
        yield {"type": "text", "delta": "\n\n[已达到最大执行步数，自动停止]"}
        yield {"type": "done", "usage": total_usage, "credits_used": credits_used, "tool_calls_log": tool_calls_log}

    def _calculate_credits(self, usage: dict, multiplier: float = 1.0) -> int:
        """根据 token 使用量和模型倍率计算消耗的额度"""
        input_tokens = usage.get("input_tokens", 0)
        output_tokens = usage.get("output_tokens", 0)
        total_tokens = input_tokens + output_tokens
        base_credits = total_tokens // 1000
        return max(1, int(base_credits * multiplier))

    @staticmethod
    def _estimate_tokens(messages: list[dict], output: str) -> dict:
        """粗略估算 token 数（中文约 2 字符/token，英文约 4 字符/token）"""
        input_chars = sum(len(str(m.get("content", ""))) for m in messages)
        output_chars = len(output)
        return {
            "input_tokens": max(input_chars // 2, 100),
            "output_tokens": max(output_chars // 2, 10),
        }

