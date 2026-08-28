#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from typing import Any

from naming_common import resolve_columns, text
from xlsx_io import patch_workbook, read_workbook_rows


NET_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,30}$")
NAMING_BASIS_MARKER = "网络命名依据："


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    raise ValueError(f"{path} 第 {line_number} 行不是合法 JSON: {exc}") from exc
    return rows


def append_or_replace_basis(analysis: str, basis: str) -> str:
    original = text(analysis)
    if NAMING_BASIS_MARKER in original:
        original = original.split(NAMING_BASIS_MARKER, 1)[0].rstrip("；; ")
    naming_text = f"{NAMING_BASIS_MARKER}{text(basis)}"
    return f"{original}；{naming_text}" if original else naming_text


def apply_naming(input_path: str | Path, task_dir: str | Path, output_path: str | Path) -> dict[str, Any]:
    input_path = Path(input_path).resolve()
    task_dir = Path(task_dir).resolve()
    output_path = Path(output_path).resolve()
    if input_path == output_path:
        raise ValueError("输出路径必须与输入路径不同")

    index_data = json.loads((task_dir / "row_index.json").read_text(encoding="utf-8"))
    indexed_input = Path(index_data.get("input", "")).resolve()
    if indexed_input != input_path:
        return {
            "status": "ERROR",
            "written_rows": 0,
            "errors": [{"id": "", "message": "row_index.json 不属于当前 --input，请重新运行 prepare_naming.py"}],
        }
    row_index = index_data["groups"]
    decisions = read_jsonl(task_dir / "naming_decisions.jsonl")
    by_id: dict[str, dict[str, str]] = {}
    errors: list[dict[str, str]] = []
    for decision in decisions:
        group_id = text(decision.get("id"))
        net_name = text(decision.get("net_name"))
        basis = text(decision.get("basis"))
        if not group_id:
            errors.append({"id": "", "message": "decision 缺少 id"})
            continue
        if group_id in by_id:
            errors.append({"id": group_id, "message": "同一命名组存在重复 decision"})
            continue
        if group_id not in row_index:
            errors.append({"id": group_id, "message": "decision id 不在命名组中"})
        if not NET_RE.fullmatch(net_name):
            errors.append({"id": group_id, "message": "net_name 必须为字母开头、最长31字符的 SCREAMING_SNAKE_CASE"})
        if not basis:
            errors.append({"id": group_id, "message": "basis 不能为空"})
        by_id[group_id] = {"net_name": net_name, "basis": basis}
    for missing in sorted(set(row_index) - set(by_id)):
        errors.append({"id": missing, "message": "缺少命名 decision"})
    if errors:
        return {"status": "ERROR", "written_rows": 0, "errors": errors}

    workbook_rows = read_workbook_rows(input_path)
    columns_by_sheet = {
        sheet: resolve_columns({text(value): column for column, value in rows.get(1, {}).items() if text(value)})
        for sheet, rows in workbook_rows.items()
    }
    for group_id, group_index in row_index.items():
        refs = group_index["refs"]
        allowed_connection_ids = set(group_index["connection_ids"])
        for ref in refs:
            sheet = ref["sheet"]
            if sheet not in columns_by_sheet:
                errors.append({"id": group_id, "message": f"输入 Excel 缺少 sheet: {sheet}"})
                continue
            columns = columns_by_sheet[sheet]
            if columns.get("net_name") != 13:
                errors.append({"id": group_id, "message": f"{sheet} 的网络命名不是第 13 列"})
                continue
            row_number = int(ref["row"])
            current_id = text(workbook_rows[sheet].get(row_number, {}).get(columns.get("connection_id", 0), ""))
            if current_id not in allowed_connection_ids:
                errors.append({"id": group_id, "message": f"{sheet} 第 {row_number} 行连线ID已变为 {current_id}，请重新 prepare"})
    if errors:
        return {"status": "ERROR", "written_rows": 0, "errors": errors}

    changes: dict[str, dict[tuple[int, int], str]] = {}
    written_rows = 0
    for group_id, group_index in row_index.items():
        refs = group_index["refs"]
        decision = by_id[group_id]
        for ref in refs:
            sheet = ref["sheet"]
            columns = columns_by_sheet[sheet]
            row_number = int(ref["row"])
            original_analysis = workbook_rows[sheet].get(row_number, {}).get(columns["analysis"], "")
            sheet_changes = changes.setdefault(sheet, {})
            sheet_changes[(row_number, columns["net_name"])] = decision["net_name"]
            sheet_changes[(row_number, columns["analysis"])] = append_or_replace_basis(original_analysis, decision["basis"])
            written_rows += 1
    patch_workbook(input_path, output_path, changes)
    return {"status": "PASS", "output": str(output_path), "written_rows": written_rows, "group_count": len(row_index), "errors": []}


def main() -> int:
    parser = argparse.ArgumentParser(description="校验组级网络命名 decision 并统一回填所有端点行")
    parser.add_argument("--input", required=True)
    parser.add_argument("--task-dir", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    report = apply_naming(args.input, args.task_dir, args.output)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
