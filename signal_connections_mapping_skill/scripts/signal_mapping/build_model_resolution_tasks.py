#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
from collections import defaultdict
import re
from pathlib import Path
from typing import Any, Dict, List

from .build_analysis_context_groups import analysis_strategy_for_group, infer_link_family, infer_mapping_family
from .common import ensure_dir, iter_jsonl, load_pin_catalog, pins_for_part, read_json, resolve_catalog_key, write_json

DEFAULT_MAX_LINES_PER_MODEL_TASK = 50
PIN_GROUP_THRESHOLD = 100

PIN_GROUP_PATTERNS = {
    "POWER_GROUND": [
        r"VDD", r"VCC", r"VSS", r"GND", r"VBAT", r"VIN", r"VOUT", r"PWR", r"POWER",
    ],
    "CLOCK": [r"CLK", r"CLOCK", r"REFCLK", r"TCXO", r"(?:^|_)XO(?:_|$)"],
    "SPI": [r"SPI", r"SCLK", r"MOSI", r"MISO", r"(?:^|_)CS\d*(?:_|$)"],
    "I2C": [r"I2C", r"IIC", r"(?:^|_)SCL(?:_|$)", r"(?:^|_)SDA(?:_|$)"],
    "GPIO": [r"GPIO"],
    "CONTROL": [
        r"CTRL", r"CONTROL", r"ENABLE", r"(?:^|_)EN\d*(?:_|$)", r"RESET", r"RST",
        r"(?:^|_)SW", r"(?:^|_)SEL", r"MODE", r"ALERT", r"IRQ", r"INT",
    ],
    "ANALOG_RF": [r"RF", r"ADC", r"DAC", r"AFE", r"LNA"],
    "DIFFERENTIAL": [r"(?:^|[_-])(?:P|N|DP|DN|POS|NEG)(?:$|[_-])"],
}


def load_by_line_id(path: str | Path) -> Dict[str, Dict[str, Any]]:
    return {row["line_id"]: row for row in iter_jsonl(path)}


def pin_group_ids(value: Any) -> List[str]:
    """返回无分数、多标签的固定语义组；顺序只来自固定组定义。"""
    text = re.sub(r"[^A-Z0-9]+", "_", str(value or "").upper()).strip("_")
    padded = f"_{text}_"
    return [
        group_id
        for group_id, patterns in PIN_GROUP_PATTERNS.items()
        if any(re.search(pattern, padded) for pattern in patterns)
    ]


def build_pin_group_catalog(source_part_id: str, pins: List[str]) -> Dict[str, Any]:
    groups: Dict[str, List[str]] = {group_id: [] for group_id in PIN_GROUP_PATTERNS}
    unclassified: List[str] = []
    for pin in pins:
        memberships = pin_group_ids(pin)
        if not memberships:
            unclassified.append(pin)
            continue
        for group_id in memberships:
            groups[group_id].append(pin)
    if unclassified:
        groups["UNCLASSIFIED"] = unclassified
    return {
        "source_part_id": source_part_id,
        "pin_count": len(pins),
        "grouping_threshold": PIN_GROUP_THRESHOLD,
        "lossless": True,
        "multi_label": True,
        "ranked": False,
        "all_pins": list(pins),
        "groups": {
            group_id: group_pins
            for group_id, group_pins in groups.items()
            if group_pins
        },
    }


def task_pin_group_ids(
    task_group: Dict[str, Any],
    rows: List[Dict[str, Any]],
    available_group_ids: List[str],
) -> List[str]:
    context_values: List[Any] = []
    context_values.extend(task_group.get("mapping_families", []) or [])
    context_values.extend(task_group.get("link_family_ids", []) or [])
    for row in rows:
        context_values.extend([
            row.get("source_port", ""),
            row.get("target_port", ""),
            row.get("connection_name", ""),
            row.get("signal_shape", ""),
        ])
    selected = {
        group_id
        for value in context_values
        for group_id in pin_group_ids(value)
        if group_id in available_group_ids
    }
    # 无法可靠识别当前语义组时不做过滤，保证任务仍然无损。
    return sorted(selected) if selected else list(available_group_ids)


def pins_for_groups(catalog: Dict[str, Any], group_ids: List[str]) -> List[str]:
    included = {
        pin
        for group_id in group_ids
        for pin in catalog.get("groups", {}).get(group_id, [])
    }
    return [pin for pin in catalog.get("all_pins", []) if pin in included]


def cleanup_model_task_output_dir(output_dir: Path) -> None:
    """清理本脚本的旧任务产物，避免 CTX_xxx 和新 TASK_xxx 混在一起。"""
    for pattern in [
        "CTX_*.json",
        "CTX_*.prompt.md",
        "TASK_*.json",
        "TASK_*.prompt.md",
        "global_subagent_plan.json",
        "global_subagent_plan.md",
        "global_link_plan.json",
        "global_link_plan.md",
        "subagent_task_plan.json",
        "subagent_task_plan.md",
        "subagent_session_plan.json",
        "subagent_session_plan.md",
        "index.json",
        "manifest.json",
        "subagent_task_prompt.md",
    ]:
        for path in output_dir.glob(pattern):
            if path.is_file():
                path.unlink()
    tasks_dir = output_dir / "tasks"
    if tasks_dir.exists():
        for pattern in ["TASK_*.json", "TASK_*.prompt.md"]:
            for path in tasks_dir.glob(pattern):
                if path.is_file():
                    path.unlink()
    subagent_outputs_dir = output_dir.parent / "subagent_outputs"
    subagent_outputs_dir.mkdir(parents=True, exist_ok=True)
    subagent_state_dir = output_dir.parent / "subagent_state"
    if subagent_state_dir.exists():
        for path in subagent_state_dir.glob("*.json"):
            if path.is_file():
                path.unlink()
    subagent_state_dir.mkdir(parents=True, exist_ok=True)


def source_part_label(group: Dict[str, Any]) -> str:
    signature = str(group.get("source_device_signature", ""))
    if signature.startswith("DEVICE_INFO:"):
        return signature.split(":", 1)[1]
    return "UNKNOWN_PART"


