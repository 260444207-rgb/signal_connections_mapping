#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

from common import ensure_dir, write_json, write_jsonl


def read_json(path: str | Path, default: Any = None) -> Any:
    p = Path(path)
    if not p.exists():
        return default
    return json.loads(p.read_text(encoding="utf-8"))


def read_jsonl_with_errors(path: str | Path) -> Tuple[List[Dict[str, Any]], List[str]]:
    p = Path(path)
    rows: List[Dict[str, Any]] = []
    errors: List[str] = []
    if not p.exists():
        return rows, [f"missing output file: {p}"]
    with p.open("r", encoding="utf-8") as handle:
        for idx, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                errors.append(f"line {idx}: invalid JSONL object: {exc}")
                continue
            if not isinstance(row, dict):
                errors.append(f"line {idx}: JSONL row must be an object")
                continue
            rows.append(row)
    return rows, errors


def expected_output_file(task: Dict[str, Any], plan_path: Path) -> Path:
    contract = task.get("output_contract") if isinstance(task.get("output_contract"), dict) else {}
    output_file = task.get("output_file") or contract.get("output_file")
    if output_file:
        return Path(output_file)
    task_id = task.get("task_id") or Path(task.get("task_json", "TASK_UNKNOWN.json")).stem
    return plan_path.parent.parent / "subagent_outputs" / f"{task_id}.jsonl"


def validate_task_output(task: Dict[str, Any], plan_path: Path) -> Dict[str, Any]:
    output_file = expected_output_file(task, plan_path)
    expected_ids = [str(x) for x in task.get("line_ids", [])]
    expected_set = set(expected_ids)
    rows, parse_errors = read_jsonl_with_errors(output_file)
    line_ids = [str(row.get("line_id", "")) for row in rows]
    parent_line_ids = [str(row.get("parent_line_id", "")) for row in rows]
    actual_set = set(line_ids)
    duplicate_ids = sorted({line_id for line_id in line_ids if line_ids.count(line_id) > 1 and line_id})
    covered_expected = set()
    extra_ids = []
    for row in rows:
        line_id = str(row.get("line_id", ""))
        parent_line_id = str(row.get("parent_line_id", ""))
        if line_id in expected_set:
            covered_expected.add(line_id)
            continue
        if parent_line_id in expected_set:
            covered_expected.add(parent_line_id)
            continue
        if line_id:
            extra_ids.append(line_id)
    missing_ids = sorted(expected_set - covered_expected)
    extra_ids = sorted(set(extra_ids))
    blank_line_ids = sum(1 for line_id in line_ids if not line_id)

    errors = list(parse_errors)
    if duplicate_ids:
        errors.append(f"duplicate line_id: {', '.join(duplicate_ids)}")
    if missing_ids:
        errors.append(f"missing line_id: {', '.join(missing_ids)}")
    if extra_ids:
        errors.append(f"extra line_id: {', '.join(extra_ids)}")
    if blank_line_ids:
        errors.append(f"blank line_id rows: {blank_line_ids}")

    return {
        "status": "PASS" if not errors else "FAIL",
        "task_id": task.get("task_id", ""),
        "task_display_name": task.get("task_display_name", ""),
        "context_group_id": task.get("context_group_id", ""),
        "task_json": task.get("task_json", ""),
        "prompt_file": task.get("prompt_file", ""),
        "output_file": str(output_file),
        "expected_line_count": len(expected_ids),
        "actual_line_count": len(rows),
        "covered_expected_line_count": len(covered_expected),
        "missing_line_ids": missing_ids,
        "extra_line_ids": extra_ids,
        "duplicate_line_ids": duplicate_ids,
        "parent_line_ids": sorted({x for x in parent_line_ids if x}),
        "errors": errors,
    }


def expected_session_status_file(plan: Dict[str, Any], plan_path: Path) -> Path:
    status_file = plan.get("subagent_session_status_json")
    if status_file:
        return Path(status_file)
    return plan_path.parent / "subagent_session_status.json"


def validate_session_status(plan: Dict[str, Any], plan_path: Path) -> Dict[str, Any]:
    status_file = expected_session_status_file(plan, plan_path)
    expected_by_session: Dict[str, set[str]] = {}
    for task in plan.get("tasks", []):
        session_id = str(task.get("subagent_session_id", ""))
        if not session_id:
            continue
        expected_by_session.setdefault(session_id, set()).add(str(task.get("task_id", "")))

    if not expected_by_session:
        return {"status": "PASS", "status_file": str(status_file), "sessions": []}

    if not status_file.exists():
        return {
            "status": "FAIL",
            "status_file": str(status_file),
            "sessions": [],
            "errors": [f"missing subagent session status file: {status_file}"],
        }

    status = read_json(status_file, {})
    sessions = status.get("sessions", []) if isinstance(status, dict) else []
    actual_by_session = {
        str(session.get("subagent_session_id", "")): session
        for session in sessions
        if isinstance(session, dict)
    }

    session_reports: List[Dict[str, Any]] = []
    errors: List[str] = []
    for session_id, expected_task_ids in sorted(expected_by_session.items()):
        session = actual_by_session.get(session_id)
        if not session:
            message = f"missing session status: {session_id}"
            errors.append(message)
            session_reports.append({"subagent_session_id": session_id, "status": "FAIL", "errors": [message]})
            continue

        session_errors: List[str] = []
        completed_task_ids = {str(x) for x in session.get("completed_task_ids", [])}
        missing_completed = sorted(expected_task_ids - completed_task_ids)
        if not session.get("spawned", False):
            session_errors.append("spawned is not true")
        if not session.get("completed", False):
            session_errors.append("completed is not true")
        if session.get("failed", False):
            session_errors.append("failed is true")
        if session.get("timed_out", False):
            session_errors.append("timed_out is true")
        if session.get("rerun_required", False):
            session_errors.append("rerun_required is true")
        if missing_completed:
            session_errors.append("completed_task_ids missing: " + ", ".join(missing_completed))
        if session_errors:
            errors.extend(f"{session_id}: {message}" for message in session_errors)
        session_reports.append({
            "subagent_session_id": session_id,
            "status": "PASS" if not session_errors else "FAIL",
            "expected_task_count": len(expected_task_ids),
            "completed_task_count": len(completed_task_ids & expected_task_ids),
            "errors": session_errors,
        })

    return {
        "status": "PASS" if not errors else "FAIL",
        "status_file": str(status_file),
        "sessions": session_reports,
        "errors": errors,
    }


