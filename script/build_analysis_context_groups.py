#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from common import iter_jsonl, write_json, stable_hash, normalize_text


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

LINK_FAMILY_KEYWORDS = [
    ("RF_TX_CHAIN", ["TXVGA", "TX VGA", "DAC", "RFIN", "RFOUT", "TX_AFE", "TX_SW"]),
    ("FEEDBACK_CHAIN", ["SP9T", "FBV", "ADC_FB", "反馈", "FBSW", "FB00", "FB01", "FB02", "FB03", "FB04", "FB05", "FB06", "FB07"]),
    ("PA_CONTROL_CHAIN", ["PA_SW", "PAPD", "PA_PD", "功放", "PA_SW_AB"]),
    ("SROC_DRIVER_CONTROL_CHAIN", ["集成驱动", "HBF", "PWRSAVE", "ALERT", "SIO", "IN_A-D"]),
    ("CAL_SWITCH_CHAIN", ["TXCAL", "RXCAL", "SW-SROC", "CAL_SW"]),
    ("SPI_CONTROL_CHAIN", ["SPI", "HAC_SPI", "AMC7964"]),
    ("POWER_CHAIN", ["VDD", "VCC", "PWR", "PMU", "比邻星", "天狼星", "VOUT"]),
    ("CLOCK_CHAIN", ["CLK", "CLOCK", "REFCLK", "XO", "TCXO"]),
]


def device_signature(part_id: Any, missing_label: str) -> str:
    part = normalize_text(part_id)
    if part:
        return f"DEVICE_INFO:{part.upper()}"
    return missing_label


def context_signature(prefix: str, *values: Any) -> str:
    for value in values:
        text = normalize_text(value)
        if text:
            return f"{prefix}:{text.upper()}"
    return f"{prefix}:UNKNOWN"


def source_analysis_signature(row: Dict[str, Any]) -> str:
    """
    context_group 的硬边界是“源端器件 pin 体系”。

    如果能从 block_info 找到 source_part_id，则同料号实例合并分析；
    如果找不到，则按 sheet/block 上下文隔离未知源端，避免所有未知器件混在一起。
    """
    part = normalize_text(row.get("source_part_id"))
    if part:
        return f"DEVICE_INFO:{part.upper()}"
    return context_signature(
        "UNKNOWN_SOURCE",
        row.get("source_sheet_name"),
        row.get("source_block_id"),
        row.get("source_block_name"),
    )


def infer_mapping_family(row: Dict[str, Any]) -> str:
    text = " ".join([
        normalize_text(row.get("source_port")),
        normalize_text(row.get("target_port")),
        normalize_text(row.get("connection_name")),
        normalize_text(row.get("source_block_name")),
        normalize_text(row.get("target_block_name")),
    ])
    for family, words in FAMILY_KEYWORDS:
        upper = text.upper()
        if any(w.upper() in upper for w in words):
            return family
    return "UNKNOWN"


def row_text(row: Dict[str, Any]) -> str:
    return " ".join([
        normalize_text(row.get("source_block_name")),
        normalize_text(row.get("source_block_id")),
        normalize_text(row.get("source_port")),
        normalize_text(row.get("target_block_name")),
        normalize_text(row.get("target_block_id")),
        normalize_text(row.get("target_port")),
        normalize_text(row.get("connection_name")),
    ]).upper()


def infer_link_family(row: Dict[str, Any], mapping_family: str) -> str:
    explicit = normalize_text(row.get("link_family_id"))
    if explicit:
        return explicit
    text = row_text(row)
    for family, words in LINK_FAMILY_KEYWORDS:
        if any(word.upper() in text for word in words):
            return family
    if mapping_family in {"RF_CHAIN", "SPI_CTRL", "POWER_ENABLE", "CLOCK_TREE"}:
        return mapping_family
    return "LOCAL_DEVICE_MAPPING"


def link_family_source(row: Dict[str, Any], link_family_id: str, mapping_family: str) -> str:
    if normalize_text(row.get("link_family_id")):
        return "explicit_link_info"
    if link_family_id == "LOCAL_DEVICE_MAPPING":
        return "fallback_device_context"
    if link_family_id == mapping_family:
        return "fallback_mapping_family"
    return "inferred_from_connection"


def analysis_strategy_for(link_family_id: str, mapping_family: str) -> str:
    if link_family_id in {"RF_TX_CHAIN", "FEEDBACK_CHAIN", "PA_CONTROL_CHAIN", "CAL_SWITCH_CHAIN"}:
        return "link_family_first_then_device_template_reuse"
    if mapping_family in {"SPI_CTRL", "POWER_ENABLE", "CLOCK_TREE", "GPIO_CTRL"}:
        return "mapping_family_first"
    return "device_type_pair_with_link_context"


def analysis_strategy_for_group(link_family_ids: List[str], mapping_families: List[str], isolation_level: str) -> str:
    if isolation_level == "hard_case":
        return "source_device_hard_case"
    if len(link_family_ids) > 1 or len(mapping_families) > 1:
        return "source_device_context_with_link_summaries"
    link_family_id = link_family_ids[0] if link_family_ids else "LOCAL_DEVICE_MAPPING"
    mapping_family = mapping_families[0] if mapping_families else "UNKNOWN"
    return analysis_strategy_for(link_family_id, mapping_family)


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
    hard_reasons = {
        "hard_case",
        "candidate_conflict",
        "validation_failed",
        "user_rule_conflict",
        "no_available_pins",
    }
    result = set()
    for row in iter_jsonl(p):
        reason = normalize_text(row.get("reason")).lower()
        if row.get("line_id") and reason in hard_reasons:
            result.add(row["line_id"])
    return result


