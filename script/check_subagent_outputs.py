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
    actual_set = set(line_ids)
    duplicate_ids = sorted({line_id for line_id in line_ids if line_ids.count(line_id) > 1 and line_id})
    missing_ids = sorted(expected_set - actual_set)
    extra_ids = sorted(actual_set - expected_set)
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
        "missing_line_ids": missing_ids,
        "extra_line_ids": extra_ids,
        "duplicate_line_ids": duplicate_ids,
        "errors": errors,
    }


def render_rerun_plan(failed_tasks: List[Dict[str, Any]]) -> str:
    lines = [
        "# Failed Subagent Rerun Plan",
        "",
        "这些 subagent 输出没有通过主控检查。必须重新启动这些 TASK 的语义分析，写入对应 output_file 后再运行 finish。",
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
    lines.append("重启要求：每个失败 subagent 只读取自己的 task_json，并把 JSONL 写入 output_file；不要在聊天中粘贴结果代替写文件。")
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
    task_reports = [validate_task_output(task, plan_path) for task in tasks]
    failed_tasks = [task for task in task_reports if task["status"] != "PASS"]

    report = {
        "status": "PASS" if not failed_tasks else "FAIL",
        "task_count": len(task_reports),
        "failed_task_count": len(failed_tasks),
        "expected_line_count": sum(task.get("expected_line_count", 0) for task in task_reports),
        "actual_line_count": sum(task.get("actual_line_count", 0) for task in task_reports),
        "tasks": task_reports,
    }
    write_json(report_path, report)

    rerun_plan_path = Path(rerun_plan_path)
    ensure_dir(rerun_plan_path.parent)
    if failed_tasks:
        rerun_plan_path.write_text(render_rerun_plan(failed_tasks), encoding="utf-8")
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
