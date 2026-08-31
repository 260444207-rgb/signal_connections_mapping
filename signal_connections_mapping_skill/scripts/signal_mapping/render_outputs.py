#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
调试用平铺输出脚本。
正式信号接口列表请使用 render_template_sheets.py，
它会严格按照输入框图 Excel 的原 sheet 结构写入。
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Dict, Any, List

from .common import iter_jsonl, write_jsonl, ensure_dir, FINAL_HEADERS

MULTI_RESULT_CONNECTION_ID_SEPARATOR = "#"

def decision_selected_pins(decision):
    pins = decision.get("selected_pins")
    if isinstance(pins, list) and pins:
        return [str(pin).strip() for pin in pins if str(pin).strip()]
    pin = str(decision.get("selected_pin", "") or "").strip()
    return [pin] if pin else []

def decision_list_value(decision: Dict[str, Any], key: str, index: int, default: str = "") -> str:
    values = decision.get(key)
    if isinstance(values, list) and index < len(values):
        return str(values[index] or "")
    return str(decision.get(key[:-1] if key.endswith("s") else key, default) or default)

def expanded_connection_id(base_connection_id: str, original_connection_id: str, should_expand: bool, index: int) -> str:
    if not should_expand:
        return original_connection_id
    base = str(base_connection_id or original_connection_id or "").strip()
    return f"{base}{MULTI_RESULT_CONNECTION_ID_SEPARATOR}{index + 1}" if base else str(index + 1)

def normalize_selected_pins_for_row(normalized: Dict[str, Any], selected_pins: List[str]) -> tuple[List[str], int]:
    shape_info = normalized.get("signal_shape_info", {})
    if not isinstance(shape_info, dict) or not shape_info.get("is_expanded_member"):
        return selected_pins, 0
    if len(selected_pins) <= 1:
        return selected_pins, 0
    member_index = int(shape_info.get("member_index", 1) or 1) - 1
    member_index = max(0, min(member_index, len(selected_pins) - 1))
    return [selected_pins[member_index]], member_index

def inferred_parent_line_id(line_id: str) -> str:
    text = str(line_id or "")
    if "#" not in text:
        return ""
    parent, suffix = text.rsplit("#", 1)
    return parent if parent and suffix.isdigit() else ""

def decision_parent_line_id(decision: Dict[str, Any]) -> str:
    return str(decision.get("parent_line_id", "") or "").strip() or inferred_parent_line_id(decision.get("line_id", ""))

def child_decision_index(decision: Dict[str, Any]) -> int:
    line_id = str(decision.get("line_id", "") or "")
    if "#" not in line_id:
        return 0
    suffix = line_id.rsplit("#", 1)[1]
    return int(suffix) - 1 if suffix.isdigit() else 0

def display_connection_id_for_decision(normalized: Dict[str, Any], decision: Dict[str, Any]) -> str:
    parent = decision_parent_line_id(decision)
    line_id = str(decision.get("line_id", "") or "")
    if parent and line_id.startswith(parent + "#"):
        suffix = line_id.rsplit("#", 1)[1]
        base = str(normalized.get("base_connection_id") or normalized.get("connection_id") or "").strip()
        return f"{base}#{suffix}" if base else line_id
    return normalized.get("connection_id", "")

def group_child_decisions(decisions: Dict[str, Dict[str, Any]], normalized_ids: set[str]) -> Dict[str, List[Dict[str, Any]]]:
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for decision in decisions.values():
        line_id = decision.get("line_id", "")
        if line_id in normalized_ids:
            continue
        parent = decision_parent_line_id(decision)
        if parent:
            grouped.setdefault(parent, []).append(decision)
    for items in grouped.values():
        items.sort(key=lambda item: child_decision_index(item))
    return grouped

def rows_for_decision(normalized: Dict[str, Any], decision: Dict[str, Any], connection_id: str | None = None) -> List[Dict[str, Any]]:
    selected_pins, decision_index_offset = normalize_selected_pins_for_row(normalized, decision_selected_pins(decision) or [""])
    should_expand = len(selected_pins) > 1
    base_connection_id = normalized.get("base_connection_id") or normalized.get("connection_id", "")
    rows: List[Dict[str, Any]] = []
    for idx, selected_pin in enumerate(selected_pins):
        decision_index = decision_index_offset + idx
        rows.append({
            "源Block标识": normalized.get("source_block_id", ""),
            "源Block名称": normalized.get("source_block_name", ""),
            "源Port": normalized.get("source_port", ""),
            "目的Block标识": normalized.get("target_block_id", ""),
            "目的Block名称": normalized.get("target_block_name", ""),
            "目的Port": normalized.get("target_port", ""),
            "连线ID": connection_id or expanded_connection_id(base_connection_id, normalized.get("connection_id", ""), should_expand, idx),
            "连线名称": normalized.get("connection_name", ""),
            "连线方向": normalized.get("direction", ""),
            "连线属性": normalized.get("connection_attribute", ""),
            "原理图Pin脚": selected_pin,
            "分析说明": decision_list_value(decision, "analyses", decision_index, decision.get("analysis", "")),
            "映射置信度": decision_list_value(decision, "confidences", decision_index, decision.get("confidence", "")),
            "网络命名": "",
        })
    return rows

def build_final_rows(normalized_path: str | Path, decisions_path: str | Path) -> List[Dict[str, Any]]:
    decisions = {d["line_id"]: d for d in iter_jsonl(decisions_path)}
    normalized_rows = list(iter_jsonl(normalized_path))
    normalized_ids = {row["line_id"] for row in normalized_rows}
    child_decisions = group_child_decisions(decisions, normalized_ids)
    rows = []
    for n in normalized_rows:
        children = child_decisions.get(n["line_id"], [])
        if children:
            for child in children:
                rows.extend(rows_for_decision(n, child, display_connection_id_for_decision(n, child)))
            continue
        rows.extend(rows_for_decision(n, decisions.get(n["line_id"], {})))
    return rows

def render_outputs(normalized_path: str | Path, decisions_path: str | Path, output_dir: str | Path) -> None:
    out = Path(output_dir)
    ensure_dir(out)
    rows = build_final_rows(normalized_path, decisions_path)
    write_jsonl(out / "final_mapping_rows.jsonl", rows)
    with (out / "mapping_result_flat.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FINAL_HEADERS)
        writer.writeheader()
        writer.writerows(rows)

def main():
    parser = argparse.ArgumentParser(description="仅用于调试的平铺 CSV 输出；不能生成正式信号接口列表")
    parser.add_argument("--normalized", required=True)
    parser.add_argument("--decisions", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument(
        "--debug-only-confirm",
        action="store_true",
        help="确认该输出仅用于调试；正式输出必须执行 finish_command.txt",
    )
    args = parser.parse_args()
    if not args.debug_only_confirm:
        parser.error(
            "render_outputs.py cannot produce the formal workbook. "
            "Execute intermediate/finish_command.txt instead. "
            "For an intentional debug CSV only, add --debug-only-confirm."
        )
    render_outputs(args.normalized, args.decisions, args.output_dir)
    print(f"[OK] rendered flat debug outputs -> {args.output_dir}")

if __name__ == "__main__":
    main()