def filename_slug(value: Any, default: str = "UNKNOWN", max_len: int = 48) -> str:
    text = str(value or "").strip()
    if not text:
        text = default
    text = re.sub(r"[\\/:*?\"<>|\s]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("._")
    if not text:
        text = default
    return text[:max_len]


def readable_device_type(group: Dict[str, Any]) -> str:
    values = []
    values.extend(group.get("source_sheets", []) or [])
    values.extend(group.get("source_device_instances", []) or [])
    values.append(group.get("source_device_signature", ""))
    text = " ".join(str(v) for v in values).upper()
    keyword_labels = [
        ("SROC", ["SROC"]),
        ("TXVGA", ["TXVGA", "TX VGA"]),
        ("91FBSW", ["91FBSW", "FBSW", "反馈九选一"]),
        ("AMC7964", ["AMC7964"]),
        ("HBF", ["HBF"]),
        ("PA", ["功放", " PA", "PAM"]),
    ]
    for label, keywords in keyword_labels:
        if any(keyword.upper() in text for keyword in keywords):
            return label
    for value in group.get("source_sheets", []) or []:
        if value:
            return filename_slug(value)
    return filename_slug(group.get("source_device_signature", ""), "SOURCE_DEVICE")


def readable_family_scope(group: Dict[str, Any]) -> str:
    families = group.get("link_family_ids") or [group.get("link_family_id") or "LOCAL_DEVICE_MAPPING"]
    if len(families) == 1:
        return filename_slug(families[0], "LOCAL_DEVICE_MAPPING", 36)
    return "MULTI_LINK"


def task_file_stem(task_index: int, group: Dict[str, Any], context_id: str) -> str:
    device = filename_slug(readable_device_type(group), "DEVICE", 32)
    part = filename_slug(source_part_label(group), "UNKNOWN_PART", 32)
    family = readable_family_scope(group)
    context_hash = context_id.replace("CTX_", "")
    return f"TASK_{task_index:02d}_{device}_{part}_{family}_{context_hash}"

def line_family_for_row(row: Dict[str, Any], fallback_family_id: str) -> str:
    family_ids = link_family_ids_for_row(row, fallback_family_id)
    return family_ids[0] if family_ids else fallback_family_id


def physical_device_instance_id(row: Dict[str, Any]) -> str:
    sheet = row.get("source_sheet_name") or row.get("output_sheet_name") or "UNKNOWN_SHEET"
    part_id = row.get("source_part_id", "") or "UNKNOWN_PART"
    return f"SHEET:{sheet}|PART:{part_id}"


def line_scope_key(row: Dict[str, Any], group: Dict[str, Any]) -> tuple[str, str, str]:
    """
    小 TASK 的切分维度。

    subagent 仍按源端器件 pin 体系执行；这里仅把同一个 subagent 里的输入切小。
    小 TASK 必须先守住 physical_device_instance_id 边界，再按链路族和映射族切分。
    link_instance_id 不作为硬切分维度，只用于排序和上下文；否则重复链路会产生过多碎片 TASK。
    """
    fallback_family = group.get("link_family_id") or "LOCAL_DEVICE_MAPPING"
    return (
        normalize_match_text(physical_device_instance_id(row)),
        normalize_match_text(line_family_for_row(row, fallback_family)),
        normalize_match_text(infer_mapping_family(row)),
    )


def chunk_items(items: List[str], size: int) -> List[List[str]]:
    if size <= 0:
        return [items]
    return [items[i:i + size] for i in range(0, len(items), size)]


def split_balanced_line_tasks(
    group: Dict[str, Any],
    rows: List[Dict[str, Any]],
    max_lines_per_task: int = DEFAULT_MAX_LINES_PER_MODEL_TASK,
) -> List[List[str]]:
    buckets: Dict[tuple[str, str, str], List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        buckets[line_scope_key(row, group)].append(row)

    keyed_chunks: List[tuple[str, List[str]]] = []
    for key in sorted(buckets):
        bucket_rows = sorted(
            buckets[key],
            key=lambda row: (
                normalize_match_text(row.get("source_block_name")),
                normalize_match_text(row.get("source_port")),
                normalize_match_text(row.get("link_instance_id")),
                normalize_match_text(row.get("target_block_name")),
                normalize_match_text(row.get("target_port")),
                normalize_match_text(row.get("connection_id")),
                normalize_match_text(row.get("line_id")),
            ),
        )
        instance_id = key[0]
        for chunk in chunk_items([row["line_id"] for row in bucket_rows], max_lines_per_task):
            keyed_chunks.append((instance_id, chunk))

    packed: List[List[str]] = []
    current: List[str] = []
    current_instance = ""
    for instance_id, chunk in keyed_chunks:
        if current and instance_id != current_instance:
            packed.append(current)
            current = []
            current_instance = ""
        if len(chunk) >= max_lines_per_task:
            if current:
                packed.append(current)
                current = []
                current_instance = ""
            packed.append(chunk)
            continue
        if current and len(current) + len(chunk) > max_lines_per_task:
            packed.append(current)
            current = []
            current_instance = ""
        if not current:
            current_instance = instance_id
        current.extend(chunk)
    if current:
        packed.append(current)
    return packed


def scoped_group(group: Dict[str, Any], rows: List[Dict[str, Any]], line_ids: List[str]) -> Dict[str, Any]:
    scoped = dict(group)
    fallback_family = group.get("link_family_id") or "LOCAL_DEVICE_MAPPING"
    families = sorted({family for row in rows for family in link_family_ids_for_row(row, fallback_family) if family})
    mapping_families = sorted({infer_mapping_family(row) for row in rows if infer_mapping_family(row)})
    link_sources = sorted({
        "explicit_link_info" if row.get("link_family_id") else (
            "fallback_device_context" if (families == ["LOCAL_DEVICE_MAPPING"]) else "inferred_from_connection"
        )
        for row in rows
    })
    target_signatures = sorted({
        f"DEVICE_INFO:{str(row.get('target_part_id')).upper()}" if row.get("target_part_id")
        else f"TARGET_CONTEXT:{normalize_match_text(row.get('target_block_name') or row.get('target_block_id') or 'UNKNOWN')}"
        for row in rows
    })
    scoped.update({
        "line_ids": line_ids,
        "task_line_count": len(line_ids),
        "parent_context_group_id": group.get("context_group_id", ""),
        "link_family_ids": families or group.get("link_family_ids", []),
        "link_family_id": (families[0] if len(families) == 1 else "SOURCE_DEVICE_CONTEXT") if families else group.get("link_family_id", ""),
        "link_family_sources": link_sources or group.get("link_family_sources", []),
        "link_family_source": (link_sources[0] if len(link_sources) == 1 else "mixed_context") if link_sources else group.get("link_family_source", ""),
        "mapping_families": mapping_families or group.get("mapping_families", []),
        "mapping_family": (mapping_families[0] if len(mapping_families) == 1 else "MIXED") if mapping_families else group.get("mapping_family", ""),
        "target_device_signatures": target_signatures or group.get("target_device_signatures", []),
        "target_device_signature": target_signatures[0] if len(target_signatures) == 1 else "MULTI_TARGET_CONTEXT",
        "source_sheets": sorted({row.get("source_sheet_name") or row.get("output_sheet_name") or "" for row in rows if row.get("source_sheet_name") or row.get("output_sheet_name")}),
        "source_block_ids": sorted({row.get("source_block_id", "") for row in rows if row.get("source_block_id")}),
        "source_device_instances": sorted({
            row.get("source_block_name") or row.get("source_block_id") or row.get("source_sheet_name") or ""
            for row in rows
            if row.get("source_block_name") or row.get("source_block_id") or row.get("source_sheet_name")
        }),
        "target_device_instances": sorted({
            row.get("target_block_name") or row.get("target_block_id") or ""
            for row in rows
            if row.get("target_block_name") or row.get("target_block_id")
        }),
        "link_instance_ids": sorted({row.get("link_instance_id", "") for row in rows if row.get("link_instance_id")}),
        "link_member_sheets": sorted({sheet for row in rows for sheet in (row.get("link_member_sheets") or []) if sheet}),
        "user_link_infos": sorted({row.get("user_link_info", "") for row in rows if row.get("user_link_info")}),
        "device_role_infos": sorted({row.get("device_role_info", "") for row in rows if row.get("device_role_info")}),
        "analysis_strategy": analysis_strategy_for_group(
            families or group.get("link_family_ids", []),
            mapping_families or group.get("mapping_families", []),
            group.get("isolation_level", "source_device_context"),
        ),
        "notes": "balanced mode: context_group 仍表示源端器件 pin 体系；当前 TASK 是该 subagent 会话内的一个小批次。",
    })
    return scoped


def slim_context_group(group: Dict[str, Any]) -> Dict[str, Any]:
    """只保留模型裁决所需的组级语义；逐行事实由 normalized_connections 承载。"""
    keys = [
        "context_group_id",
        "parent_context_group_id",
        "source_device_signature",
        "target_device_signatures",
        "link_family_ids",
        "link_family_sources",
        "mapping_families",
        "analysis_strategy",
        "link_instance_ids",
        "link_member_sheets",
        "user_link_infos",
        "device_role_infos",
        "link_contexts",
    ]
    return {
        key: group.get(key)
        for key in keys
        if group.get(key) not in (None, "", [], {})
    }


def compact_signal_shape_info(row: Dict[str, Any]) -> Dict[str, Any]:
    """把可由 TASK 默认值恢复的 signal_shape_info 字段移出逐行对象。"""
    info = row.get("signal_shape_info")
    if not isinstance(info, dict):
        return {
            "shape": row.get("signal_shape", "scalar") or "scalar",
            "expected_physical_pin_count": int(row.get("expected_physical_pin_count", 1) or 1),
        }

    line_id = row.get("line_id", "")
    shape = info.get("shape", row.get("signal_shape", "scalar")) or "scalar"
    compact: Dict[str, Any] = {
        "shape": shape,
        "expected_physical_pin_count": int(info.get("expected_physical_pin_count", 1) or 1),
    }
    optional_values = {
        "is_expanded_member": info.get("is_expanded_member", False),
        "parent_line_id": info.get("parent_line_id", ""),
        "member_index": info.get("member_index", 1),
        "member_count": info.get("member_count", 1),
        "member_role": info.get("member_role", ""),
        "line_id_expansion_policy": info.get("line_id_expansion_policy", ""),
        "connection_id_suffix_separator": info.get("connection_id_suffix_separator", ""),
        "expected_output_connection_ids": info.get("expected_output_connection_ids", []),
        "confidence": info.get("confidence", ""),
        "needs_model_shape_review": info.get("needs_model_shape_review", False),
        "reasons": info.get("reasons", []),
    }
    defaults = {
        "is_expanded_member": False,
        "parent_line_id": line_id,
        "member_index": 1,
        "member_count": 1,
        "member_role": "",
        "line_id_expansion_policy": "single_output_row" if shape == "scalar" else "",
        "connection_id_suffix_separator": "",
        "expected_output_connection_ids": [],
        "confidence": "auto_high",
        "needs_model_shape_review": False,
        "reasons": [],
    }
    for key, value in optional_values.items():
        if value in (None, "", [], {}) and defaults[key] not in (None, "", [], {}):
            continue
        if value != defaults[key]:
            compact[key] = value

    evidence = dict(info.get("evidence", {}) or {})
    if evidence.get("source_pins_available") is True:
        evidence.pop("source_pins_available", None)
    if evidence:
        compact["evidence"] = evidence
    return compact


def compact_normalized_connection(row: Dict[str, Any]) -> Dict[str, Any]:
    """生成面向模型的无损语义视图，省略可确定恢复的空值和别名字段。"""
    always = [
        "line_id",
        "source_sheet_name",
        "source_part_id",
        "source_block_id",
        "source_block_name",
        "source_port",
        "target_block_id",
        "target_block_name",
        "target_port",
        "connection_id",
        "connection_name",
        "direction",
    ]
    compact: Dict[str, Any] = {key: row.get(key, "") for key in always}
    optional = [
        "target_part_id",
        "link_family_id",
        "link_instance_id",
        "link_member_sheets",
        "user_link_info",
        "device_role_info",
        "link_contexts",
        "connection_attribute",
    ]
    for key in optional:
        value = row.get(key)
        if value not in (None, "", [], {}):
            compact[key] = value

    alias_overrides = {
        "output_sheet_name": ("source_sheet_name",),
        "base_line_id": ("line_id",),
        "base_connection_id": ("connection_id",),
        "raw_source_port": ("source_port",),
        "raw_target_port": ("target_port",),
    }
    for key, source_keys in alias_overrides.items():
        value = row.get(key)
        source_value = next((row.get(source_key) for source_key in source_keys), None)
        if value not in (None, "") and value != source_value:
            compact[key] = value

    if int(row.get("expansion_index", 1) or 1) != 1:
        compact["expansion_index"] = int(row.get("expansion_index", 1) or 1)
    if int(row.get("expansion_count", 1) or 1) != 1:
        compact["expansion_count"] = int(row.get("expansion_count", 1) or 1)
    compact["signal_shape_info"] = compact_signal_shape_info(row)
    return compact


def connection_defaults() -> Dict[str, Any]:
    return {
        "output_sheet_name": "same_as_source_sheet_name",
        "base_line_id": "same_as_line_id",
        "base_connection_id": "same_as_connection_id",
        "raw_source_port": "same_as_source_port",
        "raw_target_port": "same_as_target_port",
        "expansion_index": 1,
        "expansion_count": 1,
        "signal_shape_info": {
            "is_expanded_member": False,
            "parent_line_id": "same_as_line_id",
            "member_index": 1,
            "member_count": 1,
            "confidence": "auto_high",
            "needs_model_shape_review": False,
            "evidence.source_pins_available": True,
        },
    }


def pin_state_instances(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    instances: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        instance_id = physical_device_instance_id(row)
        instance = instances.setdefault(instance_id, {
            "physical_device_instance_id": instance_id,
            "source_sheet_name": row.get("source_sheet_name") or row.get("output_sheet_name") or "",
            "source_part_id": row.get("source_part_id", ""),
            "line_ids": [],
            "used_pins": [],
            "allowed_shared_pin_groups": [],
            "unresolved_conflicts": [],
        })
        instance["line_ids"].append(row.get("line_id", ""))
    return list(instances.values())


def semantic_hints_for_link_family(family_id: str) -> List[str]:
    family = normalize_match_text(family_id)
    hints = [
        "同一个 link_family 下的不同 link_instance 可以互相借鉴链路拓扑、方向、实例索引、差分/总线展开规律和器件角色。",
        "借鉴的是链路语义和分析方法，不是直接复制某一行的 selected_pin；每条 line_id 仍必须结合当前源端 pin 列表、端口、对端和连线信息独立判断。",
    ]
    if "RF" in family or "TX" in family:
        hints.append("RF/TX 类链路通常需要先判断通道索引、P/N 极性、RFIN/RFOUT 方向和上下游器件角色，再选择当前源端器件 pin。")
    if "FEEDBACK" in family or "FB" in family:
        hints.append("反馈链路通常需要关注 FB 索引、反馈开关通道、回采方向以及 SROC/开关/功放模组之间的角色关系。")
    if "SPI" in family:
        hints.append("SPI 类链路可以借鉴 CLK/CS/DI/DO 或 DIO 的拆分方式，但片选编号、数据方向和实例编号不足时应保持 unresolved。")
    if "POWER" in family or "PWR" in family:
        hints.append("电源链路应先判断供电源、负载器件、电压域和上电脚功能，再在当前源端器件 pin 中找同功能 pin。")
    if "CONTROL" in family or "CTRL" in family or "PA_" in family:
        hints.append("控制链路应优先判断控制源、被控对象、通道编号和使能/开关/模式选择语义。")
    return hints


def link_family_ids_for_row(row: Dict[str, Any], fallback_family_id: str) -> List[str]:
    explicit = row.get("link_family_id")
    if explicit:
        return [explicit]
    context_family_ids = sorted({
        ctx.get("link_family_id", "")
        for ctx in row.get("link_contexts", [])
        if isinstance(ctx, dict) and ctx.get("link_family_id")
    })
    if context_family_ids:
        return context_family_ids
    mapping_family = infer_mapping_family(row)
    inferred_family = infer_link_family(row, mapping_family)
    return [inferred_family or fallback_family_id]


def build_link_family_profiles(
    groups: List[Dict[str, Any]],
    normalized_by_id: Dict[str, Dict[str, Any]],
    max_examples_per_family: int = 40,
) -> Dict[str, Dict[str, Any]]:
    """
    为每个 link_family 构建可共享的链路语义上下文。

    profile 会注入到所有涉及该 link_family 的 CTX 中。它用于让不同源端器件
    subagent 借鉴同一链路族的拓扑、实例编号和用户说明，但不做 pin 裁决。
    """
    profiles: Dict[str, Dict[str, Any]] = {}

    for group in groups:
        group_families = group.get("link_family_ids") or [group.get("link_family_id") or "LOCAL_DEVICE_MAPPING"]
        group_line_ids = group.get("line_ids", [])
        for family_id in group_families:
            entry = profiles.setdefault(family_id, {
                "link_family_id": family_id,
                "purpose": "共享给涉及该 link_family 的 subagent，用于借鉴链路级语义；不得作为直接 pin 裁决结果。",
                "usage": "先理解本 profile 的链路拓扑、实例、用户说明和相关器件角色，再回到当前 line_id 独立判断 selected_pin。",
                "context_group_ids": set(),
                "source_device_signatures": set(),
                "target_device_signatures": set(),
                "mapping_families": set(),
                "link_family_sources": set(),
                "link_instance_ids": set(),
                "member_sheets": set(),
                "user_link_infos": set(),
                "device_role_infos": set(),
                "line_count": 0,
                "line_examples": [],
                "ambiguous_sheet_member_line_count": 0,
                "ambiguous_sheet_member_line_examples": [],
                "shared_semantic_hints": semantic_hints_for_link_family(family_id),
            })
            entry["context_group_ids"].add(group.get("context_group_id", ""))
            entry["source_device_signatures"].add(group.get("source_device_signature", ""))
            for source in group.get("link_family_sources") or [group.get("link_family_source", "")]:
                entry["link_family_sources"].add(source)

            for line_id in group_line_ids:
                row = normalized_by_id.get(line_id, {})
                explicit_row_family = row.get("link_family_id", "")
                row_families = link_family_ids_for_row(row, family_id)
                if family_id not in row_families:
                    continue
                target_part_id = str(row.get("target_part_id", "") or "").strip()
                target_block_name = str(row.get("target_block_name", "") or "").strip()
                if target_part_id:
                    entry["target_device_signatures"].add(f"DEVICE_INFO:{target_part_id}")
                elif target_block_name:
                    entry["target_device_signatures"].add(f"TARGET_CONTEXT:{target_block_name}")
                entry["mapping_families"].add(infer_mapping_family(row))
                is_ambiguous_sheet_member = not explicit_row_family and bool(row.get("link_contexts"))
                for instance_id in [row.get("link_instance_id", "")]:
                    if instance_id:
                        entry["link_instance_ids"].add(instance_id)
                for sheet in row.get("link_member_sheets", []):
                    entry["member_sheets"].add(sheet)
                if row.get("user_link_info"):
                    entry["user_link_infos"].add(row.get("user_link_info"))
                if row.get("device_role_info"):
                    entry["device_role_infos"].add(row.get("device_role_info"))
                example = {
                    "line_id": line_id,
                    "context_group_id": group.get("context_group_id", ""),
                    "source_device_signature": group.get("source_device_signature", ""),
                    "source_sheet_name": row.get("source_sheet_name", ""),
                    "source_block_name": row.get("source_block_name", ""),
                    "source_port": row.get("source_port", ""),
                    "target_block_name": row.get("target_block_name", ""),
                    "target_port": row.get("target_port", ""),
                    "connection_name": row.get("connection_name", ""),
                    "link_instance_id": row.get("link_instance_id", ""),
                    "user_link_info": row.get("user_link_info", ""),
                    "device_role_info": row.get("device_role_info", ""),
                }
                if is_ambiguous_sheet_member:
                    entry["ambiguous_sheet_member_line_count"] += 1
                    if len(entry["ambiguous_sheet_member_line_examples"]) < 8:
                        entry["ambiguous_sheet_member_line_examples"].append(example)
                else:
                    entry["line_count"] += 1
                    if len(entry["line_examples"]) < max_examples_per_family:
                        entry["line_examples"].append(example)

    for entry in profiles.values():
        for key in [
            "context_group_ids",
            "source_device_signatures",
            "target_device_signatures",
            "mapping_families",
            "link_family_sources",
            "link_instance_ids",
            "member_sheets",
            "user_link_infos",
            "device_role_infos",
        ]:
            entry[key] = sorted(x for x in entry[key] if x)
    return profiles


def describe_subagent_task(task: Dict[str, Any], group: Dict[str, Any]) -> str:
    strategy = group.get("analysis_strategy", "")
    families = ", ".join(group.get("link_family_ids", [])[:6]) or group.get("link_family_id", "")
    family_source = group.get("link_family_source", "")
    source = group.get("source_device_signature", "")
    targets = ", ".join(group.get("target_device_signatures", [])[:5]) or group.get("target_device_signature", "")
    role_infos = "; ".join(group.get("device_role_infos", [])[:3])
    user_infos = "; ".join(group.get("user_link_infos", [])[:3])
    if strategy == "source_device_context_with_link_summaries":
        goal = f"统一分析 {source} 源端 pin 体系，链路族包括 {families}，目标上下文包括 {targets}；逐条连接按链路/信号上下文选择源端 pin。"
    elif strategy == "source_device_hard_case":
        goal = f"单独分析 {source} 的 hard-case 连接，先复核链路、规则和 pin 分配冲突原因。"
    elif family_source in {"fallback_device_context", "fallback_mapping_family"}:
        goal = f"没有显式链路级数据，按 {source} 的器件上下文和 {group.get('mapping_family', '')} 映射族启动分析。"
    elif strategy == "link_family_first_then_device_template_reuse":
        goal = f"先理解 {families} 链路族的全局功能和上下游角色，再为 {source} 的连接选择源端 pin。"
    elif strategy == "mapping_family_first":
        goal = f"按 {group.get('mapping_family', '')} 映射族优先分析，再结合源端器件 pin 列表裁决。"
    else:
        goal = f"按源/目的器件上下文分析 {source} 到 {targets} 的局部映射。"
    details = []
    if user_infos:
        details.append(f"用户链路说明：{user_infos}")
    if role_infos:
        details.append(f"器件角色说明：{role_infos}")
    return goal + (" " + " ".join(details) if details else "")


def build_diagram_link_context(group: Dict[str, Any], normalized_connections: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    把输入框图表中的链路信息整理成模型易读上下文。

    normalized_connections 是唯一逐行事实。这里仅保留组级链路总览，
    避免把每行 block/port/link 字段再复制一遍。
    """
    return {
        "source": "input_workbook_link_info_sheet_and_connection_rows",
        "usage": "组级链路信息用于理解链路归属、角色和实例；逐行事实只读取 normalized_connections。",
        "group_link_family_ids": group.get("link_family_ids", []),
        "group_link_family_sources": group.get("link_family_sources", []),
        "group_link_instance_ids": group.get("link_instance_ids", []),
        "group_link_member_sheets": group.get("link_member_sheets", []),
        "group_user_link_infos": group.get("user_link_infos", []),
        "group_device_role_infos": group.get("device_role_infos", []),
        "group_link_contexts": group.get("link_contexts", []),
    }


def build_sheet_device_context(normalized_connections: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    表达输入 Excel 的 sheet 语义：

    一个连接 sheet 表示一个物理器件实例；sheet 内不同 source_block_id /
    source_block_name 是这个物理器件的逻辑块、功能块或端口视图，不应被模型
    当成多个独立器件来分配 pin。
    """
    instances: Dict[str, Dict[str, Any]] = {}
    for row in normalized_connections:
        sheet = row.get("source_sheet_name") or row.get("output_sheet_name") or "UNKNOWN_SHEET"
        part_id = row.get("source_part_id", "")
        instance_key = f"SHEET:{sheet}|PART:{part_id or 'UNKNOWN_PART'}"
        instance = instances.setdefault(instance_key, {
            "physical_device_instance_id": instance_key,
            "source_sheet_name": sheet,
            "source_part_id": part_id,
            "line_ids": [],
        })
        instance["line_ids"].append(row.get("line_id", ""))

    return {
        "source": "input_workbook_sheet_structure",
        "usage": "同一 source_sheet_name 是一个物理器件实例；block/port 逐行事实读取 normalized_connections。",
        "physical_device_instances": list(instances.values()),
    }


def shared_signal_key(row: Dict[str, Any]) -> str:
    name = str(row.get("connection_name", "") or "").strip()
    if name and "LINE" not in name.upper():
        return f"NET:{name}"
    base_connection = str(row.get("base_connection_id", "") or "").strip()
    if base_connection:
        return f"CONNECTION:{base_connection}"
    return ""


def endpoint_key(row: Dict[str, Any]) -> str:
    return "|".join([
        str(row.get("source_sheet_name") or row.get("output_sheet_name") or ""),
        str(row.get("source_block_id") or row.get("source_block_name") or ""),
        str(row.get("source_port") or ""),
    ])


def build_pin_allocation_context(
    normalized_connections: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    给模型显式提供同一物理器件实例内的 pin 分配约束。

    这里不预先选择 pin，只告诉模型哪些连接共享同一物理器件 pin 空间，
    哪些连接可能因为同一连线名称或连接 ID 而允许共享同一个 pin。
    """
    instances: Dict[str, Dict[str, Any]] = {}
    shared_groups: Dict[str, Dict[str, Any]] = {}
    endpoint_groups: Dict[str, Dict[str, Any]] = {}
    for row in normalized_connections:
        line_id = row.get("line_id", "")
        sheet = row.get("source_sheet_name") or row.get("output_sheet_name") or "UNKNOWN_SHEET"
        part_id = row.get("source_part_id", "")
        instance_key = f"SHEET:{sheet}|PART:{part_id or 'UNKNOWN_PART'}"
        instance = instances.setdefault(instance_key, {
            "physical_device_instance_id": instance_key,
            "source_sheet_name": sheet,
            "source_part_id": part_id,
            "line_ids": [],
        })
        instance["line_ids"].append(line_id)

        key = shared_signal_key(row)
        if key:
            group = shared_groups.setdefault(f"{instance_key}|{key}", {
                "physical_device_instance_id": instance_key,
                "shared_signal_key": key,
                "reason": "相同 connection_name 或 base_connection_id，可能是同一物理信号/同一 pin 的多端口视图；是否共享 pin 仍需结合规则和语义判断。",
                "line_ids": [],
            })
            group["line_ids"].append(line_id)

        endpoint = endpoint_key(row)
        if endpoint:
            endpoint_group = endpoint_groups.setdefault(f"{instance_key}|ENDPOINT:{endpoint}", {
                "physical_device_instance_id": instance_key,
                "shared_signal_key": f"SOURCE_ENDPOINT:{endpoint}",
                "source_sheet_name": sheet,
                "source_block_id": row.get("source_block_id", ""),
                "source_block_name": row.get("source_block_name", ""),
                "source_port": row.get("source_port", ""),
                "reason": "同一个源端端口连接到多个目标端口，表示扇出/多目标连接；通常可共享同一个源端 pin。",
                "line_ids": [],
                "target_endpoints": set(),
            })
            endpoint_group["line_ids"].append(line_id)
            endpoint_group["target_endpoints"].add(
                f"{row.get('target_block_name', '')}:{row.get('target_port', '')}"
            )

    endpoint_shared_groups = []
    for group in endpoint_groups.values():
        group["target_endpoints"] = sorted(x for x in group.get("target_endpoints", set()) if x and x != ":")
        if len(set(group.get("line_ids", []))) > 1 and len(group["target_endpoints"]) > 1:
            endpoint_shared_groups.append(group)

    return {
        "pin_reuse_policy": "default_unique_per_physical_instance_except_listed_shared_groups",
        "physical_device_pin_spaces": list(instances.values()),
        "potential_shared_pin_groups": [
            group for group in shared_groups.values()
            if len(set(group.get("line_ids", []))) > 1
        ] + endpoint_shared_groups,
    }


def render_subagent_task_plan(tasks: List[Dict[str, Any]], skipped_tasks: List[Dict[str, Any]] | None = None) -> str:
    skipped_tasks = skipped_tasks or []
    lines = [
        "# Subagent Task Plan",
        "",
        "在启动语义 subagent 前，先按本计划检查每个任务包。平衡模式下，一个源端器件 subagent 可以顺序处理同一 session 下的多个小 TASK；每个 TASK 只处理自己的 task_json 中列出的 line_id。",
        "",
        "| # | task | session | 器件类型 | 源端器件编码 | context_group | link_family | lines | task_json | output_file | prompt | 要做什么 |",
        "|---|---|---|---|---|---|---|---:|---|---|---|---|",
    ]
    for i, task in enumerate(tasks, start=1):
        family_label = ", ".join(task.get("link_family_ids", [])[:4]) or task.get("link_family_id", "")
        task_json = Path(task.get("task_json", ""))
        output_file = Path(task.get("output_file", ""))
        prompt_file = Path(task.get("prompt_file", ""))
        lines.append(
            "| {i} | {task_name} | {session} | {device} | {part} | {context} | {family} | {lines_count} | {task_json} | {output_file} | {prompt} | {goal} |".format(
                i=i,
                task_name=task.get("task_display_name", ""),
                session=task.get("subagent_session_id", ""),
                device=task.get("readable_device_type", ""),
                part=task.get("source_part_id", ""),
                context=task.get("context_group_id", ""),
                family=family_label,
                lines_count=task.get("line_count", 0),
                task_json=f"{task_json.parent.name}/{task_json.name}" if task_json.parent.name else task_json.name,
                output_file=f"{output_file.parent.name}/{output_file.name}" if output_file.parent.name else output_file.name,
                prompt=f"{prompt_file.parent.name}/{prompt_file.name}" if prompt_file.parent.name else prompt_file.name,
                goal=str(task.get("task_goal", "")).replace("|", "/"),
            )
        )
    if skipped_tasks:
        lines.extend([
            "",
            "## Skipped Context Groups",
            "",
            "以下 context_group 因为入参 pin_info.json 中没有对应源端器件编码的 pin 列表，不生成 CTX 语义分析任务；最终保留 pre_resolve 的 unresolved 结果。",
            "",
            "| context_group | source | lines | reason |",
            "|---|---|---:|---|",
        ])
        for item in skipped_tasks:
            lines.append(
                "| {context} | {source} | {count} | {reason} |".format(
                    context=item.get("context_group_id", ""),
                    source=", ".join(item.get("source_part_ids", [])) or item.get("source_device_signature", ""),
                    count=item.get("line_count", 0),
                    reason=item.get("reason", ""),
                )
            )
    return "\n".join(lines) + "\n"


def render_subagent_session_plan(sessions: List[Dict[str, Any]]) -> str:
    lines = [
        "# Subagent Session Plan",
        "",
        "平衡模式：subagent 按源端器件 pin 体系启动；每个 subagent 顺序处理自己的多个小 TASK。这样减少单次推理上下文，但不会因为 TASK 变小而启动几十个互不相干的 subagent。",
        "",
        "| # | session | 源端器件 | lines | tasks | pin_state | 执行顺序 |",
        "|---|---|---|---:|---:|---|---|",
    ]
    for idx, session in enumerate(sessions, start=1):
        task_names = [
            Path(task.get("task_json", "")).name
            for task in session.get("tasks", [])
        ]
        lines.append(
            "| {idx} | {session_id} | {source} | {lines_count} | {task_count} | {state} | {tasks} |".format(
                idx=idx,
                session_id=str(session.get("subagent_session_id", "")).replace("|", "/"),
                source=str(session.get("source_device_signature", "")).replace("|", "/"),
                lines_count=session.get("line_count", 0),
                task_count=len(session.get("tasks", [])),
                state=(
                    str(Path(session.get("pin_allocation_state_file", "")).name)
                    + "<br>"
                    + str(Path(session.get("session_context_file", "")).name)
                ).replace("|", "/"),
                tasks="<br>".join(task_names).replace("|", "/"),
            )
        )
    lines.extend([
        "",
        "执行要求：同一个 session 由一个 subagent 顺序处理全部 TASK；session_context_file 只读一次，处理每个 TASK 前读取 pin_allocation_state_file 最新状态。完成后写入 output_file 并更新 state。",
    ])
    return "\n".join(lines) + "\n"


def build_global_link_plan(
    link_family_profiles: Dict[str, Dict[str, Any]],
    sessions: List[Dict[str, Any]],
) -> Dict[str, Any]:
    families = []
    for family_id, profile in sorted(link_family_profiles.items()):
        families.append({
            "link_family_id": family_id,
            "purpose": "给各 source_device subagent 共享链路级语义；不得作为 pin 裁决结果。",
            "line_count": profile.get("line_count", 0),
            "context_group_count": len(profile.get("context_group_ids", [])),
            "source_device_signatures": profile.get("source_device_signatures", []),
            "target_device_signatures": profile.get("target_device_signatures", []),
            "mapping_families": profile.get("mapping_families", []),
            "link_family_sources": profile.get("link_family_sources", []),
            "link_instance_ids": profile.get("link_instance_ids", []),
            "member_sheets": profile.get("member_sheets", []),
            "user_link_infos": profile.get("user_link_infos", []),
            "device_role_infos": profile.get("device_role_infos", []),
            "shared_semantic_hints": profile.get("shared_semantic_hints", []),
        })
    return {
        "execution_mode": "balanced_source_device_sessions",
        "purpose": "先统一整理链路族/链路实例/器件角色语义，再让各源端器件 subagent 在小 TASK 内逐条选择源端 pin。",
        "rules": [
            "global_link_plan 只提供链路级语义和执行规划，不选择 pin。",
            "每个 subagent_session 对应一个源端器件 pin 体系，可以顺序处理多个小 TASK。",
            "小 TASK 用于降低单次推理负担；不要因为 TASK 变多就为同一个源端器件启动互不共享 state 的 subagent。",
            "跨 TASK 的 pin 占用、允许复用和冲突必须通过 pin_allocation_state_file 传递。",
        ],
        "link_families": families,
        "subagent_sessions": [
            {
                "subagent_session_id": session.get("subagent_session_id", ""),
                "source_device_signature": session.get("source_device_signature", ""),
                "line_count": session.get("line_count", 0),
                "task_count": len(session.get("tasks", [])),
                "pin_allocation_state_file": session.get("pin_allocation_state_file", ""),
                "session_context_file": session.get("session_context_file", ""),
            }
            for session in sessions
        ],
    }


def render_global_link_plan(plan: Dict[str, Any]) -> str:
    lines = [
        "# Global Link Plan",
        "",
        plan.get("purpose", ""),
        "",
        "## Execution Rules",
        "",
    ]
    for rule in plan.get("rules", []):
        lines.append(f"- {rule}")
    lines.extend([
        "",
        "## Link Families",
        "",
        "| link_family | lines | contexts | sources | mapping_families | user_info |",
        "|---|---:|---:|---|---|---|",
    ])
    for family in plan.get("link_families", []):
        lines.append(
            "| {family_id} | {lines_count} | {contexts} | {sources} | {mapping} | {info} |".format(
                family_id=str(family.get("link_family_id", "")).replace("|", "/"),
                lines_count=family.get("line_count", 0),
                contexts=family.get("context_group_count", 0),
                sources=", ".join(family.get("source_device_signatures", [])[:4]).replace("|", "/"),
                mapping=", ".join(family.get("mapping_families", [])[:4]).replace("|", "/"),
                info="; ".join(family.get("user_link_infos", [])[:2]).replace("|", "/"),
            )
        )
    return "\n".join(lines) + "\n"


def normalize_match_text(value: Any) -> str:
    return str(value or "").upper()


RULE_LAYER_BASE_SCORE = {
    "custom": 400.0,
    "link": 300.0,
    "device": 200.0,
    "signal": 100.0,
    "global": 50.0,
    "unknown": 0.0,
}

RULE_FIELD_ALIASES = {
    "source_devices": {"源端器件", "SOURCE_DEVICE", "SOURCE_DEVICES"},
    "target_devices": {"目标器件", "典型目标", "TARGET_DEVICE", "TARGET_DEVICES"},
    "link_families": {"链路类型", "链路族", "LINK_FAMILY", "LINK_FAMILIES"},
    "mapping_families": {"映射族", "MAPPING_FAMILY", "MAPPING_FAMILIES"},
    "ports": {"典型端口", "PORTS", "TYPICAL_PORTS"},
}


def canonical_part_id(value: Any) -> str:
    text = normalize_match_text(value).strip()
    if text.isdigit():
        return text.lstrip("0") or "0"
    return text


def split_rule_values(value: str) -> List[str]:
    return [
        item.strip()
        for item in re.split(r"[/,，;；、]+", value)
        if item.strip()
    ]


def parse_rule_metadata(text: str) -> Dict[str, List[str]]:
    metadata = {key: [] for key in RULE_FIELD_ALIASES}
    alias_to_key = {
        normalize_match_text(alias): key
        for key, aliases in RULE_FIELD_ALIASES.items()
        for alias in aliases
    }
    for raw_line in text.splitlines():
        line = raw_line.strip()
        match = re.match(r"^([^:：]+)[:：]\s*(.+)$", line)
        if not match:
            continue
        key = alias_to_key.get(normalize_match_text(match.group(1)).strip())
        if not key:
            continue
        for value in split_rule_values(match.group(2)):
            if value not in metadata[key]:
                metadata[key].append(value)
    return metadata


def infer_rule_layer(source_file: str, rule_id: str, metadata: Dict[str, List[str]]) -> str:
    source = normalize_match_text(source_file).replace("\\", "/")
    rid = normalize_match_text(rule_id)
    if "/LINK_RULES/" in source:
        return "link"
    if "/DEVICE_RULES/" in source:
        return "device"
    if "/SIGNAL_RULES/" in source:
        return "signal"
    if source.endswith("/GLOBAL_MAPPING_RULES.MD"):
        return "global"
    if source:
        return "custom"
    if rid.startswith("LINK_") or metadata.get("link_families"):
        return "link"
    if rid.startswith("SIGNAL_") or metadata.get("mapping_families"):
        return "signal"
    if rid == "GLOBAL_MAPPING":
        return "global"
    if metadata.get("source_devices"):
        return "device"
    return "unknown"


def extract_rule_blocks(text: str) -> List[Dict[str, Any]]:
    pattern = re.compile(r"^### RULE:\s*(.+?)\s*$", re.MULTILINE)
    matches = list(pattern.finditer(text))
    source_pattern = re.compile(r"<!--\s*SOURCE:\s*(.+?)\s*-->", re.IGNORECASE)
    source_matches = list(source_pattern.finditer(text))
    blocks: List[Dict[str, Any]] = []
    for idx, match in enumerate(matches):
        start = match.start()
        next_rule = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        next_section_match = re.search(r"^##\s+", text[match.end():], re.MULTILINE)
        next_section = match.end() + next_section_match.start() if next_section_match else len(text)
        next_source_match = source_pattern.search(text, match.end())
        next_source = next_source_match.start() if next_source_match else len(text)
        end = min(next_rule, next_section, next_source)
        title = match.group(1).strip()
        rule_id = title.split()[0] if title else f"RULE_{idx + 1}"
        if rule_id.startswith("<"):
            continue
        block_text = text[start:end].strip()
        source_file = ""
        for source_match in source_matches:
            if source_match.start() >= start:
                break
            source_file = source_match.group(1).strip()
        metadata = parse_rule_metadata(block_text)
        blocks.append({
            "rule_id": rule_id,
            "title": title,
            "text": block_text,
            "source_file": source_file,
            "layer": infer_rule_layer(source_file, rule_id, metadata),
            "metadata": metadata,
            "source_order": idx,
        })
    return blocks


def add_term(terms: Dict[str, float], value: Any, weight: float) -> None:
    text = normalize_match_text(value).strip()
    if not text:
        return
    terms[text] = max(terms.get(text, 0.0), weight)
    if ":" in text:
        tail = text.split(":", 1)[1].strip()
        if tail:
            terms[tail] = max(terms.get(tail, 0.0), weight)
    stripped_index = re.sub(r"\d+$", "", text)
    if stripped_index and stripped_index != text and len(stripped_index) >= 2:
        terms[stripped_index] = max(terms.get(stripped_index, 0.0), weight * 0.8)


def collect_rule_match_terms(group: Dict[str, Any], rows: List[Dict[str, Any]]) -> Dict[str, float]:
    terms: Dict[str, float] = {}
    add_term(terms, group.get("source_device_signature"), 6.0)
    for value in group.get("link_family_ids", []):
        add_term(terms, value, 5.0)
    for value in group.get("mapping_families", []):
        add_term(terms, value, 3.0)
    for value in group.get("target_device_signatures", []):
        add_term(terms, value, 0.75)
    for value in group.get("source_device_instances", []):
        add_term(terms, value, 2.0)
    for value in group.get("target_device_instances", []):
        add_term(terms, value, 0.75)
    for value in group.get("user_link_infos", []):
        add_term(terms, value, 1.5)
    for value in group.get("device_role_infos", []):
        add_term(terms, value, 1.5)

    for row in rows:
        for key, weight in [
            ("source_part_id", 6.0),
            ("source_block_name", 2.5),
            ("source_block_id", 2.0),
            ("source_port", 2.5),
            ("target_block_name", 0.75),
            ("target_port", 0.75),
            ("connection_name", 1.5),
            ("link_family_id", 5.0),
            ("link_instance_id", 2.0),
            ("user_link_info", 1.5),
            ("device_role_info", 1.5),
        ]:
            add_term(terms, row.get(key), weight)
    return terms


def values_match(rule_values: List[str], context_values: List[Any]) -> bool:
    for rule_value in rule_values:
        rule_text = normalize_match_text(rule_value).strip()
        if not rule_text:
            continue
        rule_part = canonical_part_id(rule_text)
        for context_value in context_values:
            context_text = normalize_match_text(context_value).strip()
            if not context_text:
                continue
            if rule_text == context_text:
                return True
            if rule_part == canonical_part_id(context_text):
                return True
            if (
                min(len(rule_text), len(context_text)) >= 4
                and not rule_text.isdigit()
                and not context_text.isdigit()
                and (rule_text in context_text or context_text in rule_text)
            ):
                return True
    return False


def row_signal_shapes(rows: List[Dict[str, Any]]) -> set[str]:
    shapes: set[str] = set()
    for row in rows:
        direct = normalize_match_text(row.get("signal_shape", "")).lower()
        if direct:
            shapes.add(direct)
        info = row.get("signal_shape_info", {})
        if isinstance(info, dict):
            nested = normalize_match_text(info.get("shape", "")).lower()
            if nested:
                shapes.add(nested)
    return shapes


def deterministic_rule_match(
    block: Dict[str, Any],
    group: Dict[str, Any],
    rows: List[Dict[str, Any]],
) -> tuple[str, float, List[str]] | None:
    layer = block.get("layer", "unknown")
    metadata = block.get("metadata", {})
    rid = normalize_match_text(block.get("rule_id", ""))
    source_parts = [row.get("source_part_id", "") for row in rows]
    source_devices = (
        source_parts
        + [row.get("source_block_name", "") for row in rows]
        + [row.get("source_block_id", "") for row in rows]
        + group.get("source_device_instances", [])
    )
    target_devices = (
        [row.get("target_part_id", "") for row in rows]
        + [row.get("target_block_name", "") for row in rows]
        + [row.get("target_block_id", "") for row in rows]
        + group.get("target_device_instances", [])
    )
    link_families = (
        group.get("link_family_ids", [])
        + [row.get("link_family_id", "") for row in rows]
    )
    mapping_families = (
        group.get("mapping_families", [])
        + [infer_mapping_family(row) for row in rows]
    )
    ports = [
        value
        for row in rows
        for value in [row.get("source_port", ""), row.get("target_port", "")]
    ]
    shapes = row_signal_shapes(rows)

    if layer == "link" and values_match(metadata.get("link_families", []), link_families):
        return "exact_link_family", RULE_LAYER_BASE_SCORE["link"], [
            f"link_family:{value}" for value in link_families if value
        ]

    if layer == "device":
        exact_part = any(
            canonical_part_id(rid) == canonical_part_id(part)
            for part in source_parts
            if rid and part
        )
        source_match = exact_part or values_match(metadata.get("source_devices", []), source_devices)
        target_rules = metadata.get("target_devices", [])
        target_match = not target_rules or values_match(target_rules, target_devices)
        if source_match and target_match:
            match_type = "exact_source_part" if exact_part else "device_conditions"
            evidence = [f"source_device:{value}" for value in source_devices if value]
            evidence.extend(f"target_device:{value}" for value in target_devices if value)
            return match_type, RULE_LAYER_BASE_SCORE["device"], evidence[:12]

    if layer == "signal":
        if rid == "SIGNAL_SPECIAL":
            return "always_include_special", RULE_LAYER_BASE_SCORE["signal"], ["global_special_connection_policy"]
        if rid == "SIGNAL_DIFF" and "differential" in shapes:
            return "signal_shape", RULE_LAYER_BASE_SCORE["signal"], ["signal_shape:differential"]
        if values_match(metadata.get("mapping_families", []), mapping_families):
            return "exact_mapping_family", RULE_LAYER_BASE_SCORE["signal"], [
                f"mapping_family:{value}" for value in mapping_families if value
            ]
        if values_match(metadata.get("ports", []), ports):
            return "signal_port_family", RULE_LAYER_BASE_SCORE["signal"], [
                f"port:{value}" for value in ports if value
            ][:12]

    if layer == "global" or rid == "GLOBAL_MAPPING":
        return "always_include_global", RULE_LAYER_BASE_SCORE["global"], ["global_mapping_policy"]

    if layer == "custom":
        source_ok = not metadata.get("source_devices") or values_match(metadata["source_devices"], source_devices)
        target_ok = not metadata.get("target_devices") or values_match(metadata["target_devices"], target_devices)
        link_ok = not metadata.get("link_families") or values_match(metadata["link_families"], link_families)
        mapping_ok = not metadata.get("mapping_families") or values_match(metadata["mapping_families"], mapping_families)
        has_conditions = any(metadata.values())
        if has_conditions and source_ok and target_ok and link_ok and mapping_ok:
            return "custom_rule_conditions", RULE_LAYER_BASE_SCORE["custom"], ["custom_rule_applicability"]
    return None


def lexical_rule_score(block: Dict[str, Any], terms: Dict[str, float]) -> tuple[float, List[str]]:
    text = normalize_match_text(block.get("text", ""))
    score = 0.0
    matched_terms: List[str] = []
    for term, weight in sorted(terms.items(), key=lambda item: (-len(item[0]), -item[1], item[0])):
        if len(term) < 2 or term.startswith("LINE"):
            continue
        if term not in text:
            continue
        if any(term in selected or selected in term for selected in matched_terms):
            continue
        score += weight
        matched_terms.append(term)
    return score, matched_terms


def effective_rule_blocks(rule_blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """同 rule_id 后出现的 project/user 规则覆盖前面的内置规则。"""
    latest_by_id: Dict[str, Dict[str, Any]] = {}
    for block in rule_blocks:
        latest_by_id[normalize_match_text(block.get("rule_id", ""))] = block
    return sorted(latest_by_id.values(), key=lambda block: block.get("source_order", 0))


def match_rule_sections(rule_blocks: List[Dict[str, Any]], group: Dict[str, Any], rows: List[Dict[str, Any]], limit: int = 12, min_score: float = 5.0) -> List[Dict[str, Any]]:
    terms = collect_rule_match_terms(group, rows)
    deterministic = []
    lexical = []
    deterministic_ids: set[str] = set()
    blocks = effective_rule_blocks(rule_blocks)

    for block in blocks:
        result = deterministic_rule_match(block, group, rows)
        if not result:
            continue
        match_type, score, evidence = result
        deterministic.append({
            "rule_id": block.get("rule_id", ""),
            "title": block.get("title", ""),
            "score": round(score, 2),
            "matched_terms": evidence[:30],
            "text": block.get("text", ""),
            "layer": block.get("layer", "unknown"),
            "source_file": block.get("source_file", ""),
            "match_type": match_type,
        })
        deterministic_ids.add(normalize_match_text(block.get("rule_id", "")))

    for block in blocks:
        if normalize_match_text(block.get("rule_id", "")) in deterministic_ids:
            continue
        layer = block.get("layer", "unknown")
        metadata = block.get("metadata", {})
        if layer == "device" and metadata.get("source_devices"):
            continue
        if layer == "link" and metadata.get("link_families"):
            continue
        if layer == "signal" and (metadata.get("mapping_families") or metadata.get("ports")):
            continue
        if layer == "custom" and any(metadata.values()):
            continue
        score, matched_terms = lexical_rule_score(block, terms)
        if score < min_score:
            continue
        lexical.append({
            "rule_id": block.get("rule_id", ""),
            "title": block.get("title", ""),
            "score": round(score, 2),
            "matched_terms": matched_terms[:30],
            "text": block.get("text", ""),
            "layer": block.get("layer", "unknown"),
            "source_file": block.get("source_file", ""),
            "match_type": "lexical_fallback",
        })

    deterministic.sort(key=lambda item: (-item["score"], item["rule_id"]))
    lexical.sort(key=lambda item: (-item["score"], item["rule_id"]))
    remaining_slots = max(0, limit - len(deterministic))
    return deterministic + lexical[:remaining_slots]

def render_shared_prompt() -> str:
    semantic_prompt = Path(__file__).resolve().parent.parent / "prompts" / "semantic_mapping_resolver.md"
    lines = [
        "# Subagent Model Resolution Task Prompt",
        "",
        "同一个 subagent 按 session_plan 顺序处理所属 TASK；每个 TASK 只裁决 output_contract.expected_line_ids。",
        "必须使用 sessions_spawn 命令真实启动模型 subagent 分析本 session / TASK；启动或等待超时时间必须设置为 30 分钟（1800000 ms），超时则不能进入 finish。",
        "禁止编写 Python / PowerShell / JavaScript 等脚本来分析 TASK、匹配 pin、生成 mapping_decision 或跳过 sessions_spawn；selected_pin 的语义裁决必须由模型完成。工具只可用于读取输入、写 JSONL/state、做格式和覆盖校验。",
        f"语义规则只读取一次：{semantic_prompt}",
        "",
        "每个 TASK 的执行顺序：",
        "1. 读取 task_scope.session_context_file；其中保存本 session 共用的 link_family_profiles、rule_library 和跨 TASK pin 共享关系。",
        "2. 读取 task_scope.pin_allocation_state_file 的最新状态；不要使用生成 TASK 时的旧快照。",
        "3. 按 matched_rule_refs 在 session_context.rule_library 中读取本 TASK 的规则正文。",
        "4. 分析 normalized_connections；connection_defaults 说明省略字段的确定默认值。",
        "5. 单 pin source_port 若逐字存在于 source_device_pins，selected_pin 必须直接等于 source_port，任何规则不得再次映射；否则才做语义选择。大 pin 表找不到时读取 pin_catalog_context.group_file 的其他 groups 或 all_pins。",
        "6. 把 JSONL 写入 output_contract.output_file，并校验 expected_line_ids 覆盖关系。",
        "7. 更新 pin_allocation_state_file 中对应 physical_device_instance_id 的 used_pins、共享组、冲突和 completed_task_ids。",
        "8. 完成本 session 全部 TASK 后，主控必须把 subagent_session_status.json 中对应 session 标记为 completed=true、failed=false、timed_out=false；失败/超时重跑完成前禁止 finish。",
        "9. 主控正式收尾必须直接执行 intermediate/finish_command.txt；不得手工 merge/validate/render，不得调用 render_outputs.py 或编写替代脚本。",
        "",
        "本 skill 只输出 pin 裁决字段，不输出网络命名字段；最终 Excel 的网络命名列保持为空，分析说明不得添加网络命名依据。",
        "聊天回复只报告 status、output_file、decision_count 和 state 是否更新，不要粘贴完整结果。",
        "",
    ]
    return "\n".join(lines)


def build_session_status(sessions: List[Dict[str, Any]], existing_status: Dict[str, Any] | None = None) -> Dict[str, Any]:
    existing_by_id: Dict[str, Dict[str, Any]] = {}
    if isinstance(existing_status, dict):
        for session in existing_status.get("sessions", []):
            if isinstance(session, dict):
                session_id = str(session.get("subagent_session_id", ""))
                if session_id:
                    existing_by_id[session_id] = session

    status_sessions: List[Dict[str, Any]] = []
    for session in sessions:
        session_id = str(session.get("subagent_session_id", ""))
        task_ids = [str(task.get("task_id", "")) for task in session.get("tasks", [])]
        output_files = [str(task.get("output_file", "")) for task in session.get("tasks", [])]
        previous = existing_by_id.get(session_id, {})
        previous_task_ids = [str(x) for x in previous.get("expected_task_ids", [])]
        task_set_changed = bool(previous) and previous_task_ids != task_ids

        status_sessions.append({
            "subagent_session_id": session_id,
            "source_device_signature": session.get("source_device_signature", ""),
            "readable_device_type": session.get("readable_device_type", ""),
            "source_part_id": session.get("source_part_id", ""),
            "expected_task_ids": task_ids,
            "output_files": output_files,
            "sessions_spawn_required": True,
            "spawned": bool(previous.get("spawned", False)) and not task_set_changed,
            "completed": bool(previous.get("completed", False)) and not task_set_changed,
            "failed": bool(previous.get("failed", False)) or task_set_changed,
            "timed_out": bool(previous.get("timed_out", False)) and not task_set_changed,
            "rerun_required": bool(previous.get("rerun_required", False)) or task_set_changed,
            "completed_task_ids": [] if task_set_changed else previous.get("completed_task_ids", []),
            "failed_task_ids": task_ids if task_set_changed else previous.get("failed_task_ids", []),
            "sessions_spawn_thread_id": previous.get("sessions_spawn_thread_id", ""),
            "last_checked_at": previous.get("last_checked_at", ""),
            "notes": (
                "TASK list changed after status was recorded; rerun this session before finish."
                if task_set_changed
                else previous.get("notes", "")
            ),
        })

    return {
        "status_file_contract": "Main controller updates this file after waiting for each sessions_spawn run. finish requires every session to be spawned and completed with no failed/timed_out/rerun_required flags.",
        "execution_mode": "balanced_source_device_sessions",
        "session_count": len(status_sessions),
        "task_count": sum(len(session.get("expected_task_ids", [])) for session in status_sessions),
        "sessions": status_sessions,
    }


def build_model_resolution_tasks(
    context_groups_path: str | Path,
    normalized_path: str | Path,
    needs_model_path: str | Path,
    output_dir: str | Path,
    pins_path: str | Path | None = None,
    rules_path: str | Path | None = None,
) -> Dict[str, Any]:
    output_dir = ensure_dir(output_dir)
    cleanup_model_task_output_dir(output_dir)
    tasks_dir = ensure_dir(output_dir / "tasks")
    subagent_outputs_dir = ensure_dir(output_dir.parent / "subagent_outputs")
    shared_prompt_path = output_dir / "subagent_task_prompt.md"
    shared_prompt_path.write_text(render_shared_prompt(), encoding="utf-8")
    normalized_by_id = load_by_line_id(normalized_path)

    # Use the shared pin catalog loader so TASK payloads support native JSON,
    # {"pins": ...}, CSV, JSONL, and Excel.
    device_pins: Dict[str, List[str]] = {}
    if pins_path and Path(pins_path).exists():
        device_pins = load_pin_catalog(pins_path)
    skill_root = Path(__file__).resolve().parents[1]
    resolved_rules_path = Path(rules_path) if rules_path else skill_root / "rules" / "combined_mapping_rules.md"
    rules_text = resolved_rules_path.read_text(encoding="utf-8") if resolved_rules_path.exists() else ""
    rule_blocks = extract_rule_blocks(rules_text)
    needs_rows = list(iter_jsonl(needs_model_path))
    needed_ids = {row["line_id"] for row in needs_rows}

    context_data = read_json(context_groups_path, {"context_groups": []})
    context_groups = context_data.get("context_groups", [])
    link_family_profiles = build_link_family_profiles(context_groups, normalized_by_id)
    tasks: List[Dict[str, Any]] = []
    sessions_by_id: Dict[str, Dict[str, Any]] = {}
    skipped_tasks: List[Dict[str, Any]] = []
    subagent_state_dir = ensure_dir(output_dir.parent / "subagent_state")

    for group in context_groups:
        group_line_ids = [line_id for line_id in group.get("line_ids", []) if line_id in needed_ids]
        if not group_line_ids:
            continue
        context_id = group.get("context_group_id") or f"CTX_{len(tasks)+1}"
        session_id = f"SESSION_{filename_slug(readable_device_type(group), 'DEVICE', 24)}_{filename_slug(source_part_label(group), 'UNKNOWN_PART', 24)}_{context_id.replace('CTX_', '')}"
        session_state_file = subagent_state_dir / f"{session_id}.pin_allocation_state.json"
        session_context_file = subagent_state_dir / f"{session_id}.session_context.json"
        session_pin_group_file = subagent_state_dir / f"{session_id}.pin_groups.json"

        # 收集本组所有 normalized_connections 中的 source_part_id -> 真实 pin 列表。
        # pin_info 缺失时整个源端器件 session 跳过，不生成语义模型任务。
        full_group_nc = [normalized_by_id[lid] for lid in group_line_ids if lid in normalized_by_id]
        source_pins_map: Dict[str, List[str]] = {}
        source_pin_aliases: Dict[str, str] = {}
        for nc in full_group_nc:
            code = nc.get("source_part_id", "")
            if code and code not in source_pins_map:
                source_pins_map[code] = pins_for_part(device_pins, code)
                resolved_code = resolve_catalog_key(device_pins, code)
                if resolved_code != code:
                    source_pin_aliases[code] = resolved_code

        if not any(source_pins_map.values()):
            skipped_tasks.append({
                "context_group_id": context_id,
                "line_ids": group_line_ids,
                "line_count": len(group_line_ids),
                "source_device_signature": group.get("source_device_signature", ""),
                "source_part_ids": sorted({nc.get("source_part_id", "") for nc in full_group_nc if nc.get("source_part_id")}),
                "reason": "pin_info_missing_for_source_device",
                "message": "入参 pin_info.json 中没有对应源端器件编码的 pin 列表，按约束跳过该器件的语义模型分析；最终保留 pre_resolve 的 unresolved 结果。",
            })
            continue

        primary_source_code = next(
            code for code, pins in source_pins_map.items() if pins
        )
        primary_source_pins = source_pins_map[primary_source_code]
        session_pin_group_catalog: Dict[str, Any] | None = None
        if len(primary_source_pins) > PIN_GROUP_THRESHOLD:
            session_pin_group_catalog = build_pin_group_catalog(
                primary_source_code,
                primary_source_pins,
            )
            session_pin_group_catalog["aliases"] = source_pin_aliases
            session_pin_group_catalog["usage"] = (
                "TASK 只内嵌当前相关组且不排序。当前组找不到合理 pin 时，"
                "读取本文件的其他 groups 或 all_pins；最终合法性仍以原始 pin_info 为准。"
            )
            write_json(session_pin_group_file, session_pin_group_catalog)

        session = sessions_by_id.setdefault(session_id, {
            "subagent_session_id": session_id,
            "context_group_id": context_id,
            "recommended_subagent": group.get("recommended_subagent", "semantic-mapping-subagent"),
            "prompt_file": str(shared_prompt_path),
            "source_device_signature": group.get("source_device_signature", ""),
            "readable_device_type": readable_device_type(group),
            "source_part_id": source_part_label(group),
            "line_ids": [],
            "line_count": 0,
            "pin_allocation_state_file": str(session_state_file),
            "session_context_file": str(session_context_file),
            "pin_group_file": str(session_pin_group_file) if session_pin_group_catalog else "",
            "tasks": [],
        })

        session_family_ids = group.get("link_family_ids") or [
            group.get("link_family_id") or "LOCAL_DEVICE_MAPPING"
        ]
        session_context = {
            "subagent_session_id": session_id,
            "context_group_id": context_id,
            "source_device_signature": group.get("source_device_signature", ""),
            "usage": "同一 source_device session 只读取一次的静态上下文；TASK 只保存本批连接和引用。",
            "sheet_device_context": build_sheet_device_context(full_group_nc),
            "pin_allocation_context": build_pin_allocation_context(full_group_nc),
            "link_family_profiles": {
                family_id: link_family_profiles.get(family_id, {})
                for family_id in session_family_ids
            },
            "rule_library": {},
        }
        session_rule_library: Dict[str, Dict[str, Any]] = {}

        if not session_state_file.exists():
            write_json(session_state_file, {
                "subagent_session_id": session_id,
                "source_device_signature": group.get("source_device_signature", ""),
                "source_part_id": source_part_label(group),
                "purpose": "同一源端器件 subagent 跨多个小 TASK 共享的 pin 分配状态；pin 占用必须按 physical_device_instance_id 分开记录；subagent 每完成一个 TASK 后更新。",
                "pin_usage_scope": "per_physical_device_instance_id",
                "physical_device_instances": pin_state_instances(full_group_nc),
                "used_pins": [],
                "allowed_shared_pin_groups": [],
                "unresolved_conflicts": [],
                "completed_task_ids": [],
            })

        task_chunks = split_balanced_line_tasks(group, full_group_nc, DEFAULT_MAX_LINES_PER_MODEL_TASK)
        previous_task_outputs: List[str] = []
        for chunk_index, line_ids in enumerate(task_chunks, start=1):
            group_nc = [normalized_by_id[lid] for lid in line_ids if lid in normalized_by_id]
            task_group = scoped_group(group, group_nc, line_ids)
            task_number = len(tasks) + 1
            file_stem = task_file_stem(task_number, task_group, context_id)
            if len(task_chunks) > 1:
                file_stem = f"{file_stem}_PART{chunk_index:02d}"
            task_display_name = f"{readable_device_type(task_group)} / {source_part_label(task_group)} / {readable_family_scope(task_group)} / part {chunk_index} of {len(task_chunks)}"
            output_file = subagent_outputs_dir / f"{file_stem}.jsonl"
            task_physical_device_instance_ids = sorted({physical_device_instance_id(row) for row in group_nc})
            output_contract = {
                "output_file": str(output_file),
                "expected_line_ids": line_ids,
            }
            task_scope = {
                "subagent_session_id": session_id,
                "subtask_index_in_session": chunk_index,
                "subtask_count_in_session": len(task_chunks),
                "physical_device_instance_ids": task_physical_device_instance_ids,
                "pin_allocation_state_file": str(session_state_file),
                "session_context_file": str(session_context_file),
                "previous_task_outputs": list(previous_task_outputs),
            }
            task_source_pins = source_pins_map
            pin_catalog_context = {
                "mode": "inline_full",
                "pin_count": len(primary_source_pins),
                "authoritative_source": "source_device_pins",
                "final_validation_source": "original_pin_info",
            }
            if session_pin_group_catalog:
                available_group_ids = list(session_pin_group_catalog.get("groups", {}).keys())
                current_group_ids = task_pin_group_ids(
                    task_group,
                    group_nc,
                    available_group_ids,
                )
                current_group_pins = pins_for_groups(
                    session_pin_group_catalog,
                    current_group_ids,
                )
                if not current_group_pins:
                    current_group_ids = available_group_ids
                    current_group_pins = list(primary_source_pins)
                task_source_pins = {
                    code: list(current_group_pins)
                    for code, pins in source_pins_map.items()
                    if pins
                }
                pin_catalog_context = {
                    "mode": "grouped_large_catalog",
                    "pin_count": len(primary_source_pins),
                    "grouping_threshold": PIN_GROUP_THRESHOLD,
                    "group_file": str(session_pin_group_file),
                    "current_group_ids": current_group_ids,
                    "current_group_pin_count": len(current_group_pins),
                    "current_groups_are_ranked": False,
                    "current_view_is_closed": False,
                    "fallback": "当前组找不到合理 pin 时，读取 group_file 中其他 groups 或 all_pins。",
                    "authoritative_source": "group_file.all_pins",
                    "final_validation_source": "original_pin_info",
                }
            task_rule_sections = match_rule_sections(rule_blocks, task_group, group_nc)
            task_rule_refs = []
            for rule in task_rule_sections:
                rule_key = f"{rule.get('layer', 'unknown')}:{rule.get('rule_id', '')}"
                session_rule_library[rule_key] = {
                    "rule_id": rule.get("rule_id", ""),
                    "title": rule.get("title", ""),
                    "text": rule.get("text", ""),
                    "layer": rule.get("layer", "unknown"),
                    "source_file": rule.get("source_file", ""),
                }
                task_rule_refs.append({
                    "rule_key": rule_key,
                    "match_type": rule.get("match_type", ""),
                    "matched_terms": rule.get("matched_terms", []),
                })

            task_payload = {
                "task_id": file_stem,
                "task_display_name": task_display_name,
                "task_scope": task_scope,
                "context_group": slim_context_group(task_group),
                "source_device_pins": task_source_pins,
                "pin_catalog_context": pin_catalog_context,
                "diagram_link_context": build_diagram_link_context(task_group, group_nc),
                "connection_defaults": connection_defaults(),
                "normalized_connections": [
                    compact_normalized_connection(row)
                    for row in group_nc
                ],
                "matched_rule_refs": task_rule_refs,
                "output_contract": output_contract,
                "schema_file": str(skill_root / "schemas" / "mapping_decision.schema.json"),
            }
            task_json = tasks_dir / f"{file_stem}.json"
            write_json(task_json, task_payload)

            task_info = {
                "task_id": file_stem,
                "task_display_name": task_display_name,
                "context_group_id": context_id,
                "subagent_session_id": session_id,
                "task_scope": task_scope,
                "line_ids": line_ids,
                "line_count": len(line_ids),
                "task_json": str(task_json),
                "output_file": str(output_file),
                "output_contract": output_contract,
                "prompt_file": str(shared_prompt_path),
                "pin_allocation_state_file": str(session_state_file),
                "session_context_file": str(session_context_file),
                "pin_group_file": str(session_pin_group_file) if session_pin_group_catalog else "",
                "physical_device_instance_ids": task_scope["physical_device_instance_ids"],
                "recommended_subagent": task_group.get("recommended_subagent", "semantic-mapping-subagent"),
                "readable_device_type": readable_device_type(task_group),
                "source_part_id": source_part_label(task_group),
                "device_category": task_group.get("device_category", ""),
                "link_family_id": task_group.get("link_family_id", ""),
                "link_family_source": task_group.get("link_family_source", ""),
                "link_family_ids": task_group.get("link_family_ids", []),
                "link_family_sources": task_group.get("link_family_sources", []),
                "analysis_strategy": task_group.get("analysis_strategy", ""),
                "source_device_signature": task_group.get("source_device_signature", ""),
                "target_device_signature": task_group.get("target_device_signature", ""),
                "target_device_signatures": task_group.get("target_device_signatures", []),
                "link_instance_ids": task_group.get("link_instance_ids", []),
                "link_member_sheets": task_group.get("link_member_sheets", []),
                "user_link_infos": task_group.get("user_link_infos", []),
                "device_role_infos": task_group.get("device_role_infos", []),
                "mapping_family": task_group.get("mapping_family", ""),
                "mapping_families": task_group.get("mapping_families", []),
                "source_sheets": task_group.get("source_sheets", []),
                "link_family_profile_ids": list((task_group.get("link_family_ids") or [task_group.get("link_family_id") or "LOCAL_DEVICE_MAPPING"])),
            }
            task_info["task_goal"] = describe_subagent_task(task_info, task_group)
            tasks.append(task_info)
            session["tasks"].append(task_info)
            session["line_ids"].extend(line_ids)
            session["line_count"] += len(line_ids)
            previous_task_outputs.append(str(output_file))

        session_context["rule_library"] = {
            key: session_rule_library[key]
            for key in sorted(session_rule_library)
        }
        write_json(session_context_file, session_context)

    sessions = list(sessions_by_id.values())
    global_link_plan = build_global_link_plan(link_family_profiles, sessions)
    global_link_plan_json = output_dir / "global_link_plan.json"
    global_link_plan_md = output_dir / "global_link_plan.md"
    write_json(global_link_plan_json, global_link_plan)
    global_link_plan_md.write_text(render_global_link_plan(global_link_plan), encoding="utf-8")

    plan_tasks = [
        {
            "task_id": task.get("task_id", ""),
            "task_display_name": task.get("task_display_name", ""),
            "context_group_id": task.get("context_group_id", ""),
            "subagent_session_id": task.get("subagent_session_id", ""),
            "line_ids": task.get("line_ids", []),
            "line_count": task.get("line_count", 0),
            "task_json": task.get("task_json", ""),
            "output_file": task.get("output_file", ""),
            "prompt_file": task.get("prompt_file", ""),
        }
        for task in tasks
    ]
    plan_sessions = [
        {
            "subagent_session_id": session.get("subagent_session_id", ""),
            "source_device_signature": session.get("source_device_signature", ""),
            "readable_device_type": session.get("readable_device_type", ""),
            "source_part_id": session.get("source_part_id", ""),
            "line_count": session.get("line_count", 0),
            "prompt_file": session.get("prompt_file", ""),
            "pin_allocation_state_file": session.get("pin_allocation_state_file", ""),
            "session_context_file": session.get("session_context_file", ""),
            "pin_group_file": session.get("pin_group_file", ""),
            "tasks": [
                {
                    "task_id": task.get("task_id", ""),
                    "task_json": task.get("task_json", ""),
                    "output_file": task.get("output_file", ""),
                    "line_count": task.get("line_count", 0),
                }
                for task in session.get("tasks", [])
            ],
        }
        for session in sessions
    ]

    session_plan = {
        "execution_mode": "balanced_source_device_sessions",
        "finish_contract": {
            "required_entrypoint": "run_pipeline.py --stage finish",
            "working_directory": str(Path(__file__).resolve().parents[1]),
            "command_file": str((output_dir.parent / "finish_command.txt").resolve()),
            "manual_merge_validate_render_forbidden": True,
        },
        "session_count": len(sessions),
        "task_count": len(tasks),
        "line_count": sum(t["line_count"] for t in tasks),
        "sessions": plan_sessions,
    }
    session_plan_json = output_dir / "subagent_session_plan.json"
    session_plan_md = output_dir / "subagent_session_plan.md"
    session_status_json = output_dir / "subagent_session_status.json"
    write_json(session_plan_json, session_plan)
    session_plan_md.write_text(render_subagent_session_plan(sessions), encoding="utf-8")
    existing_status = read_json(session_status_json, None)
    write_json(session_status_json, build_session_status(sessions, existing_status))

    subagent_plan = {
        "execution_mode": "balanced_source_device_sessions",
        "task_count": len(tasks),
        "line_count": sum(t["line_count"] for t in tasks),
        "session_count": len(sessions),
        "skipped_task_count": len(skipped_tasks),
        "skipped_line_count": sum(t["line_count"] for t in skipped_tasks),
        "subagent_session_plan_json": str(session_plan_json),
        "subagent_session_status_json": str(session_status_json),
        "skipped_tasks": skipped_tasks,
        "tasks": plan_tasks,
    }
    plan_json = output_dir / "subagent_task_plan.json"
    plan_md = output_dir / "subagent_task_plan.md"
    write_json(plan_json, subagent_plan)
    plan_md.write_text(render_subagent_task_plan(tasks, skipped_tasks), encoding="utf-8")

    manifest = {
        "execution_mode": "balanced_source_device_sessions",
        "finish_contract": session_plan["finish_contract"],
        "task_count": len(tasks),
        "line_count": sum(t["line_count"] for t in tasks),
        "session_count": len(sessions),
        "skipped_task_count": len(skipped_tasks),
        "skipped_line_count": sum(t["line_count"] for t in skipped_tasks),
        "global_link_plan_json": str(global_link_plan_json),
        "global_link_plan_md": str(global_link_plan_md),
        "subagent_session_plan_json": str(session_plan_json),
        "subagent_session_plan_md": str(session_plan_md),
        "subagent_session_status_json": str(session_status_json),
        "subagent_task_plan_json": str(plan_json),
        "subagent_task_plan_md": str(plan_md),
        "subagent_task_prompt_md": str(shared_prompt_path),
        "tasks_dir": str(tasks_dir),
        "subagent_outputs_dir": str(subagent_outputs_dir),
        "subagent_state_dir": str(subagent_state_dir),
        "tasks": plan_tasks,
    }
    write_json(output_dir / "manifest.json", manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--context-groups", required=True)
    parser.add_argument("--normalized", required=True)
    parser.add_argument("--needs-model", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--pins", default=None, help="block_info_pin.json 路径，用于注入源器件真实 pin 列表")
    parser.add_argument("--rules", default=None, help="自然语言规则文件路径；默认使用 skill 内置模板")
    args = parser.parse_args()
    result = build_model_resolution_tasks(
        args.context_groups,
        args.normalized,
        args.needs_model,
        args.output_dir,
        args.pins,
        args.rules,
    )
    print(f"[OK] model resolution tasks: {result['task_count']} groups, {result['line_count']} lines -> {args.output_dir}")


if __name__ == "__main__":
    main()
