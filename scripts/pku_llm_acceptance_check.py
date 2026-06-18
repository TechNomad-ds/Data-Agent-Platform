#!/usr/bin/env python3
"""Optional PKU LLM acceptance checks.

This script runs after `pku_acceptance_smoke.py` style API checks. It creates a
fresh account/data spaces, uploads representative materials, sends real chat
messages, and verifies the answers with deterministic rules. It intentionally
does consume model credits/API quota.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Callable

import httpx

from pku_acceptance_smoke import (
    DEFAULT_PASSWORD,
    DEFAULT_SMOKE_EMAIL,
    DEFAULT_SMOKE_USERNAME,
    SmokeContext,
    _materials,
    _python_runtime_info,
    _require_status,
    create_space,
    register_or_login,
    upload_files,
)


CheckFn = Callable[[str], tuple[bool, str]]
DEFAULT_LLM_EMAIL = DEFAULT_SMOKE_EMAIL.replace("smoke", "llm")
DEFAULT_LLM_USERNAME = DEFAULT_SMOKE_USERNAME.replace("smoke", "llm")


def _contains_all(*phrases: str) -> CheckFn:
    def check(text: str) -> tuple[bool, str]:
        missing = [p for p in phrases if p.lower() not in text.lower()]
        if missing:
            return False, "missing: " + ", ".join(missing)
        return True, "ok"

    return check


def _sentiment_check(text: str) -> tuple[bool, str]:
    required = ("改进", "诉求")
    if not any(word in text for word in required):
        return False, "answer should classify '希望增加更多实战' as 改进/诉求"
    bad_patterns = ("希望增加更多实战是正面", "希望增加更多实战判为正面", "实战'判为正面")
    if any(p in text for p in bad_patterns):
        return False, "answer appears to classify the improvement request as positive"
    return True, "ok"


def _multisheet_check(text: str) -> tuple[bool, str]:
    required = ("课程目录", "报名记录", "学习日志")
    missing = [p for p in required if p not in text]
    if missing:
        return False, "answer did not mention all Excel sheets: " + ", ".join(missing)
    if "无法" in text and ("报名记录" in text or "学习日志" in text):
        return False, "answer still looks like the old missing-sheet failure mode"
    return True, "ok"


def _pick_model_id(client: httpx.Client, headers: dict[str, str], explicit: str | None) -> str:
    if explicit:
        return explicit
    models = []
    last_error = None
    for path in ("/api/models/available", "/api/settings/models"):
        resp = client.get(path, headers=headers)
        if resp.status_code == 200:
            models = resp.json()
            break
        last_error = f"{path}: HTTP {resp.status_code}"
    valid_models = [
        model for model in models
        if str(model.get("id", "")).strip() and str(model.get("model_name", "")).strip()
    ]
    if not valid_models:
        detail = f" Last error: {last_error}." if last_error else ""
        raise RuntimeError(f"No valid visible model found. Run backend/manage.py seed or pass --model-id.{detail}")
    return valid_models[0]["id"]


def _send_message(client: httpx.Client, headers: dict[str, str], conversation_id: str, model_id: str, content: str) -> dict[str, Any]:
    answer_parts: list[str] = []
    thinking_chars = 0
    tool_uses: list[str] = []
    errors: list[str] = []

    with client.stream(
        "POST",
        f"/api/chat/conversations/{conversation_id}/messages",
        headers={**headers, "Accept": "text/event-stream"},
        json={"content": content, "model_id": model_id},
        timeout=180,
    ) as resp:
        _require_status(resp, 200, "send chat message")
        for line in resp.iter_lines():
            if not line or not line.startswith("data: "):
                continue
            payload = line[6:]
            if payload == "[DONE]":
                break
            try:
                event = json.loads(payload)
            except json.JSONDecodeError:
                continue
            event_type = event.get("type")
            if event_type == "text":
                answer_parts.append(event.get("delta", ""))
            elif event_type == "thinking":
                thinking_chars += len(event.get("content", ""))
            elif event_type == "tool_use":
                tool_uses.append(event.get("name", "unknown"))
            elif event_type == "error":
                errors.append(event.get("message", "unknown error"))

    return {
        "answer": "".join(answer_parts),
        "thinking_chars": thinking_chars,
        "tool_uses": tool_uses,
        "errors": errors,
    }


def _create_conversation(client: httpx.Client, headers: dict[str, str], model_id: str, title: str, data_space_id: str | None) -> str:
    resp = client.post(
        "/api/chat/conversations",
        headers=headers,
        json={"data_space_id": data_space_id, "model_id": model_id, "title": title},
    )
    _require_status(resp, 201, f"create conversation {title}")
    return resp.json()["id"]


def _space_name(base: str, run_label: str) -> str:
    return f"{base}-{run_label}" if run_label else base


def _upload_acceptance_materials(ctx: SmokeContext, run_label: str) -> dict[str, str]:
    materials = _materials()
    space_ids: dict[str, str] = {}
    for course, items in materials.items():
        sid = create_space(ctx, _space_name(course, run_label))
        upload_files(ctx, sid, items, course)
        space_ids[course] = sid

    sentiment_csv = (
        "student_id,rating,recommend,comment\n"
        "S001,5,true,老师讲解清晰案例丰富\n"
        "S002,2,false,希望增加更多实战\n"
        "S003,2,false,答疑响应慢\n"
        "S004,4,true,课程节奏合适\n"
    ).encode("utf-8")
    sid = create_space(ctx, _space_name("课程满意度问卷分析", run_label))
    upload_files(ctx, sid, [("course_satisfaction.csv", sentiment_csv, "text/csv")], "sentiment")
    space_ids["课程满意度问卷分析"] = sid
    return space_ids


def run(args: argparse.Namespace) -> dict[str, Any]:
    report: dict[str, Any] = {
        "ok": False,
        "base_url": args.base_url,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "checks": [],
    }
    report.update(_python_runtime_info())
    client = httpx.Client(base_url=args.base_url.rstrip("/"), timeout=60)
    try:
        headers = register_or_login(client, args.email, args.username, args.password)
        model_id = _pick_model_id(client, headers, args.model_id)
        report["model_id"] = model_id
        report["run_label"] = args.run_label

        ctx = SmokeContext(client=client, headers=headers, report=report)
        space_ids = _upload_acceptance_materials(ctx, args.run_label)
        report["space_ids"] = space_ids

        cases: list[dict[str, Any]] = [
            {
                "id": "multisheet_excel_join",
                "space": "线性代数复习",
                "prompt": "请基于 online_course_ops_multisheet.xlsx 的课程目录、报名记录、学习日志三张工作表，说明每门课的报名学生和学习分钟数。请明确你看到了哪几个工作表。",
                "check": _multisheet_check,
            },
            {
                "id": "formula_render_source",
                "space": "计算机体系结构",
                "prompt": "用 LaTeX 写出平均访存时间 AMAT 公式，并结合 cache miss 解释它。",
                "check": _contains_all("AMAT", "Miss", "$"),
            },
            {
                "id": "personalized_study",
                "space": "计算机体系结构",
                "prompt": "我擅长 Python，但没学过硬件，我该如何理解 cache miss？",
                "check": _contains_all("Python", "cache miss"),
            },
            {
                "id": "sentiment_improvement_request",
                "space": "课程满意度问卷分析",
                "prompt": "请统计满意度和推荐率，并对评论做情感/主题分类。特别判断“希望增加更多实战”应该算正面评价还是改进诉求。",
                "check": _sentiment_check,
            },
        ]

        for case in cases:
            conv_id = _create_conversation(
                client,
                headers,
                model_id,
                f"LLM验收-{case['id']}",
                space_ids[case["space"]],
            )
            result = _send_message(client, headers, conv_id, model_id, case["prompt"])
            ok, reason = case["check"](result["answer"])
            case_report = {
                "id": case["id"],
                "space": case["space"],
                "ok": ok and not result["errors"],
                "reason": reason if not result["errors"] else "; ".join(result["errors"]),
                "tool_uses": result["tool_uses"],
                "thinking_chars": result["thinking_chars"],
                "prompt": case["prompt"],
                "answer": result["answer"],
            }
            report["checks"].append(case_report)

        report["ok"] = all(c["ok"] for c in report["checks"])
        return report
    finally:
        client.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run optional real-LLM PKU acceptance checks.")
    parser.add_argument("--base-url", default=os.getenv("DATAMIND_BASE_URL", "http://127.0.0.1:8002"))
    parser.add_argument("--email", default=os.getenv("DATAMIND_LLM_EMAIL", DEFAULT_LLM_EMAIL))
    parser.add_argument("--username", default=os.getenv("DATAMIND_LLM_USERNAME", DEFAULT_LLM_USERNAME))
    parser.add_argument("--password", default=os.getenv("DATAMIND_LLM_PASSWORD", DEFAULT_PASSWORD))
    parser.add_argument("--model-id", default=os.getenv("DATAMIND_LLM_MODEL_ID"))
    parser.add_argument("--run-label", default=os.getenv("DATAMIND_LLM_RUN_LABEL", time.strftime("%Y%m%d%H%M%S")))
    parser.add_argument("--report", default=os.getenv("DATAMIND_LLM_REPORT", "eval/pku_llm_acceptance_report.json"))
    args = parser.parse_args()

    try:
        report = run(args)
    except Exception as exc:
        report = {
            "ok": False,
            "error": str(exc),
            "base_url": args.base_url,
            "ended_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        }
        report.update(_python_runtime_info())
        _write_report(args.report, report)
        print(json.dumps(report, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1

    report["ended_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    _write_report(args.report, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"\nReport written to {args.report}")
    return 0 if report.get("ok") else 1


def _write_report(report_path: str, report: dict[str, Any]) -> None:
    out = Path(report_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
