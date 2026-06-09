"""端到端测评 harness — 运行单个 task

流程：建空间→灌文件→预处理(含视频OCR)→等后台任务→跑 agent→落盘 trace。
agent 用 model_id="" → AgentLoop 兜底用 .env 的 deepseek-v4-flash。
"""
import asyncio
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path("/root/datamind/Data-Agent-Platform/backend")))

from app.core.database import get_session_factory  # noqa: E402
from app.models.conversation import Conversation  # noqa: E402
from app.agent.loop import AgentLoop  # noqa: E402

from setup_env import ensure_user, ensure_model, reset_space, build_space, INPUT_ROOT  # noqa: E402

RUNS = Path("/root/datamind/Data-Agent-Platform/eval/runs")


async def drain_background_tasks(timeout: float = 600.0) -> None:
    """等待 preprocess_file 派生的后台任务（embedding / 视频OCR）完成。"""
    current = asyncio.current_task()
    deadline = asyncio.get_event_loop().time() + timeout
    while True:
        pending = [t for t in asyncio.all_tasks() if t is not current and not t.done()]
        if not pending:
            return
        remaining = deadline - asyncio.get_event_loop().time()
        if remaining <= 0:
            print(f"  [warn] {len(pending)} 个后台任务超时未完成")
            return
        await asyncio.wait(pending, timeout=min(remaining, 30.0))


def load_question(task_id: str) -> str:
    data = json.loads((INPUT_ROOT / task_id / "task.json").read_text(encoding="utf-8"))
    return data["question"]


async def run_agent(conversation_id: uuid.UUID, user_id: uuid.UUID,
                    space_id: uuid.UUID, question: str, model_id: str) -> dict:
    """跑 AgentLoop，收集流式事件为完整 trace。"""
    loop = AgentLoop()
    events = []
    final_text = []
    tool_log = []
    async for ev in loop.run(
        conversation_id=conversation_id,
        user_id=user_id,
        data_space_id=space_id,
        model_id=model_id,
        user_message=question,
        is_admin=True,  # 跳过额度
    ):
        t = ev.get("type")
        if t == "text":
            final_text.append(ev.get("delta", ""))
        elif t == "tool_use":
            tool_log.append({"phase": "call", "name": ev.get("name"), "input": ev.get("input")})
        elif t == "tool_result":
            tool_log.append({"phase": "result", "name": ev.get("name"),
                             "content": (ev.get("content") or ""),
                             "is_error": ev.get("is_error")})
        elif t == "done":
            events.append({"type": "done", "usage": ev.get("usage"),
                           "tool_calls_log": ev.get("tool_calls_log")})
        elif t == "error":
            events.append({"type": "error", "message": ev.get("message")})
    return {
        "answer": "".join(final_text),
        "tool_log": tool_log,
        "events": events,
    }


async def run_task(task_id: str, rebuild: bool = True) -> dict:
    user_id = await ensure_user()
    model_id = await ensure_model()
    if rebuild:
        await reset_space(user_id, task_id)
        print(f"  building space for {task_id} ...")
        space_id = await build_space(user_id, task_id, run_preprocess=True)
    else:
        space_id = await build_space(user_id, task_id, run_preprocess=False)

    question = load_question(task_id)
    print(f"  Q: {question}")

    async with get_session_factory()() as db:
        conv = Conversation(user_id=user_id, data_space_id=space_id,
                            title=f"eval {task_id}", model_id=model_id)
        db.add(conv)
        await db.commit()
        await db.refresh(conv)
        conv_id = conv.id

    print("  running agent ...")
    result = await run_agent(conv_id, user_id, space_id, question, model_id)

    out_dir = RUNS / task_id
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "result.json").write_text(
        json.dumps({"task_id": task_id, "question": question, **result},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"  answer ({len(result['answer'])} chars), {len(result['tool_log'])} tool events")
    return result


if __name__ == "__main__":
    task_id = sys.argv[1] if len(sys.argv) > 1 else "task_6"
    asyncio.run(run_task(task_id))
