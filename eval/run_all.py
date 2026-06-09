"""批量跑全部 task + 评分 + 汇总报告。

用法：
  python run_all.py            # 跑全部 60 题（跳过已有 result.json）
  python run_all.py --force    # 全部重跑
  python run_all.py 1 6 17     # 只跑指定 task 编号
  python run_all.py --score    # 不跑，只对已有 runs 重新评分
"""
import asyncio
import json
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from run_task import run_task, RUNS  # noqa: E402
from score import score_task  # noqa: E402

INPUT_ROOT = Path("/root/datamind/demo_samples_phase2/input")
ALL_TASKS = sorted((d.name for d in INPUT_ROOT.iterdir() if d.name.startswith("task_")),
                   key=lambda s: int(s.split("_")[1]))


def has_video(task_id: str) -> bool:
    return any((INPUT_ROOT / task_id / "context").rglob("*.mp4"))


async def run_one(task_id: str, force: bool) -> dict:
    res_path = RUNS / task_id / "result.json"
    if res_path.exists() and not force:
        print(f"[{task_id}] 已有结果，跳过运行")
    else:
        t0 = time.time()
        try:
            await run_task(task_id, rebuild=True)
        except Exception as e:
            print(f"[{task_id}] 运行异常: {e}")
            traceback.print_exc()
            (RUNS / task_id).mkdir(parents=True, exist_ok=True)
            res_path.write_text(json.dumps(
                {"task_id": task_id, "error": str(e), "answer": "", "tool_log": []},
                ensure_ascii=False), encoding="utf-8")
        print(f"[{task_id}] 用时 {time.time()-t0:.0f}s")
    return score_task(task_id, RUNS)


async def main():
    args = sys.argv[1:]
    force = "--force" in args
    score_only = "--score" in args
    nums = [a for a in args if a.isdigit()]
    tasks = [f"task_{n}" for n in nums] if nums else ALL_TASKS

    results = []
    for tid in tasks:
        if score_only:
            results.append(score_task(tid, RUNS))
            continue
        vid = " [VIDEO]" if has_video(tid) else ""
        print(f"\n===== {tid}{vid} =====")
        results.append(await run_one(tid, force))

    # 汇总
    passed = [r for r in results if r.get("status") == "pass"]
    report = {
        "total": len(results),
        "passed": len(passed),
        "pass_rate": round(len(passed) / len(results), 3) if results else 0,
        "results": sorted(results, key=lambda r: int(r["task_id"].split("_")[1])),
    }
    (Path(__file__).parent / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n{'='*50}\n通过 {len(passed)}/{len(results)} ({report['pass_rate']*100:.0f}%)\n{'='*50}")
    for r in report["results"]:
        mark = "✓" if r.get("status") == "pass" else "✗"
        print(f"  {mark} {r['task_id']:9s} f1={r.get('f1',0):.2f} "
              f"recall={r.get('recall',0):.2f} prec={r.get('precision',0):.2f} "
              f"(gold {r.get('gold_rows','?')}行)")


if __name__ == "__main__":
    asyncio.run(main())
