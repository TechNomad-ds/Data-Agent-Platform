"""上下文管理：规范化消息格式 + token 预算 + 混合 compaction。

设计要点：
- 内部用一套与 provider 无关的 canonical 消息格式承载历史；再由
  ``to_anthropic`` / ``to_openai`` 序列化成各后端的真实格式。这样
  compaction 只需在一种格式上实现，且能可靠识别 tool_use / tool_result
  配对，绝不把配对切断（切断会让下一轮 API 直接 400）。
- compaction 策略为「混合」：优先按 token 预算保留最近窗口（零额外成本）；
  仅当保留窗口本身仍超预算时，才对更早的消息做一次 LLM 总结兜底。

canonical 消息形态（list[dict]）：
- {"role": "user", "content": str}
- {"role": "assistant", "content": str, "tool_calls": [{"id","name","input"}]}
    - content 可为 ""；tool_calls 可为 []（纯文本回答）
- {"role": "tool_results", "results": [{"id","name","content","is_error"}]}
- {"role": "summary", "content": str}   # compaction 产生的摘要
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable, Awaitable

_CJK = re.compile(r"[㐀-鿿豈-﫿぀-ヿ]")


def estimate_tokens(text: str | None) -> int:
    """粗估 token 数。CJK 字符约 1 token/字，其余约 4 字符/token。

    不追求精确，只为预算决策提供稳定、廉价、偏保守的估计。
    """
    if not text:
        return 0
    cjk = len(_CJK.findall(text))
    other = len(text) - cjk
    return cjk + (other // 4) + 1


def _stringify_input(value: Any) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(value)


def estimate_message_tokens(msg: dict) -> int:
    """估算单条 canonical 消息的 token 数（含工具入参/结果）。"""
    role = msg.get("role")
    if role == "tool_results":
        total = 4
        for r in msg.get("results", []):
            total += estimate_tokens(str(r.get("content", ""))) + 4
        return total
    if role == "assistant":
        total = estimate_tokens(msg.get("content", ""))
        for tc in msg.get("tool_calls", []) or []:
            total += estimate_tokens(tc.get("name", "")) + 2
            total += estimate_tokens(_stringify_input(tc.get("input", {})))
        return total + 4
    # user / summary
    return estimate_tokens(msg.get("content", "")) + 4


def truncate_tool_content(content: str, max_chars: int) -> str:
    """截断单条工具结果，并诚实标注被截断。"""
    if content is None:
        return ""
    content = str(content)
    if len(content) <= max_chars:
        return content
    return content[:max_chars] + (
        f"\n...(工具结果过长，已截断；完整约 {len(content)} 字符，"
        f"此处保留前 {max_chars}。如需更多明细请缩小查询范围或分批查询)"
    )


def _is_pair_boundary_safe(messages: list[dict], cut: int) -> bool:
    """判断在 index=cut 处切（保留 messages[cut:]）是否会孤立 tool_results。

    canonical 里 tool_results 必须紧跟在带 tool_calls 的 assistant 之后。
    若保留窗口的第一条是 tool_results，说明它的 assistant 被切掉了 → 不安全。
    """
    if cut >= len(messages):
        return True
    return messages[cut].get("role") != "tool_results"


def _split_keep_window(
    messages: list[dict], budget: int, min_recent: int
) -> tuple[list[dict], list[dict]]:
    """从尾部向前累加，确定要完整保留的窗口；返回 (older, kept)。

    保证：①至少保留 min_recent 条；②不在 assistant/tool_results 配对中间切断。
    """
    n = len(messages)
    if n == 0:
        return [], []

    # 先按 token 预算从尾部确定初步切点
    acc = 0
    cut = n
    for i in range(n - 1, -1, -1):
        acc += estimate_message_tokens(messages[i])
        if acc > budget and (n - i) > min_recent:
            cut = i + 1
            break
        cut = i

    # 强制至少保留 min_recent 条
    cut = min(cut, max(0, n - min_recent))

    # 调整切点避免孤立 tool_results：把切点往前挪到安全位置
    while cut > 0 and not _is_pair_boundary_safe(messages, cut):
        cut -= 1

    return messages[:cut], messages[cut:]


def _render_for_summary(messages: list[dict]) -> str:
    """把待压缩的旧消息渲染成纯文本，供总结模型阅读。"""
    lines: list[str] = []
    for m in messages:
        role = m.get("role")
        if role == "user":
            lines.append(f"用户: {m.get('content', '')}")
        elif role == "summary":
            lines.append(f"[既有摘要] {m.get('content', '')}")
        elif role == "assistant":
            if m.get("content"):
                lines.append(f"助手: {m['content']}")
            for tc in m.get("tool_calls", []) or []:
                lines.append(
                    f"助手[调用工具 {tc.get('name')}]: "
                    f"{_stringify_input(tc.get('input', {}))[:300]}"
                )
        elif role == "tool_results":
            for r in m.get("results", []):
                tag = "失败" if r.get("is_error") else "结果"
                lines.append(
                    f"工具[{r.get('name')}·{tag}]: {str(r.get('content', ''))[:600]}"
                )
    return "\n".join(lines)


SummarizeFn = Callable[[str], Awaitable[str]]


async def compact_messages(
    messages: list[dict],
    *,
    budget: int,
    min_recent: int,
    enable_summary: bool = True,
    summarize: SummarizeFn | None = None,
) -> list[dict]:
    """混合 compaction：预算内原样返回；超预算保留最近窗口；
    窗口仍超预算且允许总结时，对更早消息做一次 LLM 总结兜底。

    summarize: async (rendered_text) -> summary_text。为 None 或失败时
    退化为「纯窗口」策略（直接丢弃更早消息，绝不切断工具配对）。
    """
    total = sum(estimate_message_tokens(m) for m in messages)
    if total <= budget:
        return messages

    older, kept = _split_keep_window(messages, budget, min_recent)
    if not older:
        return kept

    if not (enable_summary and summarize):
        return kept

    try:
        summary_text = await summarize(_render_for_summary(older))
    except Exception:
        # 总结失败：退化为纯窗口，不阻断对话
        return kept

    if not summary_text:
        return kept

    summary_msg = {
        "role": "summary",
        "content": (
            "以下是本次对话较早内容的摘要（原文已因长度压缩）：\n"
            + summary_text.strip()
        ),
    }
    return [summary_msg, *kept]


# --------------------------------------------------------------------------
# 序列化：canonical -> 各 provider 真实格式
# --------------------------------------------------------------------------

def to_anthropic(messages: list[dict]) -> list[dict]:
    """canonical -> Anthropic messages 格式。"""
    out: list[dict] = []
    for m in messages:
        role = m.get("role")
        if role == "user":
            out.append({"role": "user", "content": m.get("content", "")})
        elif role == "summary":
            # 摘要以 user 角色注入（Anthropic 无独立 system-in-history 概念）
            out.append({"role": "user", "content": m.get("content", "")})
        elif role == "assistant":
            content: list[dict] = []
            if m.get("content"):
                content.append({"type": "text", "text": m["content"]})
            for tc in m.get("tool_calls", []) or []:
                content.append({
                    "type": "tool_use",
                    "id": tc.get("id", ""),
                    "name": tc.get("name", ""),
                    "input": tc.get("input", {}) or {},
                })
            if content:
                out.append({"role": "assistant", "content": content})
        elif role == "tool_results":
            blocks = []
            for r in m.get("results", []):
                block = {
                    "type": "tool_result",
                    "tool_use_id": r.get("id", ""),
                    "content": str(r.get("content", "")),
                }
                if r.get("is_error"):
                    block["is_error"] = True
                blocks.append(block)
            if blocks:
                out.append({"role": "user", "content": blocks})
    return out


def to_openai(messages: list[dict]) -> list[dict]:
    """canonical -> OpenAI chat.completions 格式（不含 system）。"""
    out: list[dict] = []
    for m in messages:
        role = m.get("role")
        if role in ("user", "summary"):
            out.append({"role": "user", "content": m.get("content", "")})
        elif role == "assistant":
            tcs = m.get("tool_calls", []) or []
            msg: dict = {"role": "assistant", "content": m.get("content") or None}
            if tcs:
                msg["tool_calls"] = [
                    {
                        "id": tc.get("id", ""),
                        "type": "function",
                        "function": {
                            "name": tc.get("name", ""),
                            "arguments": _stringify_input(tc.get("input", {}) or {}),
                        },
                    }
                    for tc in tcs
                ]
            out.append(msg)
        elif role == "tool_results":
            for r in m.get("results", []):
                out.append({
                    "role": "tool",
                    "tool_call_id": r.get("id", ""),
                    "content": str(r.get("content", "")),
                })
    return out