def render_rerun_plan(failed_tasks: List[Dict[str, Any]], session_status_report: Dict[str, Any] | None = None) -> str:
    lines = [
        "# Failed Subagent Rerun Plan",
        "",
        "这些 subagent 输出或 session 状态没有通过主控检查。必须重新启动/等待对应 TASK 的语义分析，写入对应 output_file，并把 subagent_session_status.json 更新为完成后再运行 finish。",
        "",
        "| # | task | context_group | expected | actual | output_file | task_json | prompt | failure |",
        "|---|---|---|---:|---:|---|---|---|---|",
    ]
    for idx, task in enumerate(failed_tasks, start=1):
        failure = "; ".join(task.get("errors", [])) or "unknown failure"
        lines.append(
            "| {idx} | {task} | {context} | {expected} | {actual} | {output_file} | {task_json} | {prompt} | {failure} |".format(
                idx=idx,
                task=str(task.get("task_display_name") or task.get("task_id") or "").replace("|", "/"),
                context=str(task.get("context_group_id", "")).replace("|", "/"),
                expected=task.get("expected_line_count", 0),
                actual=task.get("actual_line_count", 0),
                output_file=str(task.get("output_file", "")).replace("|", "/"),
                task_json=str(task.get("task_json", "")).replace("|", "/"),
                prompt=str(task.get("prompt_file", "")).replace("|", "/"),
                failure=failure.replace("|", "/"),
            )
        )
    lines.append("")
    if session_status_report and session_status_report.get("status") != "PASS":
        lines.append("## Session 状态门禁失败")
        lines.append("")
        lines.append(f"- status_file: `{session_status_report.get('status_file', '')}`")
        for error in session_status_report.get("errors", []):
            lines.append(f"- {error}")
        lines.append("")
    lines.append("重启要求：每个失败 subagent 必须用 sessions_spawn 重新启动或等待完成，超时 30 分钟；只读取自己的 task_json，并把 JSONL 写入 output_file。完成后更新 subagent_session_status.json；不要在聊天中粘贴结果代替写文件。")
    return "\n".join(lines)


def check_subagent_outputs(
    plan_path: str | Path,
    merged_output_path: str | Path,
    report_path: str | Path,
    rerun_plan_path: str | Path,
) -> Dict[str, Any]:
    plan_path = Path(plan_path)
    plan = read_json(plan_path, {"tasks": []})
    tasks = plan.get("tasks", [])
    session_status_report = validate_session_status(plan, plan_path)
    task_reports = [validate_task_output(task, plan_path) for task in tasks]
    failed_tasks = [task for task in task_reports if task["status"] != "PASS"]
    session_status_failed = session_status_report.get("status") != "PASS"

    report = {
        "status": "PASS" if not failed_tasks and not session_status_failed else "FAIL",
        "task_count": len(task_reports),
        "failed_task_count": len(failed_tasks),
        "session_status": session_status_report,
        "expected_line_count": sum(task.get("expected_line_count", 0) for task in task_reports),
        "actual_line_count": sum(task.get("actual_line_count", 0) for task in task_reports),
        "tasks": task_reports,
    }
    write_json(report_path, report)

    rerun_plan_path = Path(rerun_plan_path)
    ensure_dir(rerun_plan_path.parent)
    if failed_tasks or session_status_failed:
        rerun_plan_path.write_text(render_rerun_plan(failed_tasks, session_status_report), encoding="utf-8")
        return report
    rerun_plan_path.write_text("# Failed Subagent Rerun Plan\n\nNo failed subagent tasks.\n", encoding="utf-8")

    merged_rows: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for task_report in task_reports:
        rows, _ = read_jsonl_with_errors(task_report["output_file"])
        for row in rows:
            line_id = str(row.get("line_id", ""))
            if line_id in seen:
                continue
            seen.add(line_id)
            merged_rows.append(row)
    write_jsonl(merged_output_path, merged_rows)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate subagent output files and merge them into model_resolved_decisions.jsonl.")
    parser.add_argument("--plan", required=True)
    parser.add_argument("--merged-output", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--rerun-plan", required=True)
    args = parser.parse_args()
    report = check_subagent_outputs(args.plan, args.merged_output, args.report, args.rerun_plan)
    if report["status"] != "PASS":
        print(f"[FAIL] subagent outputs failed: {report['failed_task_count']} task(s). See {args.report} and {args.rerun_plan}")
        raise SystemExit(2)
    print(f"[OK] subagent outputs checked and merged -> {args.merged_output}")


if __name__ == "__main__":
    main()
