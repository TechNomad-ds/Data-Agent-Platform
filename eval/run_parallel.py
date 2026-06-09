"""并行批量跑 task + 评分 + 汇总。

视频 OCR 是网络等待型（提交+轮询远程接口），并行收益大。
每个 task 是独立数据空间，sqlite 缓存按 space_id 分键，互不冲突。
用 semaphore 控制并发度，避免远程 OCR 接口被打爆。

用法：
  python run_parallel.py                # 全部 60 题，默认并发 4
  python run_parallel.py --conc 6       # 并发 6
  python run_parallel.py 1 6 17         # 指定 task
  python run_parallel.py --score        # 只重新评分
"""
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from run_task import run_task, RUNS  # noqa: E402
from score import score_task  # noqa: E402

INPUT_ROOT = Path("/root/datamind/demo_samples_phase2/input")
ALL_TASKS = sorted((d.name for d in INPUT_ROOT.iterdir() if d.name.startswith("task_")),
                   key=lambda s: int(s.split("_")[1]))


async def run_one(task_id: str, sem: asyncio.Semaphore, force: bool) -> dict:
    res_path = RUNS / task_id / "result.json"
    if res_path.exists() and not force:
        print(f"[{task_id}] skip (exists)", flush=True)
        return score_task(task_id, RUNS)
    async with sem:
        t0 = time.time()
        print(f"[{task_id}] START", flush=True)
        try:
            await run_task(task_id, rebuild=True)
            sc = score_task(task_id, RUNS)
            print(f"[{task_id}] DONE {time.time()-t0:.0f}s  "
                  f"{'PASS' if sc.get('status')=='pass' else 'fail'} f1={sc.get('f1',0):.2f}", flush=True)
            return sc
        except Exception as e:
            import traceback
            print(f"[{task_id}] ERROR {e}", flush=True)
            traceback.print_exc()
            res_path.parent.mkdir(parents=True, exist_ok=True)
            res_path.write_text(json.dumps(
                {"task_id": task_id, "error": str(e), "answer": "", "tool_log": []},
                ensure_ascii=False), encoding="utf-8")
            return score_task(task_id, RUNS)


async def main():
    args = sys.argv[1:]
    force = "--force" in args
    score_only = "--score" in args
    conc = 4
    skip_args = set()
    if "--conc" in args:
        ci = args.index("--conc")
        conc = int(args[ci + 1])
        skip_args = {ci, ci + 1}  # 排除 --conc 及其值，避免被当成 task 编号
    nums = [a for i, a in enumerate(args) if a.isdigit() and i not in skip_args]
    tasks = [f"task_{n}" for n in nums] if nums else ALL_TASKS

    if score_only:
        results = [score_task(t, RUNS) for t in tasks]
    else:
        sem = asyncio.Semaphore(conc)
        results = await asyncio.gather(*[run_one(t, sem, force) for t in tasks])

    passed = [r for r in results if r.get("status") == "pass"]
    report = {
        "total": len(results), "passed": len(passed),
        "pass_rate": round(len(passed) / len(results), 3) if results else 0,
        "results": sorted(results, key=lambda r: int(r["task_id"].split("_")[1])),
    }
    (Path(__file__).parent / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n{'='*50}\n通过 {len(passed)}/{len(results)} "
          f"({report['pass_rate']*100:.0f}%)\n{'='*50}", flush=True)
    for r in report["results"]:
        mark = "✓" if r.get("status") == "pass" else "✗"
        print(f"  {mark} {r['task_id']:9s} f1={r.get('f1',0):.2f} "
              f"recall={r.get('recall',0):.2f} (gold {r.get('gold_rows','?')}行)", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
