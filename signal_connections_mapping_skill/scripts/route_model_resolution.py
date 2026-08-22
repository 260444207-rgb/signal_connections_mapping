#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse

from common import (
    iter_jsonl,
    load_pin_catalog,
    pins_for_part,
    resolve_catalog_key,
    write_jsonl,
)


def route_model_resolution(normalized_path, pins_path, decisions_out, needs_model_out):
    """按 pin_info 门禁路由；只预裁决 source_port 与单 pin 事实完全相同的连接。"""
    pin_catalog = load_pin_catalog(pins_path)
    decisions = []
    needs_model = []

    for row in iter_jsonl(normalized_path):
        line_id = row["line_id"]
        source_part_id = row.get("source_part_id", "")
        resolved_part_id = resolve_catalog_key(pin_catalog, source_part_id)
        source_pins = pins_for_part(pin_catalog, source_part_id)
        signal_shape_info = (
            row.get("signal_shape_info", {})
            if isinstance(row.get("signal_shape_info", {}), dict)
            else {}
        )
        signal_shape = signal_shape_info.get("shape", row.get("signal_shape", "scalar"))
        source_port = str(row.get("source_port", "") or "").strip()
        is_single_pin_shape = (
            signal_shape == "scalar"
            or bool(signal_shape_info.get("is_expanded_member", False))
        )
        exact_source_port_pin = (
            bool(source_port)
            and source_port in source_pins
            and is_single_pin_shape
            and not bool(signal_shape_info.get("needs_model_shape_review", False))
        )

        if not source_pins:
            decisions.append({
                "line_id": line_id,
                "selected_pin": "",
                "decision_type": "unresolved",
                "confidence": "Low",
                "analysis": (
                    "入参 pin_info.json 中未找到源端器件编码 "
                    f"{source_part_id} / {resolved_part_id or source_part_id} 的 pin 列表，"
                    "跳过该器件的语义模型分析。"
                ),
                "net_name": "",
                "needs_human_review": True,
            })
            continue

        if exact_source_port_pin:
            decisions.append({
                "line_id": line_id,
                "selected_pin": source_port,
                "selected_pins": [],
                "decision_type": "pre_resolved",
                "confidence": "High",
                "analysis": (
                    "source_port 与当前源端器件 pin_info 中的单 pin 名逐字一致；"
                    "这是直接连接事实，不再进行二级语义映射。"
                ),
                "net_name": "",
                "net_names": [],
                "needs_human_review": False,
            })
            continue

        decisions.append({
            "line_id": line_id,
            "selected_pin": "",
            "decision_type": "unresolved",
            "confidence": "Low",
            "analysis": "已通过 pin_info 门禁，等待隔离语义模型分析。",
            "net_name": "",
            "needs_human_review": True,
        })
        needs_model.append({
            "line_id": line_id,
            "reason": f"needs_semantic_model_resolution_for_{signal_shape}",
        })

    write_jsonl(decisions_out, decisions)
    write_jsonl(needs_model_out, needs_model)


def main():
    parser = argparse.ArgumentParser(
        description="Route pin-backed connections to semantic model resolution."
    )
    parser.add_argument("--normalized", required=True)
    parser.add_argument("--pins", required=True)
    parser.add_argument("--decisions-out", required=True)
    parser.add_argument("--needs-model-out", required=True)
    args = parser.parse_args()
    route_model_resolution(
        args.normalized,
        args.pins,
        args.decisions_out,
        args.needs_model_out,
    )
    print("[OK] model resolution routing finished")


if __name__ == "__main__":
    main()
