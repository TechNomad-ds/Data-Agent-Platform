"""Agent ReAct 循环 - 基于 Anthropic SDK 的流式 Agent
融合 KDD-CUP 的 schema 预注入 + 重试逻辑 + DataMind 的能力
支持双后端：Anthropic 原生 / OpenAI 兼容接口"""
import uuid
import json
import asyncio
import logging
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
from app.agent.tools import get_tool_definitions, execute_tool, _resolve_tool_name, tool_display_summary
from app.core.security import decrypt_api_key

logger = logging.getLogger("datamind.agent.loop")


_client_cache: dict[str, Any] = {}


# 工具结果是否算「执行失败」。用于累计 consecutive_errors 触发「换个方法」提示，
# 并标记前端 is_error。之前只认 4 个前缀，漏掉文件不存在/读取失败/解析失败等真实
# 失败，导致 agent 拿着错误结果继续或反复同法重试、纠错提示永不触发（P0-1）。
#
# 关键区分：只把「真失败」算错误（需要换方法），不把「合法的空结果/未配置」当错误
# ——后者是有效结论，不该触发纠错循环。
_ERROR_PREFIXES = (
    "工具执行错误", "SQL 错误", "代码执行错误", "查询执行错误",
    "读取文件失败", "解析失败", "下载失败", "联网搜索失败",
)
_ERROR_SUBSTRINGS = (
    "不存在或无权访问", "不存在或不在当前数据空间",
    "无法以 Excel", "无法以表格方式读取",
    "不支持 inspect_data 的文件类型", "暂不支持抽取文本",
)


def _is_tool_error(result_str: str) -> bool:
    """判断工具返回是否表示「执行失败」（而非合法的空结果）。"""
    s = (result_str or "").lstrip()
    if s.startswith(_ERROR_PREFIXES):
        return True
    # 文件名/类型类失败常出现在开头一小段，截一段判断子串，避免误伤正文里出现这些词
    head = s[:200]
    return any(sub in head for sub in _ERROR_SUBSTRINGS)


# 可重试的错误信号：网络抖动、超时、限流、服务端 5xx。出现这些时退避重试整轮采样；
# 致命错误（鉴权 401、请求格式 400 等）不在此列，应直接清晰报错给用户。
_RETRYABLE_STATUS = {408, 409, 429, 500, 502, 503, 504, 529}
_RETRYABLE_KEYWORDS = (
    "timeout", "timed out", "connection", "connect error", "temporarily",
    "overloaded", "rate limit", "too many requests", "service unavailable",
    "bad gateway", "gateway timeout", "econnreset", "read error", "stream",
)
_FATAL_KEYWORDS = (
    "authentication", "invalid api key", "unauthorized", "permission",
    "invalid_request", "invalid request", "not found", "model_not_found",
)

# 单轮内并发执行工具的上限（P0-2 的配套兜底）：模型偶尔一次发起十几个工具调用，
# 无上限的 gather 会瞬间打满 DB 连接池/文件句柄，叠加多用户更危险。限到 5 个一批，
# 既保留并发收益（多文件读取提速），又不放大尾部资源风险。
_TOOL_CONCURRENCY = 5


def _is_retryable_error(exc: Exception) -> bool:
    """判断一次 LLM 调用异常是否值得重试。

    优先看 HTTP status_code；没有则按错误文本里的关键词启发式判断。
    致命关键词（鉴权/请求非法）一律不重试。
    """
    status = getattr(exc, "status_code", None) or getattr(exc, "status", None)
    if isinstance(status, int):
        if status in _RETRYABLE_STATUS:
            return True
        if 400 <= status < 500:
            return False  # 其余 4xx 多为请求问题，重试无意义
    msg = str(exc).lower()
    if any(k in msg for k in _FATAL_KEYWORDS):
        return False
    return any(k in msg for k in _RETRYABLE_KEYWORDS)


def _normalize_openai_base(api_base: str | None) -> str | None:
    """规范化 OpenAI 兼容接口的 base_url。

    OpenAI SDK 会在 base_url 后拼接 /chat/completions。多数中转站/官方接口
    的实际路径是 /v1/chat/completions。如果管理员只填了 host:port（无任何路径），
    SDK 会请求 /chat/completions，部分中转站对此返回空的 200 响应（无报错、无内容），
    导致 Agent 拿到零输出、对话被当作空消息删除。

    策略：仅当 base_url 不含任何路径段时才补 /v1；若管理员已显式写了路径
    （/v1、/v4、/api 等），一律尊重原值，避免补错。
    """
    if not api_base:
        return api_base
    base = api_base.rstrip("/")
    from urllib.parse import urlparse
    try:
        parsed = urlparse(base)
        # path 为空（仅 scheme://host:port）时才补 /v1
        if not parsed.path:
            return base + "/v1"
    except Exception:
        pass
    return base


def _get_client(provider: str, api_key: str, api_base: str | None = None):
    """复用 SDK client，避免每次请求创建新连接"""
    cache_key = f"{provider}:{api_key[:16]}:{api_base or ''}"
    if cache_key in _client_cache:
        return _client_cache[cache_key]

    if provider == "anthropic":
        client = AsyncAnthropic(api_key=api_key, base_url=api_base) if api_base else AsyncAnthropic(api_key=api_key)
    else:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=api_key, base_url=_normalize_openai_base(api_base))

    _client_cache[cache_key] = client
    return client


