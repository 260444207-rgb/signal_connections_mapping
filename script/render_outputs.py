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

def build_final_rows(normalized_path: str | Path, decisions_path: str | Path) -> List[Dict[str, Any]]:
    decisions = {d["line_id"]: d for d in iter_jsonl(decisions_path)}
    rows = []
    for n in iter_jsonl(normalized_path):
        d = decisions.get(n["line_id"], {})
        rows.append({
            "源Block标识": n.get("source_block_id", ""),
            "源Block名称": n.get("source_block_name", ""),
            "源Port": n.get("source_port", ""),
            "目的Block标识": n.get("target_block_id", ""),
            "目的Block名称": n.get("target_block_name", ""),
            "目的Port": n.get("target_port", ""),
            "连线ID": n.get("connection_id", ""),
            "连线名称": n.get("connection_name", ""),
            "连线方向": n.get("direction", ""),
            "原理图Pin脚": d.get("selected_pin", ""),
            "分析说明": d.get("analysis", ""),
            "映射置信度": d.get("confidence", ""),
            "网络命名": d.get("net_name", ""),
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
