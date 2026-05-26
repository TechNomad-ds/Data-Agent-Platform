"""Agent ReAct 循环 - 基于 Anthropic SDK 的流式 Agent
融合 KDD-CUP 的 schema 预注入 + 重试逻辑 + DataMind 的能力"""
import uuid
import json
from typing import AsyncGenerator, Any
from pathlib import Path

from anthropic import AsyncAnthropic
from sqlalchemy import select

from app.config import settings
from app.core.database import get_session_factory
from app.models.conversation import Message
from app.models.file import File
from app.models.data_space import DataSpace, DataSpaceFile
from app.models.credit import CreditAccount, CreditTransaction
from app.agent.tools import get_tool_definitions, execute_tool


SYSTEM_PROMPT_TEMPLATE = """你是 Data Agent，一个专业的数据分析助手。你帮助用户理解、查询和分析他们的数据。用通俗易懂的语言解释分析结果。

{schema_context}

{knowledge_context}

{memory_context}

## 可用工具

- search_data_space: 混合语义搜索（BM25 + 向量融合）
- read_file: 读取文件内容
- inspect_data: 查看数据结构和跨文件 join 关系
- pandas_query: 对数据执行 pandas 查询
- sqlite_query: 用 SQL 查询数据（表名=文件名去扩展名小写）
- execute_python: 执行 Python 代码分析数据
- generate_chart: 生成可视化图表
- save_memory: 保存重要发现到记忆系统
- graph_search: 在知识图谱中搜索实体
- graph_traverse: 从实体出发遍历关系路径
- nl2sql: 用自然语言直接生成并执行 SQL 查询

## 数据分析策略

1. 数据结构已在上方预注入，无需再调用 inspect_data（除非需要更详细信息）
2. 对于简单查询用 pandas_query，复杂多表查询用 sqlite_query 或 nl2sql
3. 如果有知识图谱数据，用 graph_search 探索实体关系
4. 主动生成图表帮助用户理解数据
5. 用通俗语言解释发现，引用数据来源
6. 如果发现重要模式或用户偏好，用 save_memory 记住"""