def build_analysis_context_groups(
    normalized_path: str | Path,
    output_path: str | Path,
    needs_model_path: str | Path | None = None
) -> Dict[str, Any]:
    rows = list(iter_jsonl(normalized_path))
    hard_cases = load_hard_case_line_ids(needs_model_path)

    buckets: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)

    for row in rows:
        source_device_signature = source_analysis_signature(row)
        row["_source_device_signature"] = source_device_signature
        row["_target_device_signature"] = device_signature(
            row.get("target_part_id"),
            context_signature("TARGET_CONTEXT", row.get("target_block_name"), row.get("target_block_id")),
        )
        mapping_family = infer_mapping_family(row)
        link_family_id = infer_link_family(row, mapping_family)
        source = link_family_source(row, link_family_id, mapping_family)
        row["_mapping_family"] = mapping_family
        row["_link_family_id"] = link_family_id
        row["_link_family_source"] = source
        is_hard = row.get("line_id") in hard_cases
        isolation_level = "hard_case" if is_hard else "source_device_context"
        key = (source_device_signature, isolation_level)
        buckets[key].append(row)

    context_groups = []
    for (source_device_signature, isolation_level), group_rows in buckets.items():
        device_category = source_device_signature
        line_ids = [r["line_id"] for r in group_rows]
        source_sheets = sorted({r.get("source_sheet_name") or r.get("output_sheet_name") or "" for r in group_rows if r.get("source_sheet_name") or r.get("output_sheet_name")})
        source_block_ids = sorted({r.get("source_block_id", "") for r in group_rows if r.get("source_block_id")})
        link_family_ids = sorted({r.get("_link_family_id", "") for r in group_rows if r.get("_link_family_id")})
        link_family_sources = sorted({r.get("_link_family_source", "") for r in group_rows if r.get("_link_family_source")})
        mapping_families = sorted({r.get("_mapping_family", "") for r in group_rows if r.get("_mapping_family")})
        target_device_signatures = sorted({r.get("_target_device_signature", "") for r in group_rows if r.get("_target_device_signature")})
        link_family_id = link_family_ids[0] if len(link_family_ids) == 1 else "SOURCE_DEVICE_CONTEXT"
        source = link_family_sources[0] if len(link_family_sources) == 1 else "mixed_context"
        mapping_family = mapping_families[0] if len(mapping_families) == 1 else "MIXED"
        target_device_signature = target_device_signatures[0] if len(target_device_signatures) == 1 else "MULTI_TARGET_CONTEXT"
        link_instance_ids = sorted({r.get("link_instance_id", "") for r in group_rows if r.get("link_instance_id")})
        user_link_infos = sorted({r.get("user_link_info", "") for r in group_rows if r.get("user_link_info")})
        device_role_infos = sorted({r.get("device_role_info", "") for r in group_rows if r.get("device_role_info")})
        link_member_sheets = sorted({
            sheet
            for r in group_rows
            for sheet in (r.get("link_member_sheets") or [])
            if sheet
        })
        link_contexts = []
        seen_contexts = set()
        for row in group_rows:
            for ctx in row.get("link_contexts") or []:
                key = (
                    ctx.get("link_family_id", ""),
                    ctx.get("link_instance_id", ""),
                    ctx.get("user_link_info", ""),
                    ctx.get("device_role_info", ""),
                )
                if key not in seen_contexts:
                    seen_contexts.add(key)
                    link_contexts.append(ctx)
        source_device_instances = sorted({
            normalize_text(r.get("source_block_name")) or normalize_text(r.get("source_block_id")) or normalize_text(r.get("source_sheet_name"))
            for r in group_rows
        })
        target_device_instances = sorted({
            normalize_text(r.get("target_block_name")) or normalize_text(r.get("target_block_id"))
            for r in group_rows
        })

        subagent, prompt_file = choose_subagent(
            mapping_family,
            line_ids,
            hard_case=(isolation_level == "hard_case")
        )
        context_group_id = "CTX_" + stable_hash({
            "source_device_signature": source_device_signature,
            "isolation_level": isolation_level,
            "line_ids": line_ids[:20],
        })
        analysis_strategy = analysis_strategy_for_group(link_family_ids, mapping_families, isolation_level)

        context_groups.append({
            "context_group_id": context_group_id,
            "device_category": device_category,
            "link_family_id": link_family_id,
            "link_family_source": source,
            "link_family_ids": link_family_ids,
            "link_family_sources": link_family_sources,
            "analysis_strategy": analysis_strategy,
            "source_device_signature": source_device_signature,
            "target_device_signature": target_device_signature,
            "target_device_signatures": target_device_signatures,
            "source_device_instances": source_device_instances,
            "target_device_instances": target_device_instances,
            "link_instance_ids": link_instance_ids,
            "link_member_sheets": link_member_sheets,
            "user_link_infos": user_link_infos,
            "device_role_infos": device_role_infos,
            "link_contexts": link_contexts,
            "mapping_family": mapping_family,
            "mapping_families": mapping_families,
            "isolation_level": isolation_level,
            "source_sheets": source_sheets,
            "source_block_ids": source_block_ids,
            "line_ids": line_ids,
            "recommended_subagent": subagent,
            "prompt_file": prompt_file,
            "notes": "context_group 按源端器件 pin 体系隔离；链路族、信号族和目标上下文作为组内上下文传给 subagent，不再作为硬切分维度。"
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