SYSTEM_PROMPT_TEMPLATE = """你是 DataMind，一个通用 AI 智能体。你的任务是回答用户的问题、完成用户的请求——可能需要读懂用户上传的文件（文档、PDF、论文、讲义、代码、网页、表格、图片 OCR、数据库）后再回答，也可能是不依赖任何文件的通用问题（概念解释、方法建议、写作、代码/架构讨论、学习答疑、闲聊）。

{file_notice}

{memory_context}

# 工作方式

- 判断要不要看文件/数据：需要就用工具去看，不需要就直接回答。不要因为挂着项目就把每个问题都往「分析数据」上扯，也不要在纯知识/写作/闲聊问题上硬调工具。
- 工具是按需自助的：你不会被预先告知文件里有什么，需要时自己探索——`list_files` 看有哪些文件、`read_file` 读内容、`inspect_data` 看表结构、`search_data_space` 在大量文本里定位、`sqlite_query`/`pandas_query` 做表格统计。每个工具的描述里写了各自用途，按需选用。
- 如实汇报：算出/读到什么就说什么，没验证的别当已确认，查不到就说查不到。内部调试过程不要写进正文。
- 歧义大时（指代不清、范围不明）用一句话澄清比猜错好，但不要为凑流程反复打断用户。
- 进入工作后坚持把用户真正的目标做完，不缩水成更省事的小问题；一个来源/方法不行就换，别在反复报错的同一条路上死磕。

# 把外部数据保存进项目（download_to_space）

用户要「把某个 HuggingFace 仓库/数据集、GitHub 文件或某个链接的数据下载/保存进项目」时，用 `download_to_space`：给 HF 仓库页链接会自动下载整个仓库的全部文件并建索引。
- **必须当前选中了一个项目才能保存**。如果现在是普通对话（没有项目），不要假装能存——明确告诉用户：先在左侧选择或新建一个项目，再让你把数据下载进去（下载需要项目作为存放位置）。
- **当前绑定了多个项目时**：数据只能存进其中一个。先问用户「要存到哪个项目」，拿到答复后用 `target_project`（项目名）参数调用 download_to_space。不要自作主张默默存进第一个。（工具也会在多项目且未指定时拦住并让你先确认。）
- 下载完成后如实汇报存了几个文件、有没有超大文件被跳过；之后这些文件就能用 read_file / inspect_data / search_data_space 处理。

# 读文档 / 讲解整篇（质量要求）

要基于上传文档（论文/报告/讲义/资料/代码）讲解、总结、答疑、抽取信息时：
- 先 `list_files` 拿准文件名（别猜、别只靠 search 凑），再 `read_file` 读。
- **逐篇讲解 / 总结整篇时，必须 `read_file` 翻页读到返回末尾出现「全文已读完」为止**；看到「还有 N 行未读」就用提示的 start_line 续读。禁止以「核心已覆盖/摘要引言已够/后面是附录」为由跳过未读部分——方法、实验、结论常在后半部分。
- 很厚的文档（教科书、长手册）找某个具体问题时，不必从头整本读：先用 `search_data_space` 语义定位，再用 `read_file` 的 `find` 参数跳到该处精读。
- `search_data_space` 命中的是片段，只够定位「在哪个文件、哪一段」，不等于读过正文。
- 回答里点明来源（"见 论文A.pdf 第 N 页附近"），方便用户核对。

# 表格数据分析（质量要求）

分析结构化表格（CSV/Excel/数据库）做统计、聚合、取数、跨表关联时：
- 先 `inspect_data` 确认真实列名、dtype、可用的 `df_xxx` 变量名，别凭中文问题猜列名。
- 取明确结果集（列出/计数/最值/排名/满足条件的记录）时，查全查准最重要：列表型答案要含全部满足条件的行（先 COUNT 核对应有多少行）；问「几家/几个」想清楚算记录数还是去重实体数；名字相近的字段（"在任"vs"总数"、"本日"vs"近一周"）先确认问哪个。
- 收尾前自检：对照实际拿到的工具结果核一遍数字、行数、口径、单位、筛选条件是否一致。
- 跨表 JOIN/GROUP BY 用 `sqlite_query`（已自动把空间内所有表格加载进库，多工作表 Excel 展开成 `文件名__工作表名`）；单表快速取数用 `pandas_query`（文件固定叫 `df`，结果赋给 `result`）；需要循环/多步自定义逻辑用 `execute_python`（受限沙箱，用预加载的 `df_xxx`，禁止 open/import 非白名单库）。
- 有趋势/对比/构成关系的分析类任务用 `generate_chart` 配图；取数类任务不要用图替代完整数据。

# 任务计划（update_plan）

任务需多步才能完成时（逐篇读文档再讲解、先读资料再抽取再筛选、逐表分析、端到端取数等），先用 `update_plan` 列出步骤让用户看到进度，每完成一步就更新。每次传完整步骤列表（不是只传变化的那条），步骤用面向用户的一句话。单步问答、概念解释、闲聊不要用。

# 输出格式

- 语言通俗，少用术语；结论先行，再给关键证据。
- 数据对比用 Markdown 表格、关键数字加粗、说明来源；开放式分析最多 5-7 条洞察，每条带关键数字和一句解释，不要套话。
- 公式用 LaTeX：行内 `$...$`，独立 `$$...$$`，不要包在代码块里。
- Markdown 稳定：不输出破损表格、未闭合代码块；列表层级不超过两层。
- 当用户要的是一个确定的数据结果（计数/最值/某条记录/满足条件的列表）时，可在回答末尾附一个 ```answer 块（CSV：首行列名，逗号分隔，只放答案本身，数值写原始值），平台会渲染成查询结果卡。这是可选项，日常解读/概念问答不需要。
- 当用户要「把某个文件发我 / 下载 X / 给我那个文件」，或需要让用户直接拿到数据空间里某个**已存在的文件**时，用 ```file 块单独一行写文件名（如 ```file\nsales.csv``` ），平台会渲染成可下载、可预览的文件卡。只用 list_files 里真实存在的准确文件名，不要臆造；普通提到文件名时不必用。"""



