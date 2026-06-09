#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from common import iter_jsonl, write_json, read_json, stable_hash, normalize_text


DEVICE_KEYWORDS = [
    ("PA", ["PA", "POWER_AMPLIFIER", "功放"]),
    ("LNA", ["LNA", "LOW_NOISE_AMPLIFIER", "低噪声"]),
    ("ADC", ["ADC", "ANALOG_DIGITAL", "模数"]),
    ("DAC", ["DAC", "DIGITAL_ANALOG", "数模"]),
    ("PLL", ["PLL"]),
    ("CLOCK", ["CLK", "CLOCK", "REFCLK", "时钟"]),
    ("MCU", ["MCU", "CPU", "PROCESSOR", "控制器"]),
    ("FPGA", ["FPGA", "CPLD"]),
    ("SWITCH", ["SW", "SWITCH", "开关"]),
    ("FILTER", ["FILTER", "滤波"]),
    ("POWER", ["PWR", "POWER", "VCC", "VDD", "电源"]),
    ("GPIO", ["GPIO"]),
    ("CTRL", ["CTRL", "CONTROL", "EN", "ENABLE", "RESET", "RST", "控制"]),
]

FAMILY_KEYWORDS = [
    ("RF_CHAIN", ["RF", "ANT", "TX", "RX", "PA", "LNA"]),
    ("CLOCK_TREE", ["CLK", "CLOCK", "REFCLK", "XO", "TCXO", "晶振"]),
    ("POWER_ENABLE", ["PWR", "POWER", "VCC", "VDD", "EN", "ENABLE", "电源"]),
    ("SPI_CTRL", ["SPI", "SCLK", "MOSI", "MISO", "CS"]),
    ("I2C_CTRL", ["I2C", "IIC", "SCL", "SDA"]),
    ("GPIO_CTRL", ["GPIO"]),
    ("RESET", ["RESET", "RST"]),
    ("INTERRUPT", ["INT", "IRQ", "中断"]),
    ("DIFFERENTIAL_PAIR", ["_P", "_N", "DP", "DN"]),
    ("DATA_BUS", ["DATA", "D[", "BUS"]),
]


def contains_any(text: str, words: List[str]) -> bool:
    upper = text.upper()
    return any(w.upper() in upper for w in words)


def infer_device_category(row: Dict[str, Any]) -> str:
    text = " ".join([
        normalize_text(row.get("source_block_name")),
        normalize_text(row.get("source_block_id")),
        normalize_text(row.get("target_block_name")),
        normalize_text(row.get("target_block_id")),
        normalize_text(row.get("source_port")),
        normalize_text(row.get("target_port")),
    ])
    for category, words in DEVICE_KEYWORDS:
        if contains_any(text, words):
            return category
    return "UNKNOWN"


def infer_mapping_family(row: Dict[str, Any]) -> str:
    text = " ".join([
        normalize_text(row.get("source_port")),
        normalize_text(row.get("target_port")),
        normalize_text(row.get("connection_name")),
        normalize_text(row.get("source_block_name")),
        normalize_text(row.get("target_block_name")),
    ])
    for family, words in FAMILY_KEYWORDS:
        if contains_any(text, words):
            return family
    return "UNKNOWN"


def choose_subagent(mapping_family: str, line_ids: List[str], hard_case: bool = False) -> tuple[str, str]:
    if hard_case:
        return "semantic-hard-case-subagent", "prompts/semantic_mapping_resolver.md"
    return "semantic-mapping-subagent", "prompts/semantic_mapping_resolver.md"


def load_hard_case_line_ids(needs_model_path: str | Path | None) -> set[str]:
    if not needs_model_path:
        return set()
    p = Path(needs_model_path)
    if not p.exists():
        return set()
    return {row.get("line_id", "") for row in iter_jsonl(p) if row.get("line_id")}


def build_analysis_context_groups(
    normalized_path: str | Path,
    output_path: str | Path,
    needs_model_path: str | Path | None = None
) -> Dict[str, Any]:
    rows = list(iter_jsonl(normalized_path))
    hard_cases = load_hard_case_line_ids(needs_model_path)

    buckets: Dict[Tuple[str, str, str], List[Dict[str, Any]]] = defaultdict(list)

    for row in rows:
        device_category = infer_device_category(row)
        mapping_family = infer_mapping_family(row)
        is_hard = row.get("line_id") in hard_cases
        isolation_level = "hard_case" if is_hard else "device_category_and_mapping_family"
        key = (device_category, mapping_family, isolation_level)
        buckets[key].append(row)

    context_groups = []
    for (device_category, mapping_family, isolation_level), group_rows in buckets.items():
        line_ids = [r["line_id"] for r in group_rows]
        source_sheets = sorted({r.get("source_sheet_name") or r.get("output_sheet_name") or "" for r in group_rows if r.get("source_sheet_name") or r.get("output_sheet_name")})
        source_block_ids = sorted({r.get("source_block_id", "") for r in group_rows if r.get("source_block_id")})

        subagent, prompt_file = choose_subagent(
            mapping_family,
            line_ids,
            hard_case=(isolation_level == "hard_case")
        )
        context_group_id = "CTX_" + stable_hash({
            "device_category": device_category,
            "mapping_family": mapping_family,
            "isolation_level": isolation_level,
            "source_sheets": source_sheets,
            "line_ids": line_ids[:20],
        })

        context_groups.append({
            "context_group_id": context_group_id,
            "device_category": device_category,
            "mapping_family": mapping_family,
            "isolation_level": isolation_level,
            "source_sheets": source_sheets,
            "source_block_ids": source_block_ids,
            "line_ids": line_ids,
            "recommended_subagent": subagent,
            "prompt_file": prompt_file,
            "notes": "context_group 仅用于模型上下文隔离，不用于最终输出分页。"
        })

    result = {"context_groups": context_groups}
    write_json(output_path, result)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--normalized", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--needs-model", default="")
    args = parser.parse_args()

    result = build_analysis_context_groups(
        args.normalized,
        args.output,
        args.needs_model or None
    )
    print(f"[OK] analysis context groups: {len(result['context_groups'])} -> {args.output}")


if __name__ == "__main__":
    main()
