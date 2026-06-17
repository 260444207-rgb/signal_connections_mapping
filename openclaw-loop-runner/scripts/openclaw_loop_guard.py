#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Tuple


def ensure_dir(path: str | Path) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def read_json(path: str | Path, default: Any = None) -> Any:
    p = Path(path)
    if not p.exists():
        return default
    return json.loads(p.read_text(encoding="utf-8"))


def write_json(path: str | Path, obj: Any) -> None:
    p = Path(path)
    ensure_dir(p.parent)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def write_jsonl(path: str | Path, rows: List[Dict[str, Any]]) -> None:
    p = Path(path)
    ensure_dir(p.parent)
    with p.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_jsonl(path: str | Path) -> Tuple[List[Dict[str, Any]], List[str]]:
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


def expected_ids_for_task(task: Dict[str, Any]) -> List[str]:
    contract = task.get("output_contract") if isinstance(task.get("output_contract"), dict) else {}
    ids = contract.get("expected_line_ids") or contract.get("expected_ids") or task.get("line_ids") or task.get("item_ids") or []
    return [str(item) for item in ids]


def output_file_for_task(task: Dict[str, Any]) -> str:
    contract = task.get("output_contract") if isinstance(task.get("output_contract"), dict) else {}
    return str(task.get("output_file") or contract.get("output_file") or "")


def id_field_for_task(task: Dict[str, Any]) -> str:
    contract = task.get("output_contract") if isinstance(task.get("output_contract"), dict) else {}
    return str(contract.get("id_field") or task.get("id_field") or "line_id")


def validate_task(task: Dict[str, Any]) -> Dict[str, Any]:
    task_id = str(task.get("task_id") or task.get("id") or "")
    output_file = output_file_for_task(task)
    id_field = id_field_for_task(task)
    expected_ids = expected_ids_for_task(task)
    expected_set = set(expected_ids)

    rows, parse_errors = read_jsonl(output_file) if output_file else ([], ["missing output_contract.output_file"])
    actual_ids = [str(row.get(id_field, "")) for row in rows]
    actual_set = set(actual_ids)
    duplicate_ids = sorted({item_id for item_id in actual_ids if item_id and actual_ids.count(item_id) > 1})
    missing_ids = sorted(expected_set - actual_set)
    extra_ids = sorted(actual_set - expected_set)
    blank_id_count = sum(1 for item_id in actual_ids if not item_id)

    errors = list(parse_errors)
    if duplicate_ids:
        errors.append(f"duplicate {id_field}: {', '.join(duplicate_ids)}")
    if missing_ids:
        errors.append(f"missing {id_field}: {', '.join(missing_ids)}")
    if extra_ids:
        errors.append(f"extra {id_field}: {', '.join(extra_ids)}")
    if blank_id_count:
        errors.append(f"blank {id_field} rows: {blank_id_count}")

    return {
        "status": "PASS" if not errors else "FAIL",
        "task_id": task_id,
        "task_json": task.get("task_json", ""),
        "prompt_file": task.get("prompt_file", ""),
        "output_file": output_file,
        "id_field": id_field,
        "expected_count": len(expected_ids),
        "actual_count": len(rows),
        "missing_ids": missing_ids,
        "extra_ids": extra_ids,
        "duplicate_ids": duplicate_ids,
        "errors": errors,
    }


def render_rerun_plan(failed: List[Dict[str, Any]]) -> str:
    lines = [
        "# Failed Task Rerun Plan",
        "",
        "Restart only these failed tasks. Each worker must write the exact output_file before the final gate can pass.",
        "",
        "| # | task_id | expected | actual | output_file | task_json | failure |",
        "|---|---|---:|---:|---|---|---|",
    ]
    for idx, task in enumerate(failed, start=1):
        failure = "; ".join(task.get("errors", [])) or "unknown failure"
        lines.append(
            "| {idx} | {task_id} | {expected} | {actual} | {output_file} | {task_json} | {failure} |".format(
                idx=idx,
                task_id=str(task.get("task_id", "")).replace("|", "/"),
                expected=task.get("expected_count", 0),
                actual=task.get("actual_count", 0),
                output_file=str(task.get("output_file", "")).replace("|", "/"),
                task_json=str(task.get("task_json", "")).replace("|", "/"),
                failure=failure.replace("|", "/"),
            )
        )
    return "\n".join(lines) + "\n"


def check(plan: str | Path, merged_output: str | Path, report: str | Path, rerun_plan: str | Path) -> Dict[str, Any]:
    plan_obj = read_json(plan, {"tasks": []})
    tasks = plan_obj.get("tasks", [])
    task_reports = [validate_task(task) for task in tasks]
    failed = [task for task in task_reports if task["status"] != "PASS"]
    result = {
        "status": "PASS" if not failed else "FAIL",
        "task_count": len(task_reports),
        "failed_task_count": len(failed),
        "expected_count": sum(task.get("expected_count", 0) for task in task_reports),
        "actual_count": sum(task.get("actual_count", 0) for task in task_reports),
        "tasks": task_reports,
    }
    write_json(report, result)

    rerun_path = Path(rerun_plan)
    ensure_dir(rerun_path.parent)
    if failed:
        rerun_path.write_text(render_rerun_plan(failed), encoding="utf-8")
        return result

    rerun_path.write_text("# Failed Task Rerun Plan\n\nNo failed tasks.\n", encoding="utf-8")
    merged_rows: List[Dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for task_report in task_reports:
        id_field = task_report["id_field"]
        rows, _ = read_jsonl(task_report["output_file"])
        for row in rows:
            key = (id_field, str(row.get(id_field, "")))
            if key in seen:
                continue
            seen.add(key)
            merged_rows.append(row)
    write_jsonl(merged_output, merged_rows)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="OpenClaw loop guard: verify worker output contracts and merge passing outputs.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    check_parser = subparsers.add_parser("check")
    check_parser.add_argument("--plan", required=True)
    check_parser.add_argument("--merged-output", required=True)
    check_parser.add_argument("--report", required=True)
    check_parser.add_argument("--rerun-plan", required=True)

    args = parser.parse_args()
    if args.command == "check":
        result = check(args.plan, args.merged_output, args.report, args.rerun_plan)
        if result["status"] != "PASS":
            print(f"[FAIL] {result['failed_task_count']} task(s) failed. See {args.rerun_plan}")
            raise SystemExit(2)
        print(f"[OK] all tasks passed. Merged output -> {args.merged_output}")


if __name__ == "__main__":
    main()