class AgentLoop:
    """Anthropic SDK 驱动的 ReAct Agent 循环"""

    def __init__(self):
        self.client = AsyncAnthropic(api_key=settings.anthropic_api_key)
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

    async def _build_schema_context(self, data_space_id: uuid.UUID | None, user_id: uuid.UUID) -> str:
        """预注入 schema 信息（来自 KDD-CUP 策略，省去 agent 调用 inspect_data 的一轮）"""
        if not data_space_id:
            return ""

        try:
            from app.agent.tools import _get_space_files, _load_df
            import pandas as pd

            files = await _get_space_files(user_id, data_space_id)
            tabular = [f for f in files if f.file_type in ("csv", "xlsx", "xls", "json", "jsonl", "parquet")]
            if not tabular:
                return ""

            lines = ["## 数据结构概览（自动预注入）\n"]
            all_columns: dict[str, dict[str, set]] = {}

            for f in tabular[:10]:
                fp = Path(settings.storage_root) / f.storage_path
                if not fp.exists():
                    continue
                try:
                    df = _load_df(fp, f.file_type)
                    col_info = []
                    for col in df.columns:
                        non_null = int(df[col].notna().sum())
                        unique = int(df[col].nunique())
                        dtype = str(df[col].dtype)
                        samples = df[col].dropna().unique()[:5].tolist()
                        samples_str = ", ".join(str(s)[:20] for s in samples)
                        col_info.append(f"    - {col} ({dtype}) unique={unique} ex=[{samples_str}]")

                        if col not in all_columns:
                            all_columns[col] = {}
                        all_columns[col][f.filename] = set(df[col].dropna().astype(str).head(500).tolist())

                    lines.append(f"### {f.filename}  rows={len(df)}  cols={len(df.columns)}")
                    lines.extend(col_info)
                    lines.append("")
                except Exception:
                    continue

            joins = self._detect_joins_for_schema(all_columns)
            if joins:
                lines.append("### 潜在 JOIN 关系")
                lines.extend(joins)

            return "\n".join(lines)
        except Exception:
            return ""

    def _detect_joins_for_schema(self, all_columns: dict[str, dict[str, set]]) -> list[str]:
        """增强的 join 检测（来自 KDD-CUP）"""
        suggestions = []
        col_names = list(all_columns.keys())

        for col_name, file_vals in all_columns.items():
            if len(file_vals) < 2:
                continue
            files = list(file_vals.keys())
            for i in range(len(files)):
                for j in range(i + 1, len(files)):
                    vals_a, vals_b = file_vals[files[i]], file_vals[files[j]]
                    if not vals_a or not vals_b:
                        continue
                    intersection = vals_a & vals_b
                    union = vals_a | vals_b
                    jaccard = len(intersection) / len(union) if union else 0
                    if jaccard > 0.05 and len(intersection) > 1:
                        tags = ["name_match"]
                        if self._is_id_like(col_name):
                            tags.append("id_like")
                        suggestions.append(
                            f"  {files[i]}:{col_name} <-> {files[j]}:{col_name}  [{', '.join(tags)}]  overlap={jaccard:.2f}"
                        )

        for col_a in col_names:
            if not self._is_id_like(col_a):
                continue
            base_a = col_a.lower().replace("_id", "").replace("id", "").strip("_")
            for col_b in col_names:
                if col_a == col_b:
                    continue
                base_b = col_b.lower().replace("_id", "").replace("id", "").strip("_")
                if base_a and base_a == base_b and col_a in all_columns and col_b in all_columns:
                    for fa in all_columns[col_a]:
                        for fb in all_columns[col_b]:
                            if fa != fb:
                                suggestions.append(f"  {fa}:{col_a} <-> {fb}:{col_b}  [id_pattern]")

        return suggestions[:15]

    @staticmethod
    def _is_id_like(name: str) -> bool:
        n = name.lower()
        return n.endswith("_id") or n == "id" or (n.endswith("id") and len(n) > 2 and n[-3].isalpha())

    async def _get_knowledge_context(self, data_space_id: uuid.UUID | None, user_id: uuid.UUID) -> str:
        """如果数据空间中有 knowledge.md，自动注入"""
        if not data_space_id:
            return ""
        try:
            from app.agent.tools import _get_file_path
            for name in ("knowledge.md", "Knowledge.md", "KNOWLEDGE.md"):
                path = await _get_file_path(name, user_id, data_space_id)
                if path and path.exists():
                    content = path.read_text(encoding="utf-8", errors="ignore")
                    if content.strip():
                        return f"## 领域知识（来自 {name}）\n\n{content[:8000]}"
        except Exception:
            pass
        return ""

    async def _get_conversation_history(self, conversation_id: uuid.UUID) -> list[dict]:
        """获取对话历史，转为 Anthropic 格式"""
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

    async def _check_balance(self, user_id: uuid.UUID) -> int:
        async with get_session_factory()() as db:
            result = await db.execute(
                select(CreditAccount).where(CreditAccount.user_id == user_id)
            )
            account = result.scalar_one_or_none()
            return account.balance if account else 0

    async def _deduct_credits(self, user_id: uuid.UUID, credits: int, model_name: str) -> None:
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

    def _tools_to_anthropic_format(self) -> list[dict]:
        """将工具定义转为 Anthropic 格式"""
        openai_tools = get_tool_definitions()
        anthropic_tools = []
        for t in openai_tools:
            func = t["function"]
            anthropic_tools.append({
                "name": func["name"],
                "description": func["description"],
                "input_schema": func["parameters"],
            })
        return anthropic_tools

    async def run(
        self,
        conversation_id: uuid.UUID,
        user_id: uuid.UUID,
        data_space_id: uuid.UUID | None,
        model_id: str,
        user_message: str,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """执行 Agent 循环，流式返回事件"""
        balance = await self._check_balance(user_id)
        if balance <= 0:
            yield {"type": "error", "message": "额度不足，请充值或等待每日免费额度发放"}
            return

        model_name = settings.anthropic_model
        credit_multiplier = 1.0

        # 构建系统提示（含 schema 预注入 + knowledge.md + 记忆）
        schema_context = await self._build_schema_context(data_space_id, user_id)
        knowledge_context = await self._get_knowledge_context(data_space_id, user_id)

        memory_context = ""
        try:
            from app.services.memory import recall
            memories = await recall(user_id, user_message, data_space_id=data_space_id)
            if memories:
                memory_lines = [f"- [{m['scope']}/{m['kind']}] {m['content']}" for m in memories]
                memory_context = "## 相关记忆\n" + "\n".join(memory_lines)
        except Exception:
            pass

        system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
            schema_context=schema_context,
            knowledge_context=knowledge_context,
            memory_context=memory_context,
        )

        # 构建 system 块（支持 prompt caching）
        system_blocks = []
        if settings.enable_prompt_caching:
            system_blocks = [
                {"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}
            ]
        else:
            system_blocks = system_prompt

        history = await self._get_conversation_history(conversation_id)
        messages = [*history[-20:], {"role": "user", "content": user_message}]

        tools = self._tools_to_anthropic_format()
        total_usage = {"input_tokens": 0, "output_tokens": 0}
        tool_calls_log = []
        consecutive_errors = 0

        yield {"type": "thinking", "content": "正在分析问题..."}

        for iteration in range(self.max_iterations):
            current_credits = self._calculate_credits(total_usage, credit_multiplier)
            if current_credits >= settings.max_credits_per_run:
                yield {"type": "text", "delta": "\n\n[已达到本次最大额度消耗上限，自动停止]"}
                break

            try:
                response_stream = self.client.messages.stream(
                    model=model_name,
                    max_tokens=settings.anthropic_max_tokens,
                    system=system_blocks,
                    messages=messages,
                    tools=tools,
                )

                full_text = ""
                tool_uses = []

                async with response_stream as stream:
                    async for event in stream:
                        if event.type == "content_block_start":
                            if event.content_block.type == "tool_use":
                                tool_uses.append({
                                    "id": event.content_block.id,
                                    "name": event.content_block.name,
                                    "input_json": "",
                                })
                        elif event.type == "content_block_delta":
                            if event.delta.type == "text_delta":
                                full_text += event.delta.text
                                yield {"type": "text", "delta": event.delta.text}
                            elif event.delta.type == "input_json_delta":
                                if tool_uses:
                                    tool_uses[-1]["input_json"] += event.delta.partial_json

                    final_message = await stream.get_final_message()
                    total_usage["input_tokens"] += final_message.usage.input_tokens
                    total_usage["output_tokens"] += final_message.usage.output_tokens

                # 没有工具调用 → Agent 完成
                if not tool_uses:
                    credits_used = max(1, self._calculate_credits(total_usage, credit_multiplier))
                    await self._deduct_credits(user_id, credits_used, model_name)
                    yield {
                        "type": "done",
                        "usage": total_usage,
                        "credits_used": credits_used,
                        "tool_calls_log": tool_calls_log,
                    }
                    return

                # 构建 assistant 消息（含文本 + tool_use blocks）
                assistant_content = []
                if full_text:
                    assistant_content.append({"type": "text", "text": full_text})
                for tu in tool_uses:
                    try:
                        input_data = json.loads(tu["input_json"]) if tu["input_json"] else {}
                    except json.JSONDecodeError:
                        input_data = {}
                    assistant_content.append({
                        "type": "tool_use",
                        "id": tu["id"],
                        "name": tu["name"],
                        "input": input_data,
                    })

                messages.append({"role": "assistant", "content": assistant_content})

                # 执行工具并收集结果
                tool_results = []
                for tu in tool_uses:
                    try:
                        tool_args = json.loads(tu["input_json"]) if tu["input_json"] else {}
                    except json.JSONDecodeError:
                        tool_args = {}

                    yield {
                        "type": "tool_use",
                        "name": tu["name"],
                        "input": tool_args,
                        "id": tu["id"],
                    }

                    tool_result = await execute_tool(
                        tool_name=tu["name"],
                        arguments=tool_args,
                        user_id=user_id,
                        data_space_id=data_space_id,
                    )

                    result_str = str(tool_result)
                    is_error = result_str.startswith("工具执行错误") or result_str.startswith("SQL 错误")

                    if is_error:
                        consecutive_errors += 1
                    else:
                        consecutive_errors = 0

                    if len(result_str) > 8000:
                        result_str = result_str[:8000] + "\n...(结果已截断)"

                    tool_calls_log.append({
                        "name": tu["name"],
                        "input": tool_args,
                        "output_preview": result_str[:200],
                    })

                    yield {
                        "type": "tool_result",
                        "name": tu["name"],
                        "content": result_str[:500],
                        "is_error": is_error,
                    }

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tu["id"],
                        "content": result_str,
                        "is_error": is_error,
                    })

                messages.append({"role": "user", "content": tool_results})

                # 重试逻辑：连续失败时注入提示（来自 KDD-CUP）
                if consecutive_errors >= 2:
                    messages.append({
                        "role": "user",
                        "content": "提示：已连续多次失败，请换一种方法尝试。减少探索步骤，直接用最简单的方式解决问题。",
                    })
                    consecutive_errors = 0

            except Exception as e:
                yield {"type": "error", "message": f"Agent 执行出错: {str(e)}"}
                return

        # 达到最大迭代次数
        credits_used = max(1, self._calculate_credits(total_usage, credit_multiplier))
        await self._deduct_credits(user_id, credits_used, model_name)
        yield {"type": "text", "delta": "\n\n[已达到最大执行步数，自动停止]"}
        yield {"type": "done", "usage": total_usage, "credits_used": credits_used, "tool_calls_log": tool_calls_log}

    def _calculate_credits(self, usage: dict, multiplier: float = 1.0) -> int:
        input_tokens = usage.get("input_tokens", 0)
        output_tokens = usage.get("output_tokens", 0)
        total_tokens = input_tokens + output_tokens
        base_credits = total_tokens // 1000
        return max(1, int(base_credits * multiplier))
