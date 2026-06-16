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

from common import iter_jsonl, write_jsonl, ensure_dir, FINAL_HEADERS
from generate_net_name import generate_net_name

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

def is_placeholder_net_name(value: str) -> bool:
    text = str(value or "").strip()
    return bool(text) and "line" in text.lower()

def final_net_name(decision: Dict[str, Any], normalized: Dict[str, Any], index: int, selected_pin: str) -> str:
    if not str(selected_pin or "").strip():
        return ""
    decision_net_name = decision_list_value(decision, "net_names", index)
    if decision_net_name and not is_placeholder_net_name(decision_net_name):
        return decision_net_name
    return generate_net_name(normalized, selected_pin)

def expanded_connection_id(base_connection_id: str, original_connection_id: str, should_expand: bool, index: int) -> str:
    if not should_expand:
        return original_connection_id
    base = str(base_connection_id or original_connection_id or "").strip()
    return f"{base}{MULTI_RESULT_CONNECTION_ID_SEPARATOR}{index + 1}" if base else str(index + 1)

def build_final_rows(normalized_path: str | Path, decisions_path: str | Path) -> List[Dict[str, Any]]:
    decisions = {d["line_id"]: d for d in iter_jsonl(decisions_path)}
    rows = []
    for n in iter_jsonl(normalized_path):
        d = decisions.get(n["line_id"], {})
        selected_pins = decision_selected_pins(d) or [""]
        should_expand = len(selected_pins) > 1
        base_connection_id = n.get("base_connection_id") or n.get("connection_id", "")
        for idx, selected_pin in enumerate(selected_pins):
            rows.append({
                "源Block标识": n.get("source_block_id", ""),
                "源Block名称": n.get("source_block_name", ""),
                "源Port": n.get("source_port", ""),
                "目的Block标识": n.get("target_block_id", ""),
                "目的Block名称": n.get("target_block_name", ""),
                "目的Port": n.get("target_port", ""),
                "连线ID": expanded_connection_id(base_connection_id, n.get("connection_id", ""), should_expand, idx),
                "连线名称": n.get("connection_name", ""),
                "连线方向": n.get("direction", ""),
                "原理图Pin脚": selected_pin,
                "分析说明": d.get("analysis", ""),
                "映射置信度": d.get("confidence", ""),
                "网络命名": final_net_name(d, n, idx, selected_pin),
            })
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
    parser = argparse.ArgumentParser()
    parser.add_argument("--normalized", required=True)
    parser.add_argument("--decisions", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    render_outputs(args.normalized, args.decisions, args.output_dir)
    print(f"[OK] rendered flat debug outputs -> {args.output_dir}")

if __name__ == "__main__":
    main()