class AgentLoop:
    """支持 Anthropic / OpenAI 双后端的 ReAct Agent 循环"""

    def __init__(self, abort_check=None):
        # 30 步对需要逐条处理大量实体的任务（如给上千只基金分类型）偏紧，会中途
        # 撞上限自动停止且没产出 answer 块。提到 40 给这类任务更多余量；正常任务
        # 远在此之前就完成，不受影响。
        self.max_iterations = 40
        self._abort_check = abort_check or (lambda: False)

    async def _file_notice(self, data_space_id: uuid.UUID | None, user_id: uuid.UUID) -> str:
        """一行式文件提示：只告诉模型本轮挂载了几个文件、什么类型，需要时自己用工具探索。

        刻意做得很轻：一次 DB 查询拿到文件清单做计数，不加载任何 DataFrame、不读列级
        schema、不读文件内容。详细信息全部交给按需工具（list_files / inspect_data /
        read_file），让系统提示词保持静态、prompt 缓存稳定命中。
        """
        if not data_space_id:
            return (
                "【当前对话没有挂载任何文件或数据。】这是一次普通对话——直接回答即可"
                "（概念、写作、代码、答疑、闲聊都行）。若用户想分析文件，提示他在左侧选择项目"
                "或把文件拖进输入框上传，之后你就能用 list_files / read_file 等工具处理。"
            )
        try:
            async with get_session_factory()() as db:
                # 校验空间归属，避免计入非本人空间的文件（与旧 notice 一致的防御）
                space_ok = await db.execute(
                    select(DataSpace.id).where(
                        DataSpace.id == data_space_id, DataSpace.user_id == user_id
                    )
                )
                if space_ok.scalar_one_or_none() is None:
                    return "【当前项目暂无文件。】若用户要分析数据，提示他先上传文件；其余问题正常回答。"
                file_result = await db.execute(
                    select(File)
                    .join(DataSpaceFile, DataSpaceFile.file_id == File.id)
                    .where(DataSpaceFile.data_space_id == data_space_id)
                )
                files = file_result.scalars().all()
        except Exception:
            files = []

        if not files:
            return "【当前项目暂无文件。】若用户要分析数据，提示他先上传文件；其余问题正常回答。"

        from collections import Counter
        type_counts = Counter((f.file_type or "?").lower() for f in files)
        type_summary = "、".join(f"{cnt} 个 {ext}" for ext, cnt in type_counts.most_common())
        return (
            f"【当前项目挂载了 {len(files)} 个文件（{type_summary}）。】需要时自己用工具探索："
            "list_files 看完整清单和文件名、read_file 读文档/PDF/代码内容、"
            "inspect_data 看表格结构、search_data_space 在大量文本里定位、"
            "sqlite_query / pandas_query 做表格统计。不必把所有文件都打开——按问题需要取用。"
        )


    async def _get_conversation_history(self, conversation_id: uuid.UUID) -> list[dict]:
        """获取对话历史，重建为 canonical 消息序列（见 context.py）。

        关键：过去每个 assistant 回合若存了完整工具 I/O（Message.tool_results
        列的 canonical 子序列），就原样回放——这样 Agent 续对话时能看到自己
        上一轮真正查到的数据，而不是只剩一行「调用了某工具」的摘要。没有存
        canonical（旧消息/纯文本回答）时退回用 content 文本。
        """
        async with get_session_factory()() as db:
            result = await db.execute(
                select(Message)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.created_at)
            )
            messages = result.scalars().all()

            canonical: list[dict] = []
            for msg in messages:
                if msg.role == "user":
                    canonical.append({"role": "user", "content": msg.content or ""})
                elif msg.role == "assistant":
                    stored = msg.tool_results if isinstance(msg.tool_results, dict) else None
                    sub = stored.get("canonical") if stored else None
                    if sub and isinstance(sub, list):
                        # 回放完整 canonical 子序列（含工具调用与结果，配对完整）
                        canonical.extend(sub)
                    elif msg.content:
                        canonical.append({
                            "role": "assistant",
                            "content": msg.content,
                            "tool_calls": [],
                        })

            return canonical


    async def _check_balance(self, user_id: uuid.UUID) -> int:
        async with get_session_factory()() as db:
            result = await db.execute(
                select(CreditAccount).where(CreditAccount.user_id == user_id)
            )
            account = result.scalar_one_or_none()
            return account.balance if account else 0

    async def _deduct_credits(self, user_id: uuid.UUID, credits: int, model_name: str) -> None:
        async with get_session_factory()() as db:
            # 使用 FOR UPDATE 加行级锁防止并发透支
            result = await db.execute(
                select(CreditAccount)
                .where(CreditAccount.user_id == user_id)
                .with_for_update()
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

    async def _resolve_model_config(self, model_id: str, user_id: uuid.UUID) -> dict:
        """解析模型配置：根据用户偏好选择平台模型或用户自己的 API"""
        from app.core.redis_client import get_redis
        from app.models.user_api_key import UserApiKey

        # 检查用户偏好：own_api 模式时用用户自己的 API
        try:
            redis = await get_redis()
            api_mode = await redis.get(f"user_pref:{user_id}:api_mode")
        except Exception:
            api_mode = None

        if api_mode == "own_api":
            async with get_session_factory()() as db:
                result = await db.execute(
                    select(UserApiKey).where(UserApiKey.user_id == user_id, UserApiKey.is_active == True)
                )
                key = result.scalar_one_or_none()
                if key:
                    # 优先用映射表的模型名，没有映射则直接用平台模型名
                    model_name = (key.model_mappings or {}).get(model_id) if model_id else None
                    if not model_name and model_id:
                        from app.models.llm_model import LLMModel
                        m = await db.execute(select(LLMModel).where(LLMModel.id == model_id))
                        platform_model = m.scalar_one_or_none()
                        model_name = platform_model.model_name if platform_model else model_id
                    return {
                        "provider": "openai",
                        "api_key": key.api_key_encrypted,
                        "model_name": model_name or "default",
                        "api_base": key.api_base_url,
                        "charge_credits": False,
                        "multiplier": 0,
                    }

        # 查找平台模型配置
        if model_id:
            async with get_session_factory()() as db:
                from app.models.llm_model import LLMModel
                result = await db.execute(
                    select(LLMModel).where(LLMModel.id == model_id, LLMModel.is_active == True)
                )
                model = result.scalar_one_or_none()
                if model:
                    return {
                        "provider": model.provider,
                        "api_key": model.api_key_encrypted,
                        "model_name": model.model_name,
                        "api_base": model.api_base,
                        "charge_credits": True,
                        "multiplier": float(model.credit_multiplier),
                    }

        # 兜底：用 .env 配置
        return {
            "provider": settings.llm_backend,
            "api_key": settings.anthropic_api_key if settings.llm_backend == "anthropic" else settings.openai_api_key,
            "model_name": settings.anthropic_model if settings.llm_backend == "anthropic" else settings.openai_model,
            "api_base": settings.openai_api_base if settings.llm_backend == "openai" else None,
            "charge_credits": True,
            "multiplier": 1.0,
        }

    async def _summarize_history(self, rendered: str, client, backend: str,
                                 model_name: str, system_blocks) -> str:
        """对较早的对话内容做一次 LLM 总结，用于混合 compaction 兜底。

        失败时抛异常由调用方退化为纯窗口策略，不阻断主对话。
        """
        instruction = (
            "你是对话压缩器。请把下面这段较早的数据分析对话压成简洁但信息完整的中文摘要，"
            "保留：用户的目标与约束、已确认的关键数据结论与具体数值、用过哪些数据文件/表、"
            "已知的口径与假设、尚未完成的部分。不要复述工具调用细节，不要编造。\n\n"
            f"=== 待压缩内容 ===\n{rendered}"
        )
        if backend == "anthropic":
            resp = await client.messages.create(
                model=model_name,
                max_tokens=1024,
                messages=[{"role": "user", "content": instruction}],
            )
            parts = [b.text for b in resp.content if getattr(b, "type", None) == "text"]
            return "".join(parts).strip()
        else:
            resp = await client.chat.completions.create(
                model=model_name,
                messages=[{"role": "user", "content": instruction}],
                max_tokens=1024,
                stream=False,
            )
            return (resp.choices[0].message.content or "").strip()

    async def run(
        self,
        conversation_id: uuid.UUID,
        user_id: uuid.UUID,
        data_space_id: uuid.UUID | None,
        model_id: str,
        user_message: str,
        is_admin: bool = False,
        extra_space_ids: list | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """执行 Agent 循环，流式返回事件"""
        # #12 多数据空间：把本轮活跃空间集合注入 contextvar，供工具层跨空间检索/查表。
        # 主空间 + 额外绑定空间；为空集合时工具退化为单主空间，行为不变。
        from app.agent.tools import set_active_space_ids
        _all_spaces = []
        if data_space_id:
            _all_spaces.append(data_space_id)
        for s in (extra_space_ids or []):
            if s and s not in _all_spaces:
                _all_spaces.append(s)
        set_active_space_ids(_all_spaces)
        # 解析模型配置（平台模型 or 用户自带）
        model_config = await self._resolve_model_config(model_id, user_id)
        charge_credits = model_config["charge_credits"] and not is_admin
        credit_multiplier = model_config["multiplier"]
        model_name = model_config["model_name"]

        # 复用 SDK client（按 provider + api_key 缓存）
        try:
            api_key = decrypt_api_key(model_config["api_key"])
        except ValueError:
            yield {"type": "error", "message": "模型 API 密钥解密失败，请在管理后台重新配置模型或在设置中重新配置 API Key。"}
            return
        active_backend = model_config["provider"]
        client = _get_client(active_backend, api_key, model_config.get("api_base"))

        if charge_credits:
            balance = await self._check_balance(user_id)
            if balance <= 0:
                yield {"type": "error", "message": "额度不足。每日免费额度会在次日自动发放，你也可以在「额度中心」查看详情，或在「设置」中配置自己的 API Key 免费使用。"}
                return

        # 构建系统提示。提示词本体完全静态（一个通用 agent + 全量工具自助），
        # 只注入两处动态内容：一行文件提示（本轮挂了几个文件，没有则说明是普通对话）
        # 和相关记忆。不再做模式分流、不预加载 schema/knowledge——这些交给按需工具，
        # 也让 prompt 缓存稳定命中（仅文件数变化时 file_notice 才变）。
        file_notice = await self._file_notice(data_space_id, user_id)

        memory_context = ""
        try:
            from app.services.memory import recall
            memories = await recall(user_id, user_message, data_space_id=data_space_id)
            if memories:
                memory_lines = [f"- [{m['scope']}/{m['kind']}] {m['content']}" for m in memories]
                memory_context = "## 相关记忆\n" + "\n".join(memory_lines)
        except Exception as e:
            logger.warning("memory recall failed, continuing without memory: %s", e)

        system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
            file_notice=file_notice,
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

        # 加载 canonical 历史 + 本次 user 消息，做混合 compaction，再序列化为
        # provider 格式作为循环初始 messages。turn_canonical 并行累积「本回合」
        # 新产生的 canonical 子序列（assistant + 工具结果），随 done 事件回传给
        # 路由层持久化到 Message.tool_results，下一轮即可完整回放。
        from app.agent import context as ctx

        canonical_history = await self._get_conversation_history(conversation_id)
        canonical_all = [*canonical_history, {"role": "user", "content": user_message}]

        async def _summarize(text: str) -> str:
            return await self._summarize_history(
                text, client, active_backend, model_name, system_blocks
            )

        canonical_all = await ctx.compact_messages(
            canonical_all,
            budget=settings.context_token_budget,
            min_recent=settings.context_min_recent_messages,
            enable_summary=settings.context_enable_summary_fallback,
            summarize=_summarize,
        )

        # 压缩后健康校验（对齐 claude code 的压缩后探针，适配本架构）：确认序列结构
        # 合法、不会让下一步 API 调用因孤立 tool_results 而 400。畸形则安全降级到
        # 纯窗口策略（不加摘要、不重排，绝不切断配对）。
        ok, reason = ctx.validate_sequence(canonical_all)
        if not ok:
            canonical_all = await ctx.compact_messages(
                [*canonical_history, {"role": "user", "content": user_message}],
                budget=settings.context_token_budget,
                min_recent=settings.context_min_recent_messages,
                enable_summary=False,
                summarize=None,
            )

        if active_backend == "anthropic":
            messages = ctx.to_anthropic(canonical_all)
        else:
            messages = ctx.to_openai(canonical_all)

        turn_canonical: list[dict] = []

        tools = self._tools_to_anthropic_format()
        total_usage = {"input_tokens": 0, "output_tokens": 0}
        tool_calls_log = []
        consecutive_errors = 0
        # 当前任务计划（由 update_plan 维护），供任务状态停止条件使用
        current_plan: list[dict] = []

        # 停止条件基于「任务状态」而非步数（对齐 codex / claude code）：
        # 模型不再请求工具即视为一个 turn 完成。若此时计划仍有未完成步骤，
        # 注入一次简短提示让它继续；提示有上限，绝不靠步数硬刹车。
        # max_iterations 仅作为防跑飞的安全上限。
        plan_nudges = 0
        MAX_PLAN_NUDGES = 1
        # 撞上限收尾（P1-#3）：跑到最后一步时，不再让模型继续调工具，而是注入一次
        # 「用已有信息给最终答复」的提示并再采样一轮，避免大任务直接烂尾、token 白花。
        final_forced = False
        # 取数结果自检（对齐 codex completion audit）：本轮是否调用过「数据工具」
        # （读/查/算，排除 update_plan / save_memory 等元工具），以及是否已自检过一次。
        data_tool_used = False
        self_check_done = False
        # 反向判定：除了「元工具」（不产生需核实结果），其余工具都算「数据/信息工具」，
        # 用过就该在收尾前自检。这样新增工具（如 download_to_space / web_search）自动纳入，
        # 不会像写死白名单那样漏掉。
        _META_TOOLS = {"update_plan", "save_memory"}

        # 用显式计数的 while 循环：只有「真正向模型采样的轮次」才消耗配额。
        # plan_nudge / self_check 这类注入轮通过 continue 回到顶部，但不计入 iteration，
        # 保证多步任务始终有完整 max_iterations 步用于实际工具调用。
        iteration = 0
        while iteration < self.max_iterations:
            iteration += 1
            if self._abort_check():
                # 中断不是「作废」：把已产出的 canonical 正常收尾持久化，
                # 下一轮用户追加消息时即可在完整上下文上继续（可续中断）。
                yield {"type": "text", "delta": "\n\n[已暂停。你可以补充说明后让我接着做。]"}
                credits_used = max(1, self._calculate_credits(total_usage, credit_multiplier)) if charge_credits else 0
                if charge_credits:
                    await self._deduct_credits(user_id, credits_used, model_name)
                yield {
                    "type": "done",
                    "usage": total_usage,
                    "credits_used": credits_used,
                    "tool_calls_log": tool_calls_log,
                    "canonical": turn_canonical,
                    "interrupted": True,
                }
                return

            try:
                full_text = ""
                reasoning_text = ""  # 推理模型的思考内容（DeepSeek 等需回传）
                tool_uses = []
                # 本轮采样的重试控制：仅当「尚未向用户流出任何内容」时才重试整轮采样，
                # 避免重复输出。一旦已经流出文本/工具增量，中途断流走优雅降级（保留已产出）。
                streamed_anything = False
                attempt = 0
                # 收尾轮禁用工具，强制模型用已有信息直接作答（P1-#3）
                _pass_tools = [] if final_forced else tools
                while True:
                    try:
                        if active_backend == "anthropic":
                            # Anthropic SDK 流式调用
                            response_stream = client.messages.stream(
                                model=model_name,
                                max_tokens=settings.anthropic_max_tokens,
                                system=system_blocks,
                                messages=messages,
                                tools=_pass_tools,
                            )
                            async with response_stream as stream:
                                async for event in stream:
                                    if self._abort_check():
                                        break
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
                                            if event.delta.text:
                                                streamed_anything = True
                                                yield {"type": "text", "delta": event.delta.text}
                                        elif event.delta.type == "input_json_delta":
                                            if tool_uses:
                                                streamed_anything = True
                                                tool_uses[-1]["input_json"] += event.delta.partial_json
                                final_message = await stream.get_final_message()
                                total_usage["input_tokens"] += final_message.usage.input_tokens
                                total_usage["output_tokens"] += final_message.usage.output_tokens

                        else:
                            # OpenAI 兼容接口流式调用
                            openai_tools = [] if final_forced else get_tool_definitions()
                            oai_messages = [{"role": "system", "content": system_blocks if isinstance(system_blocks, str) else system_blocks[0]["text"]}] + messages
                            response = await client.chat.completions.create(
                                model=model_name,
                                messages=oai_messages,
                                tools=openai_tools if openai_tools else None,
                                stream=True,
                            )
                            tool_calls_data = []
                            async for chunk in response:
                                if self._abort_check():
                                    break
                                delta = chunk.choices[0].delta if chunk.choices else None
                                if not delta:
                                    continue
                                # 处理推理模型的 reasoning_content（如 DeepSeek）
                                reasoning = getattr(delta, 'reasoning_content', None)
                                if reasoning:
                                    reasoning_text += reasoning
                                    streamed_anything = True
                                    yield {"type": "thinking", "content": reasoning}
                                if delta.content:
                                    full_text += delta.content
                                    streamed_anything = True
                                    yield {"type": "text", "delta": delta.content}
                                if delta.tool_calls:
                                    for tc in delta.tool_calls:
                                        streamed_anything = True
                                        while tc.index >= len(tool_calls_data):
                                            tool_calls_data.append({"id": "", "function": {"name": "", "arguments": ""}})
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
                            # 转换为统一的 tool_uses 格式（过滤掉无效的 tool_call）
                            for tc in tool_calls_data:
                                if tc["id"] and tc["function"]["name"]:
                                    tool_uses.append({
                                        "id": tc["id"],
                                        "name": tc["function"]["name"],
                                        "input_json": tc["function"]["arguments"],
                                    })
                        break  # 本轮采样成功，跳出重试循环

                    except Exception as stream_err:
                        # 已经向用户流出内容 → 不重试（重试会重复输出）。
                        # 当作优雅降级：保留已产出的 full_text，按"模型本轮结束"继续后续逻辑。
                        if streamed_anything:
                            yield {"type": "text", "delta": "\n\n[与模型的连接中断，已保留上面已生成的内容。]"}
                            tool_uses = []
                            break
                        # 尚未流出任何内容：可重试错误就退避重试，否则上抛由外层报错。
                        if attempt < settings.llm_max_retries and _is_retryable_error(stream_err):
                            attempt += 1
                            delay = settings.llm_retry_base_delay * (2 ** (attempt - 1))
                            yield {"type": "thinking", "content": f"网络波动，正在重试（第 {attempt} 次）…"}
                            await asyncio.sleep(delay)
                            full_text = ""
                            reasoning_text = ""
                            tool_uses = []
                            continue
                        raise


                # 流式过程中被中断：把已产出的半截文本并入 canonical，跳回循环顶部
                # 由统一的「暂停收尾」分支干净落盘，不执行本轮残缺的工具调用。
                if self._abort_check():
                    if full_text:
                        turn_canonical.append({
                            "role": "assistant", "content": full_text, "tool_calls": [],
                        })
                    continue

                # 没有工具调用 → 模型认为本 turn 完成。基于任务状态判断是否真的结束：
                # 若存在计划且仍有未完成步骤，注入一次简短提示让它继续；否则正式收尾。
                if not tool_uses:
                    plan_incomplete = bool(current_plan) and any(
                        s.get("status") != "completed" for s in current_plan
                    )
                    if plan_incomplete and plan_nudges < MAX_PLAN_NUDGES:
                        if full_text:
                            messages.append({"role": "assistant", "content": full_text})
                            turn_canonical.append({
                                "role": "assistant", "content": full_text, "tool_calls": [],
                            })
                        pending = [s["content"] for s in current_plan if s.get("status") != "completed"]
                        nudge = (
                            "（系统提示）你的任务计划还有未完成的步骤："
                            + "；".join(pending[:5])
                            + "。请继续执行：要么调用工具完成它们，要么如果已无法推进，"
                            "就基于现有信息给出最终答案，并用 update_plan 把计划标记为完成。"
                        )
                        messages.append({"role": "user", "content": nudge})
                        turn_canonical.append({"role": "user", "content": nudge})
                        plan_nudges += 1
                        iteration -= 1  # 注入轮不消耗工具调用配额
                        continue

                    # 取数结果自检（对齐 codex completion audit）：本轮用过数据工具、
                    # 尚未自检过、且开关开启时，注入一次有界的核对提示。只做一次，
                    # 不基于文本启发式（基于真实工具使用），不会无限循环。
                    if (settings.enable_answer_self_check and data_tool_used
                            and not self_check_done):
                        if full_text:
                            messages.append({"role": "assistant", "content": full_text})
                            turn_canonical.append({
                                "role": "assistant", "content": full_text, "tool_calls": [],
                            })
                        audit = (
                            "（系统自检，仅本轮内部使用）在给出最终答复前，请对照你上面实际拿到的"
                            "工具结果快速核对一遍：关键数字/行数/聚合口径/单位/筛选条件是否与工具输出一致？"
                            "是否有该列全/该去重/该换算却没做的地方？"
                            "如果发现不一致或遗漏，直接修正（必要时再调用工具），然后给出最终答复；"
                            "如果核对无误，就直接给出最终答复，不要复述这段自检过程。"
                        )
                        messages.append({"role": "user", "content": audit})
                        turn_canonical.append({"role": "user", "content": audit})
                        self_check_done = True
                        iteration -= 1  # 自检注入轮不消耗工具调用配额
                        continue

                    credits_used = max(1, self._calculate_credits(total_usage, credit_multiplier)) if charge_credits else 0
                    if charge_credits:
                        await self._deduct_credits(user_id, credits_used, model_name)
                    if full_text:
                        turn_canonical.append({
                            "role": "assistant",
                            "content": full_text,
                            "tool_calls": [],
                        })
                    yield {
                        "type": "done",
                        "usage": total_usage,
                        "credits_used": credits_used,
                        "tool_calls_log": tool_calls_log,
                        "canonical": turn_canonical,
                    }
                    return

                # 撞上限收尾（P1-#3）：模型还想调工具，但已接近步数上限。不执行这些工具，
                # 改为把已产出的文本并入历史，注入「用已有信息收尾」提示，再给一轮无工具
                # 采样产出最终答复——避免大任务直接烂尾、之前的工作白费。
                if final_forced:
                    # 收尾轮里模型仍执意调工具（少见）：不再纠缠，直接用已产出文本收尾。
                    if full_text:
                        turn_canonical.append({
                            "role": "assistant", "content": full_text, "tool_calls": [],
                        })
                    else:
                        closing = "已到执行步数上限。以上是目前已完成的部分；可补充说明后我接着做。"
                        yield {"type": "text", "delta": "\n\n" + closing}
                        turn_canonical.append({
                            "role": "assistant", "content": closing, "tool_calls": [],
                        })
                    credits_used = max(1, self._calculate_credits(total_usage, credit_multiplier)) if charge_credits else 0
                    if charge_credits:
                        await self._deduct_credits(user_id, credits_used, model_name)
                    yield {
                        "type": "done", "usage": total_usage, "credits_used": credits_used,
                        "tool_calls_log": tool_calls_log, "canonical": turn_canonical,
                    }
                    return

                if iteration >= self.max_iterations - 1:
                    if full_text:
                        messages.append({"role": "assistant", "content": full_text})
                        turn_canonical.append({
                            "role": "assistant", "content": full_text, "tool_calls": [],
                        })
                    wrap = (
                        "（系统提示）已到本轮工具调用步数上限，不能再调用工具了。"
                        "请基于你目前已经掌握的信息，直接给出尽可能完整、有用的最终答复："
                        "总结已完成的部分和已得到的结论，对还没来得及核实/完成的部分如实说明，"
                        "并给出后续可以怎么继续。不要再尝试调用任何工具。"
                    )
                    messages.append({"role": "user", "content": wrap})
                    turn_canonical.append({"role": "user", "content": wrap})
                    final_forced = True
                    continue  # 收尾轮不减 iteration——靠 final_forced 单独保证只走一次

                # 构建本回合 canonical assistant 条目（含工具调用），再由统一序列化器
                # 转成 provider 格式追加到 messages——消除手工维护两套格式的漂移风险。
                _canon_tool_calls = []
                for tu in tool_uses:
                    try:
                        _ci = json.loads(tu["input_json"]) if tu["input_json"] else {}
                    except json.JSONDecodeError:
                        _ci = {}
                    _canon_tool_calls.append({"id": tu["id"], "name": tu["name"], "input": _ci})
                assistant_entry = {
                    "role": "assistant",
                    "content": full_text,
                    "tool_calls": _canon_tool_calls,
                }
                turn_canonical.append(assistant_entry)

                if active_backend == "anthropic":
                    messages.extend(ctx.to_anthropic([assistant_entry]))
                else:
                    serialized = ctx.to_openai([assistant_entry])
                    # 推理模型（DeepSeek thinking 等）要求把 reasoning_content 原样回传，否则下一轮报 400
                    if reasoning_text and serialized:
                        serialized[0]["reasoning_content"] = reasoning_text
                    messages.extend(serialized)

                # 执行工具并收集结果。
                # P0-2：同一轮模型可能一次发起多个工具调用（如逐篇 read_file 多个文件）。
                # 这些调用相互独立（模型在看不到彼此结果时同时发出），可并发执行，
                # 把多文件读取/检索的墙钟时间从「之和」降到「最慢的一个」。
                # 三段式：① 串行预处理（名字纠正/解析/发 tool_use 事件/内联处理 update_plan）
                # ② 并发执行真正的工具 ③ 串行后处理（错误判定/截断/发 tool_result，保持顺序）。
                tool_results = []
                valid_tool_names = [t["function"]["name"] for t in get_tool_definitions()]
                to_run = []  # [(tu, tool_args)]，待并发执行的真实工具
                for tu in tool_uses:
                    corrected_name = _resolve_tool_name(tu["name"], valid_tool_names)
                    if corrected_name:
                        tu["name"] = corrected_name

                    try:
                        tool_args = json.loads(tu["input_json"]) if tu["input_json"] else {}
                    except json.JSONDecodeError:
                        tool_args = {}

                    # update_plan 是「元工具」：不访问数据，只把计划状态推给前端，
                    # 并回一条简短 ack 维持工具调用协议有效。同时更新 current_plan
                    # 供主循环的任务状态停止条件使用。
                    if tu["name"] == "update_plan":
                        steps = tool_args.get("steps", []) if isinstance(tool_args, dict) else []
                        norm_steps = [
                            {
                                "content": str(s.get("content", "")).strip(),
                                "status": s.get("status", "pending"),
                            }
                            for s in steps if isinstance(s, dict)
                        ]
                        current_plan = norm_steps
                        yield {"type": "plan", "steps": norm_steps}
                        ack = "计划已更新。" + (
                            "全部步骤已完成。" if norm_steps and all(s["status"] == "completed" for s in norm_steps)
                            else "请按计划继续执行下一步。"
                        )
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tu["id"],
                            "content": ack,
                            "is_error": False,
                        })
                        continue

                    # 记录本轮用过「非元工具」（读/查/算/下载/联网等），供完成前的取数自检判断。
                    if tu["name"] not in _META_TOOLS:
                        data_tool_used = True

                    # 发送给前端的 input 做脱敏：去除代码、路径等内部细节
                    safe_input = {}
                    for k, v in tool_args.items():
                        if k == "code":
                            continue
                        elif k == "sql":
                            continue
                        elif k == "expression":
                            continue
                        elif k == "text" and len(str(v)) > 50:
                            safe_input[k] = str(v)[:50] + "..."
                        else:
                            safe_input[k] = v

                    yield {
                        "type": "tool_use",
                        "name": tu["name"],
                        "input": safe_input,
                        "id": tu["id"],
                        "summary": tool_display_summary(tu["name"], tool_args),
                    }
                    to_run.append((tu, tool_args))

                # ② 并发执行（单个失败不影响其它：异常就地转成错误字符串）
                async def _run_one(tu, tool_args):
                    try:
                        return str(await execute_tool(
                            tool_name=tu["name"],
                            arguments=tool_args,
                            user_id=user_id,
                            data_space_id=data_space_id,
                        ))
                    except Exception as e:
                        return f"工具执行错误: {str(e)}"

                run_results = []
                if to_run:
                    if len(to_run) == 1:
                        run_results = [await _run_one(to_run[0][0], to_run[0][1])]
                    else:
                        # 限流并发：最多 _TOOL_CONCURRENCY 个工具同时执行，避免打满资源
                        _sem = asyncio.Semaphore(_TOOL_CONCURRENCY)
                        async def _run_bounded(tu, ta):
                            async with _sem:
                                return await _run_one(tu, ta)
                        run_results = await asyncio.gather(
                            *[_run_bounded(tu, ta) for tu, ta in to_run]
                        )

                # ③ 串行后处理：按发起顺序做错误判定/截断/日志/事件，语义与原先一致
                for (tu, tool_args), result_str in zip(to_run, run_results):
                    is_error = _is_tool_error(result_str)
                    if is_error:
                        consecutive_errors += 1
                    else:
                        consecutive_errors = 0

                    # 模型可见的工具结果上限：放宽到 15 万字符，让"读完整篇论文/长文档"
                    # 或"列出全部"这类大结果能完整进入上下文（约数千行），而不是被腰斩——
                    # 尤其 read_file 的「全文已读完/未读完」信号在结果末尾，截断会把它一起切掉，
                    # 导致模型误判已读完。极端超大结果才会触顶，此时提示改用聚合/筛选/翻页。
                    if len(result_str) > 150000:
                        result_str = result_str[:150000] + (
                            "\n...(结果过大已截断。若是查表请用聚合/分组/WHERE 缩小范围而非逐行返回；"
                            "若是读长文档请用更小的 max_lines 分页读，按末尾提示逐页续读)"
                        )

                    tool_calls_log.append({
                        "name": tu["name"],
                        "input": tool_args,
                        "output_preview": result_str[:200],
                    })

                    # 脱敏：移除存储路径 + 遮蔽凭据。前端展示只取前 2000 字符，诚实标注是否截断。
                    full_len = len(result_str)
                    display_result = ctx.redact_secrets(
                        result_str[:2000].replace(settings.storage_root, "[数据]")
                    )
                    display_truncated = full_len > 2000

                    yield {
                        "type": "tool_result",
                        "name": tu["name"],
                        "content": display_result,
                        "is_error": is_error,
                        "truncated": display_truncated,
                        "total_chars": full_len,
                        "shown_chars": min(full_len, 2000),
                    }

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tu["id"],
                        "content": result_str,
                        "is_error": is_error,
                    })

                # 工具结果 → canonical，再由统一序列化器转 provider 格式追加到 messages。
                # 循环内 messages 用完整结果（模型可见），持久化的 turn_canonical 用按
                # 配置截断的结果（避免历史无限膨胀）。
                def _result_name(tr):
                    return next((tu["name"] for tu in tool_uses if tu["id"] == tr["tool_use_id"]), "")

                full_results_entry = {
                    "role": "tool_results",
                    "results": [
                        {"id": tr["tool_use_id"], "name": _result_name(tr),
                         "content": tr["content"], "is_error": tr["is_error"]}
                        for tr in tool_results
                    ],
                }
                if active_backend == "anthropic":
                    messages.extend(ctx.to_anthropic([full_results_entry]))
                else:
                    messages.extend(ctx.to_openai([full_results_entry]))

                turn_canonical.append({
                    "role": "tool_results",
                    "results": [
                        {
                            "id": tr["tool_use_id"],
                            "name": _result_name(tr),
                            # 持久化/回放边界：先截断再脱敏凭据（当轮模型看到的完整结果
                            # 在 messages 里，不受影响）。
                            "content": ctx.redact_secrets(ctx.truncate_tool_content(
                                tr["content"], settings.context_tool_result_max_chars
                            )),
                            "is_error": tr["is_error"],
                        }
                        for tr in tool_results
                    ],
                })

                # 重试逻辑：连续失败时注入提示（来自 KDD-CUP）
                if consecutive_errors >= 2:
                    messages.append({
                        "role": "user",
                        "content": "提示：已连续多次失败，请换一种方法尝试。减少探索步骤，直接用最简单的方式解决问题。",
                    })
                    consecutive_errors = 0

            except Exception as e:
                # 重试已在内层用尽（或属致命错误）。给用户一句可读的说明，
                # 并把本轮已产出的 canonical 落盘，便于下一轮接续。
                if any(k in str(e).lower() for k in _FATAL_KEYWORDS):
                    hint = "模型调用被拒绝（可能是 API Key 或请求配置问题）。请检查模型设置后重试。"
                else:
                    hint = "模型调用多次失败，可能是网络或服务暂时不可用。请稍后重试。"
                yield {"type": "error", "message": f"{hint}（{str(e)[:200]}）"}
                if turn_canonical:
                    credits_used = max(1, self._calculate_credits(total_usage, credit_multiplier)) if charge_credits else 0
                    yield {
                        "type": "done",
                        "usage": total_usage,
                        "credits_used": credits_used if charge_credits else 0,
                        "tool_calls_log": tool_calls_log,
                        "canonical": turn_canonical,
                        "interrupted": True,
                    }
                return

        # 达到最大迭代次数（正常情况下已被上面的「收尾轮」拦截并给出最终答复；
        # 走到这里属极端兜底）。
        credits_used = max(1, self._calculate_credits(total_usage, credit_multiplier)) if charge_credits else 0
        if charge_credits:
            await self._deduct_credits(user_id, credits_used, model_name)
        yield {"type": "text", "delta": "\n\n[已达到最大执行步数。以上是目前已完成的部分；可补充说明后让我接着做。]"}
        yield {"type": "done", "usage": total_usage, "credits_used": credits_used, "tool_calls_log": tool_calls_log, "canonical": turn_canonical}

    def _calculate_credits(self, usage: dict, multiplier: float = 1.0) -> int:
        return 1
