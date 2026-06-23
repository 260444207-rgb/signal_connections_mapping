#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
from collections import defaultdict
import re
from pathlib import Path
from typing import Any, Dict, List

from build_analysis_context_groups import analysis_strategy_for_group, infer_link_family, infer_mapping_family
from common import ensure_dir, iter_jsonl, load_pin_catalog, pins_for_part, read_json, resolve_catalog_key, write_json

DEFAULT_MAX_LINES_PER_MODEL_TASK = 50
DEFAULT_CANDIDATE_HINT_LIMIT = 3


def load_by_line_id(path: str | Path) -> Dict[str, Dict[str, Any]]:
    return {row["line_id"]: row for row in iter_jsonl(path)}


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


def session_state_snapshot(state_path: str | Path, physical_device_instance_ids: List[str]) -> Dict[str, Any]:
    state = read_json(state_path, {})
    instance_filter = set(physical_device_instance_ids)
    instances = []
    for instance in state.get("physical_device_instances", []) or []:
        instance_id = instance.get("physical_device_instance_id", "")
        if instance_filter and instance_id not in instance_filter:
            continue
        instances.append({
            "physical_device_instance_id": instance_id,
            "source_sheet_name": instance.get("source_sheet_name", ""),
            "source_part_id": instance.get("source_part_id", ""),
            "used_pins": instance.get("used_pins", []),
            "allowed_shared_pin_groups": instance.get("allowed_shared_pin_groups", []),
            "unresolved_conflicts": instance.get("unresolved_conflicts", []),
        })
    return {
        "source": "pin_allocation_state_file_snapshot",
        "authoritative_file": str(state_path),
        "usage": "这是生成 TASK 时从 session pin_allocation_state_file 读取的状态摘要；subagent 仍必须读取 authoritative_file 获取最新状态，并在完成 TASK 后更新该文件。",
        "completed_task_ids": state.get("completed_task_ids", []),
        "physical_device_instances": instances,
        "session_used_pins": state.get("used_pins", []),
        "session_allowed_shared_pin_groups": state.get("allowed_shared_pin_groups", []),
        "session_unresolved_conflicts": state.get("unresolved_conflicts", []),
    }


def build_link_family_summary(groups: List[Dict[str, Any]]) -> Dict[str, Any]:
    families: Dict[str, Dict[str, Any]] = {}
    for group in groups:
        family_ids = group.get("link_family_ids") or [group.get("link_family_id") or "LOCAL_DEVICE_MAPPING"]
        for family_id in family_ids:
            entry = families.setdefault(family_id, {
                "link_family_id": family_id,
                "context_group_count": 0,
                "line_count": 0,
                "analysis_strategies": set(),
                "link_family_sources": set(),
                "source_device_signatures": set(),
                "target_device_signatures": set(),
                "mapping_families": set(),
                "representative_context_group_ids": [],
            })
            entry["context_group_count"] += 1
            entry["line_count"] += len(group.get("line_ids", []))
            entry["analysis_strategies"].add(group.get("analysis_strategy", ""))
            for source in group.get("link_family_sources") or [group.get("link_family_source", "")]:
                entry["link_family_sources"].add(source)
            entry["source_device_signatures"].add(group.get("source_device_signature", ""))
            for target in group.get("target_device_signatures") or [group.get("target_device_signature", "")]:
                entry["target_device_signatures"].add(target)
            for mapping_family in group.get("mapping_families") or [group.get("mapping_family", "")]:
                entry["mapping_families"].add(mapping_family)
            if len(entry["representative_context_group_ids"]) < 5:
                entry["representative_context_group_ids"].append(group.get("context_group_id", ""))
    for entry in families.values():
        for key in ["analysis_strategies", "link_family_sources", "source_device_signatures", "target_device_signatures", "mapping_families"]:
            entry[key] = sorted(x for x in entry[key] if x)
    return families


def semantic_hints_for_link_family(family_id: str) -> List[str]:
    family = normalize_match_text(family_id)
    hints = [
        "同一个 link_family 下的不同 link_instance 可以互相借鉴链路拓扑、方向、实例索引、差分/总线展开规律和器件角色。",
        "借鉴的是链路语义和分析方法，不是直接复制某一行的 selected_pin；每条 line_id 仍必须结合当前源端 pin 列表、端口、对端和网络名独立判断。",
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
            for target in group.get("target_device_signatures") or [group.get("target_device_signature", "")]:
                entry["target_device_signatures"].add(target)
            for mapping_family in group.get("mapping_families") or [group.get("mapping_family", "")]:
                entry["mapping_families"].add(mapping_family)
            for source in group.get("link_family_sources") or [group.get("link_family_source", "")]:
                entry["link_family_sources"].add(source)
            for instance_id in group.get("link_instance_ids", []):
                entry["link_instance_ids"].add(instance_id)
            for sheet in group.get("link_member_sheets", []):
                entry["member_sheets"].add(sheet)
            for info in group.get("user_link_infos", []):
                entry["user_link_infos"].add(info)
            for info in group.get("device_role_infos", []):
                entry["device_role_infos"].add(info)

            for line_id in group_line_ids:
                row = normalized_by_id.get(line_id, {})
                explicit_row_family = row.get("link_family_id", "")
                row_families = link_family_ids_for_row(row, family_id)
                if family_id not in row_families:
                    continue
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
        goal = f"单独分析 {source} 的 hard-case 连接，先复核候选 pin 与规则冲突原因。"
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

    normalized_connection 里仍保留逐行字段；这里额外提供一个显式总览，
    防止 subagent 忽略来自 link_info / 链路信息 sheet 的用户标注。
    """
    line_contexts = []
    for row in normalized_connections:
        line_contexts.append({
            "line_id": row.get("line_id", ""),
            "source_sheet_name": row.get("source_sheet_name", ""),
            "source_block_name": row.get("source_block_name", ""),
            "source_port": row.get("source_port", ""),
            "target_block_name": row.get("target_block_name", ""),
            "target_port": row.get("target_port", ""),
            "connection_id": row.get("connection_id", ""),
            "connection_name": row.get("connection_name", ""),
            "link_family_id": row.get("link_family_id", ""),
            "link_instance_id": row.get("link_instance_id", ""),
            "link_member_sheets": row.get("link_member_sheets", []),
            "user_link_info": row.get("user_link_info", ""),
            "device_role_info": row.get("device_role_info", ""),
            "link_contexts": row.get("link_contexts", []),
        })

    return {
        "source": "input_workbook_link_info_sheet_and_connection_rows",
        "usage": "这些是框图信息表中的链路上下文，只用于帮助判断每条连接的链路归属、上下游角色、实例编号和特殊连接方式；不得用它们修改前 9 列连接事实。",
        "group_link_family_ids": group.get("link_family_ids", []),
        "group_link_family_sources": group.get("link_family_sources", []),
        "group_link_instance_ids": group.get("link_instance_ids", []),
        "group_link_member_sheets": group.get("link_member_sheets", []),
        "group_user_link_infos": group.get("user_link_infos", []),
        "group_device_role_infos": group.get("device_role_infos", []),
        "group_link_contexts": group.get("link_contexts", []),
        "line_link_contexts": line_contexts,
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
            "interpretation": "该 sheet 表示一个物理器件实例；sheet 内不同 source_block_id/source_block_name 是该器件的逻辑块、功能块或端口视图。",
            "logical_blocks": {},
            "line_ids": [],
        })
        block_key = row.get("source_block_id") or row.get("source_block_name") or "UNKNOWN_BLOCK"
        block = instance["logical_blocks"].setdefault(block_key, {
            "source_block_id": row.get("source_block_id", ""),
            "source_block_name": row.get("source_block_name", ""),
            "ports": set(),
            "line_ids": [],
        })
        if row.get("source_port"):
            block["ports"].add(row.get("source_port"))
        block["line_ids"].append(row.get("line_id", ""))
        instance["line_ids"].append(row.get("line_id", ""))

    result_instances = []
    for instance in instances.values():
        logical_blocks = []
        for block in instance["logical_blocks"].values():
            logical_blocks.append({
                "source_block_id": block.get("source_block_id", ""),
                "source_block_name": block.get("source_block_name", ""),
                "ports": sorted(x for x in block.get("ports", set()) if x),
                "line_ids": block.get("line_ids", []),
            })
        instance["logical_blocks"] = logical_blocks
        result_instances.append(instance)

    return {
        "source": "input_workbook_sheet_structure",
        "usage": "subagent 必须把同一 source_sheet_name 视为同一个物理器件实例；同 sheet 内多个 block_id/block_name 只表示该器件的逻辑块/端口视图。",
        "physical_device_instances": result_instances,
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


def classify_signal_shape(row: Dict[str, Any], candidate_mapping: Dict[str, Any] | None = None) -> Dict[str, Any]:
    precomputed = row.get("signal_shape_info")
    if isinstance(precomputed, dict) and precomputed.get("shape"):
        return {
            "shape": precomputed.get("shape", "scalar"),
            "is_bus_or_differential": precomputed.get("shape") in {"bus", "differential"},
            "expected_physical_pin_count": precomputed.get("expected_physical_pin_count", 1),
            "line_id_expansion_policy": precomputed.get("line_id_expansion_policy", ""),
            "expected_output_connection_ids": precomputed.get("expected_output_connection_ids", []),
            "confidence": precomputed.get("confidence", ""),
            "needs_model_shape_review": precomputed.get("needs_model_shape_review", False),
            "reasons": precomputed.get("reasons", []),
            "evidence": precomputed.get("evidence", {}),
            "source": "pre_mapping_signal_shape_inference",
        }

    text = " ".join([
        str(row.get("source_port", "")),
        str(row.get("target_port", "")),
        str(row.get("connection_name", "")),
    ]).upper()
    candidate_text = " ".join([
        str(item.get("pin", ""))
        for item in (candidate_mapping or {}).get("candidates", [])[:10]
    ]).upper()
    reasons = []
    shape = "scalar"
    if int(row.get("expansion_count", 1) or 1) > 1:
        shape = "bus"
        reasons.append("expansion_count > 1")
    if re.search(r"\[[0-9]+:[0-9]+\]|\*[0-9]+|\bD\[[0-9]+", text):
        shape = "bus"
        reasons.append("bus notation in port/net")
    if re.search(r"(_P\b|_N\b|\bDP\b|\bDN\b|\bP\b|\bN\b)", text):
        shape = "differential"
        reasons.append("P/N differential marker")
    if re.search(r"\b(RFIN|RFOUT|DAC|ADC)\d*", text):
        shape = "differential"
        reasons.append("RF/DAC/ADC port commonly maps to P/N physical pins")
    return {
        "shape": shape,
        "is_bus_or_differential": shape in {"bus", "differential"},
        "expected_physical_pin_count": int(row.get("expansion_count", 1) or 1) if shape == "bus" else 2 if shape == "differential" else 1,
        "line_id_expansion_policy": "selected_pins_array_then_render_connection_id_suffix" if shape in {"bus", "differential"} else "single_output_row",
        "expected_output_connection_ids": [],
        "confidence": "legacy_fallback",
        "needs_model_shape_review": False,
        "reasons": reasons,
        "evidence": {},
        "source": "task_stage_fallback",
    }


def slim_candidate_mapping(candidate_mapping: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "line_id": candidate_mapping.get("line_id", ""),
        "source_part_id": candidate_mapping.get("source_part_id", ""),
        "resolved_part_id": candidate_mapping.get("resolved_part_id", ""),
        "role": "rough_lexical_search_hint_only",
        "usage_policy": [
            "这些候选只来自端口名/pin名/索引的轻量相似度，不是答案列表。",
            "selected_pin 可以且经常应该从 source_device_pins 的完整 pin 列表中选择，不限于这里的 candidates。",
            "score 不是置信度；不得因为分数最高就直接选择，必须先完成链路语义、方向、signal_shape 和 pin 占用判断。",
            "如果候选和语义判断冲突，忽略候选并从 source_device_pins 全量列表中选择，或输出 unresolved。",
        ],
        "candidate_hint_limit": DEFAULT_CANDIDATE_HINT_LIMIT,
        "candidates": [
            {
                "pin": item.get("pin", ""),
                "rough_lexical_score": item.get("score", 0),
                "score_is_confidence": False,
                "basis": item.get("basis", []),
            }
            for item in candidate_mapping.get("candidates", [])[:DEFAULT_CANDIDATE_HINT_LIMIT]
        ],
        "available_pins_count": len(candidate_mapping.get("available_pins", [])),
        "available_pins_ref": "source_device_pins[source_part_id]",
    }


def slim_need_row(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "line_id": row.get("line_id", ""),
        "reason": row.get("reason", ""),
    }


def build_pin_allocation_context(
    normalized_connections: List[Dict[str, Any]],
    candidates_by_id: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    """
    给模型显式提供同一物理器件实例内的 pin 分配约束。

    这里不预先选择 pin，只告诉模型哪些连接共享同一物理器件 pin 空间，
    哪些连接可能因为同一网络/连接名而允许共享同一个 pin。
    """
    instances: Dict[str, Dict[str, Any]] = {}
    shared_groups: Dict[str, Dict[str, Any]] = {}
    endpoint_groups: Dict[str, Dict[str, Any]] = {}
    for row in normalized_connections:
        line_id = row.get("line_id", "")
        sheet = row.get("source_sheet_name") or row.get("output_sheet_name") or "UNKNOWN_SHEET"
        part_id = row.get("source_part_id", "")
        instance_key = f"SHEET:{sheet}|PART:{part_id or 'UNKNOWN_PART'}"
        candidate_mapping = candidates_by_id.get(line_id, {})
        rough_pin_search_hints = [
            {
                "pin": item.get("pin", ""),
                "rough_lexical_score": item.get("score", 0),
                "score_is_confidence": False,
                "basis": item.get("basis", []),
            }
            for item in candidate_mapping.get("candidates", [])[:DEFAULT_CANDIDATE_HINT_LIMIT]
        ]
        instances.setdefault(instance_key, {
            "physical_device_instance_id": instance_key,
            "source_sheet_name": sheet,
            "source_part_id": part_id,
            "pin_space": "source_device_pins for this source_part_id",
            "line_pin_domains": [],
        })["line_pin_domains"].append({
            "line_id": line_id,
            "signal_shape": classify_signal_shape(row, candidate_mapping),
            "source_block_id": row.get("source_block_id", ""),
            "source_block_name": row.get("source_block_name", ""),
            "source_port": row.get("source_port", ""),
            "target_block_name": row.get("target_block_name", ""),
            "target_port": row.get("target_port", ""),
            "connection_id": row.get("connection_id", ""),
            "connection_name": row.get("connection_name", ""),
            "available_pins_count": len(candidate_mapping.get("available_pins", [])),
            "rough_pin_search_hints": rough_pin_search_hints,
            "rough_pin_search_hints_policy": "只用于快速定位可能相关的 pin 名，不是候选闭集；最终必须从 source_device_pins 全量列表按语义选择。",
        })

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
                "reason": "同一个源端端口连接到多个目标端口，表示扇出/多目标连接；通常可共享同一个源端 pin 和网络名。",
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
        "pin_reuse_policy": [
            "每个 line_id 必须先判断 signal_shape：scalar / bus / differential。",
            "如果不是 bus/differential，且不是同一源端口扇出到多个目标端口，则同一个源端端口对应的 selected_pin 不应重复分配给其他不同语义连接。",
            "如果同一个源端端口连接到多个目标器件端口，表示 fanout / multi-target connection，通常可以共享同一个 selected_pin 和 net_name。",
            "bus/differential 可以在同一个 decision 中使用 selected_pins 表达多个物理 pin；不要把非 bus/differential 的普通标量连接硬拆成多个 pin。",
            "只有当连接明确属于同一物理信号、同一网络名、同一 base_connection_id、同一源端口扇出、多端口别名，或用户/规则明确说明一个器件引脚暴露为多个端口时，才允许多个 line_id 选择同一个 pin。",
            "如果两个不同语义的 line_id 竞争同一个 pin，不能硬分配；应选择更匹配的一条，另一条输出 unresolved 或说明冲突。",
            "这个约束只在同一个 physical_device_instance_id 内生效；不同 sheet 表示不同物理器件实例，可以使用同名 pin。",
        ],
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
                    + str(Path(session.get("pin_allocation_context_file", "")).name)
                ).replace("|", "/"),
                tasks="<br>".join(task_names).replace("|", "/"),
            )
        )
    lines.extend([
        "",
        "执行要求：同一个 session 由一个 subagent 顺序处理全部 TASK；处理每个 TASK 前读取 session_pin_allocation_context_file 和 pin_allocation_state_file。每处理完一个 TASK，写入 TASK 的 output_file，并更新 pin_allocation_state_file 中已用 pin、允许复用 pin 和 unresolved 冲突说明。后续 TASK 必须读取该 state 再继续分析。",
    ])
    return "\n".join(lines) + "\n"


def build_global_link_plan(
    link_family_summaries: Dict[str, Any],
    link_family_profiles: Dict[str, Dict[str, Any]],
    sessions: List[Dict[str, Any]],
) -> Dict[str, Any]:
    families = []
    for family_id, summary in sorted(link_family_summaries.items()):
        profile = link_family_profiles.get(family_id, {})
        families.append({
            "link_family_id": family_id,
            "purpose": "给各 source_device subagent 共享链路级语义；不得作为 pin 裁决结果。",
            "line_count": summary.get("line_count", 0),
            "context_group_count": summary.get("context_group_count", 0),
            "source_device_signatures": summary.get("source_device_signatures", []),
            "target_device_signatures": summary.get("target_device_signatures", []),
            "mapping_families": summary.get("mapping_families", []),
            "analysis_strategies": summary.get("analysis_strategies", []),
            "link_family_sources": summary.get("link_family_sources", []),
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
                "pin_allocation_context_file": session.get("pin_allocation_context_file", ""),
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


def split_natural_language_rules(text: str) -> Dict[str, str]:
    sections = {
        "full_text": text,
        "link_level_rules": "",
        "device_level_rules": "",
        "general_signal_rules": "",
    }
    markers = [
        ("link_level_rules", "## 1. 链路级规则"),
        ("device_level_rules", "## 2. 器件级规则"),
        ("general_signal_rules", "## 3. 通用信号规则"),
        ("pending_rules", "## 4. 当前待确认规则"),
    ]
    positions = []
    for key, marker in markers:
        idx = text.find(marker)
        if idx >= 0:
            positions.append((idx, key, marker))
    positions.sort()
    for i, (start, key, marker) in enumerate(positions):
        end = positions[i + 1][0] if i + 1 < len(positions) else len(text)
        if key in sections:
            sections[key] = text[start:end].strip()
    return sections


def normalize_match_text(value: Any) -> str:
    return str(value or "").upper()


def extract_rule_blocks(text: str) -> List[Dict[str, Any]]:
    pattern = re.compile(r"^### RULE:\s*(.+?)\s*$", re.MULTILINE)
    matches = list(pattern.finditer(text))
    blocks: List[Dict[str, Any]] = []
    for idx, match in enumerate(matches):
        start = match.start()
        next_rule = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        next_section_match = re.search(r"^##\s+", text[match.end():], re.MULTILINE)
        next_section = match.end() + next_section_match.start() if next_section_match else len(text)
        end = min(next_rule, next_section)
        title = match.group(1).strip()
        rule_id = title.split()[0] if title else f"RULE_{idx + 1}"
        if rule_id.startswith("<"):
            continue
        block_text = text[start:end].strip()
        blocks.append({
            "rule_id": rule_id,
            "title": title,
            "text": block_text,
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


def match_rule_sections(rule_blocks: List[Dict[str, Any]], group: Dict[str, Any], rows: List[Dict[str, Any]], limit: int = 12, min_score: float = 5.0) -> List[Dict[str, Any]]:
    terms = collect_rule_match_terms(group, rows)
    matched = []
    for block in rule_blocks:
        text = normalize_match_text(block.get("text", ""))
        score = 0.0
        matched_terms = []
        for term, weight in terms.items():
            if len(term) < 2:
                continue
            if term in text:
                score += weight
                matched_terms.append(term)
        if score < min_score:
            continue
        matched.append({
            "rule_id": block.get("rule_id", ""),
            "title": block.get("title", ""),
            "score": round(score, 2),
            "matched_terms": matched_terms[:30],
            "text": block.get("text", ""),
        })
    matched.sort(key=lambda item: (-item["score"], item["rule_id"]))
    return matched[:limit]


def render_shared_prompt() -> str:
    schema_fields = (
        "line_id, parent_line_id, selected_pin, selected_pins, "
        "decision_type, confidence, analysis, net_name, net_names, "
        "analyses, confidences, needs_human_review"
    )
    lines = [
        "# Subagent Model Resolution Task Prompt",
        "",
        "你是当前 subagent session 的硬件信号接口映射专家。平衡模式下，一个 source_device subagent 可以顺序处理同一 session 下的多个小 TASK；每个小 TASK 只能分析自己的 task_json 中列出的 line_id。",
        "请按 prompts/semantic_mapping_resolver.md 的语义分析方法处理，优先使用链路族语义理解全局功能，再在链路约束下复用器件类型局部 pin 规则。",
        "本任务的结果必须写入 task_json.output_contract.output_file。只在聊天回复中解释或输出 JSON、但不写入该文件，视为未完成。",
        "最终聊天回复只能报告 status、output_file、decision_count、是否已更新 pin_allocation_state_file；不要把完整 JSON 结果贴在聊天中代替写文件。",
        "",
        "## 必须遵守",
        "",
        "1. 不得新增、删除或修改 normalized_connection。",
        "2. 不得输出 output_sheet_name/source_sheet_name。",
        "3. 每个输入 line_id 必须被一个 mapping_decision 覆盖；如果该 line 根据上下文展开为多条物理线，可用 parent_line_id=输入line_id 且 line_id=输入line_id#数字 的多行 decision 覆盖。",
        "4. 一条逻辑连接对应多个物理 pin 时，优先输出多行 parent_line_id#数字 decision，每行一个 selected_pin；只有 TASK 明确保留未展开数组模式时才使用 selected_pins。",
        "5. 信息不足时输出 selected_pin 为空、decision_type=unresolved、confidence=Low、needs_human_review=true。",
        "6. 输出文件格式必须是 JSONL：每行一个 mapping_decision object，不要 Markdown 包裹，不要 JSON 数组。",
        "6-0. 必须先阅读 task_json.output_schema_contract；它是本 TASK 的输出字段白名单、必填字段和禁止字段契约。",
        f"6a. 每个 mapping_decision object 必须严格遵守 schemas/mapping_decision.schema.json，只允许这些字段：{schema_fields}。",
        "6b. 必填字段必须存在：line_id、selected_pin、decision_type、confidence、analysis、net_name。即使 unresolved 或没有 pin，也必须写空字符串字段，不得省略。",
        "6c. 不得使用中文字段名，不得输出表格列名字段，不得输出 source_sheet_name/output_sheet_name，不得自造字段，不得把结果包在 data/results/decisions 数组里。",
        "6d. decision_type 只能是 model_resolved 或 unresolved；confidence 只能是 High、Medium、Low 或空字符串；needs_human_review 必须是 boolean。",
        "7. 当前 context_group 代表同一个源端器件 pin 体系；可以共享该器件的 pin 功能理解，但每条 line_id 的实例编号、对端端口和网络名必须独立判断。",
        "7a. 必须阅读 task_json.task_scope。task_scope 会给出 subagent_session_id、global_link_plan_file、pin_allocation_state_file、session_state_snapshot、session_pin_allocation_context_file、physical_device_instance_ids、previous_task_outputs 和当前小 TASK 在 session 中的顺序。",
        "7b. 同一个 subagent_session 下的多个 TASK 必须由同一个 subagent 顺序处理；不要因为 TASK 文件变多就为同一个源端器件启动多个互不共享 state 的 subagent。",
        "7c. 处理当前 TASK 前必须先查看 task_scope.session_state_snapshot，再读取 pin_allocation_state_file 获取最新状态；pin 占用必须按 physical_device_instance_id 分开记录。同名 pin 在不同 physical_device_instance_id 下可以各自使用，不算冲突。",
        "7c-1. 处理完成后必须把本 TASK 的已用 pin、允许复用 pin、冲突和 completed_task_ids 写回对应 physical_device_instance_id 的 state，供同一物理器件实例的后续 TASK 使用。",
        "7d. 必须阅读 global_link_plan_file，用它统一理解 link_family、link_instance、器件角色和共享链路语义；global_link_plan 不选择 pin，不能当作裁决结果。",
        "8. 必须先阅读 task_json.diagram_link_context；它来自输入框图表/link_info/链路信息 sheet，用于判断链路归属、上下游角色、实例编号和特殊连接方式。",
        "9. 必须阅读 task_json.matched_rule_sections；它只是脚本召回的候选自然语言规则块，不能替代逐行语义判断。",
        "10. 必须阅读 task_json.link_family_profiles；它是同一 link_family 跨 subagent 共享的链路级语义上下文，用于借鉴拓扑、方向、实例索引和用户说明。",
        "11. 必须阅读 task_json.sheet_device_context；同一个 source_sheet_name 表示同一个物理器件实例，sheet 内不同 block_id/block_name 是该器件的逻辑块/端口视图。",
        "12. 必须阅读 task_json.pin_allocation_context 和 task_scope.session_pin_allocation_context_file；前者是当前小 TASK 局部视图，后者是同一 source_device session 的全量视图，包含跨 TASK 的 potential_shared_pin_groups。先判断每条连接是 scalar、bus 还是 differential；同一物理器件实例内同一个 pin 默认不能被多个不同语义 line_id 重复使用，除非同一源端口扇出、同一网络、多端口别名或用户规则明确允许。",
        "13. 借鉴 link_family_profiles 时，只能复用链路语义和分析方法，不能直接复制其他 line_id 或其他源端器件的 selected_pin。",
        "14. 如果 task_json 中存在 link_family_summaries，先用它们理解组内链路族、控制族、总线族和局部映射，再做单行 pin 选择。",
        "15. 如果没有显式 link_info/link_family 数据，必须按 context_group 的源/目的器件类型、源Block名称、源Port 和 mapping_family 继续分析，不得要求用户必须补充链路表。",
        "15a. 必须先阅读 task_json.pin_selection_policy。source_device_pins 是唯一权威 pin 来源；candidate_mappings 和 rough_pin_search_hints 只是粗糙搜索提示，不是候选闭集，不是答案列表，score 不是置信度。",
        "15b. selected_pin 可以选择任何出现在 source_device_pins 的 pin，即使它没有出现在 candidate_mappings。不得按候选最高分直接选择 pin；必须先完成语义判断再选 pin。",
        "16. 输出前自检：输出必须覆盖 task_json.line_ids；如果根据上下文判断某条原始 line 需要展开为差分/总线，可以不输出原始 line 的决策，改为输出 parent_line_id=原始line_id 且 line_id=原始line_id#数字 的多行决策；除此之外不得遗漏、重复或额外输出。",
        "17. 输出前自检：同一个 physical_device_instance_id 内，除 pin_allocation_context.potential_shared_pin_groups 或用户规则允许外，不得让多个不同语义 line_id 选择同一个 selected_pin。",
        "18. selected_pin/selected_pins 必须逐字来自入参 pin_info.json 中当前源端器件编码对应的 task_json.source_device_pins；不能编造、改写、翻译、补全 pin，也不能使用其他器件的 pin。candidate_mappings 不承载完整 pin 列表，不限制可选 pin 范围。",
        "19. 如果 task_json.source_device_pins 没有当前源端器件编码，或 source_device_pins 中没有可用 pin，必须输出 unresolved，并说明入参 pin_info 缺少该器件 pin 信息。",
        "20. 如果 selected_pin/selected_pins 为空，net_name/net_names 必须为空；没有原理图 pin 时不得生成网络名。",
        "21. LINE_xxx、line、包含 line 的连线名称是画图工具默认连线名，不是有效网络名；不得直接复制到 net_name/net_names，需要网络名时必须结合信号语义生成。",
        "22. 一条逻辑连接对应多个物理 pin 时，优先输出多行 parent_line_id#数字 decision，每行一个 selected_pin；只有兼容旧任务时才使用 selected_pins/net_names 数组。",
        "23. signal_shape / signal_shape_info 是进入映射分析前的前置形态判断结果，来自自动规则、pin 列表 P/N 对识别和本地自然语言规则提示。必须先读取它；只有 needs_model_shape_review=true、证据冲突或明显不符合连接语义时，才在 analysis 中说明并修正判断。",
        "24. 如果 normalized_connection.signal_shape_info.is_expanded_member=true，说明该差分/总线成员已经在映射前展开为独立 line_id（例如 1868#1、1868#2）；该行只输出单个 selected_pin，不得再输出 selected_pins 数组。",
        "25. 如果某条未展开 line 需要结合上下文才知道是差分/总线，则可以在本 TASK 内直接输出展开后的多行 decision：line_id 使用 原line_id#数字，parent_line_id 写原 line_id，每行一个 selected_pin；不要使用 selected_pins 数组。",
        "26. 写文件前自检：每个 task_json.output_contract.expected_line_ids 都必须被同名 line_id 或 parent_line_id 覆盖；写入后必须重新读取 output_file 校验覆盖关系。",
        "27. 写入 output_file 并自检通过后，必须更新 task_json.task_scope.pin_allocation_state_file：按 physical_device_instance_id 追加 completed_task_ids、used_pins、allowed_shared_pin_groups 和 unresolved_conflicts。只有 selected_pin 非空且来自 source_device_pins 时才写入 used_pins。",
        "",
        "## 输出格式",
        "",
        "写入 task_json.output_contract.output_file，每行一个 JSON object：",
        "",
        '{"line_id":"","parent_line_id":"","selected_pin":"","selected_pins":[],"decision_type":"model_resolved|unresolved","confidence":"High|Medium|Low","analysis":"","net_name":"","net_names":[],"needs_human_review":false}',
        "",
        "## 输入文件",
        "",
        "- task_json: 由 subagent_task_plan.md/json 分配的 TASK_xxx.json",
        "",
    ]
    return "\n".join(lines)


def build_model_resolution_tasks(
    context_groups_path: str | Path,
    normalized_path: str | Path,
    candidates_path: str | Path,
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
    candidates_by_id = load_by_line_id(candidates_path)

    # Use the same pin catalog loader as candidate generation and validation so
    # TASK payloads support native JSON, {"pins": ...}, CSV, JSONL, and Excel.
    device_pins: Dict[str, List[str]] = {}
    if pins_path and Path(pins_path).exists():
        device_pins = load_pin_catalog(pins_path)
    skill_root = Path(__file__).resolve().parents[1]
    resolved_rules_path = Path(rules_path) if rules_path else skill_root / "rules" / "natural_language_mapping_rules_template.md"
    rules_text = resolved_rules_path.read_text(encoding="utf-8") if resolved_rules_path.exists() else ""
    rule_blocks = extract_rule_blocks(rules_text)
    needs_rows = list(iter_jsonl(needs_model_path))
    needs_by_id = {row["line_id"]: row for row in needs_rows}
    needed_ids = set(needs_by_id)

    context_data = read_json(context_groups_path, {"context_groups": []})
    context_groups = context_data.get("context_groups", [])
    link_family_summaries = build_link_family_summary(context_groups)
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
        session_pin_context_file = subagent_state_dir / f"{session_id}.pin_allocation_context.json"

        # 收集本组所有 normalized_connections 中的 source_part_id -> 真实 pin 列表。
        # pin_info 缺失时整个源端器件 session 跳过，不生成语义模型任务。
        full_group_nc = [normalized_by_id[lid] for lid in group_line_ids if lid in normalized_by_id]
        source_pins_map: Dict[str, List[str]] = {}
        for nc in full_group_nc:
            code = nc.get("source_part_id", "")
            if code and code not in source_pins_map:
                source_pins_map[code] = pins_for_part(device_pins, code)
                resolved_code = resolve_catalog_key(device_pins, code)
                if resolved_code != code:
                    source_pins_map[resolved_code] = source_pins_map[code]

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
            "pin_allocation_context_file": str(session_pin_context_file),
            "global_link_plan_file": str(output_dir / "global_link_plan.json"),
            "tasks": [],
        })

        session_pin_allocation_context = build_pin_allocation_context(full_group_nc, candidates_by_id)
        session_pin_allocation_context.update({
            "scope": "session_level_full_source_device_context",
            "subagent_session_id": session_id,
            "context_group_id": context_id,
            "usage": "这是同一个 source_device session 的全量 pin 分配上下文，包含跨小 TASK 的 potential_shared_pin_groups；subagent 处理每个 TASK 前都应读取它，再结合当前 TASK 内的 pin_allocation_context。",
        })
        write_json(session_pin_context_file, session_pin_allocation_context)

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
                "must_write_file": True,
                "output_file": str(output_file),
                "format": "jsonl",
                "one_mapping_decision_per_line": True,
                "expected_line_ids": line_ids,
                "line_id_coverage_policy": "每个 expected_line_ids 必须被同名 line_id 覆盖；若上下文判断需要展开，可由 parent_line_id=expected_line_id 且 line_id=expected_line_id#数字 的多行 decision 覆盖。",
                "failure_policy": "如果该文件不存在、不是 JSONL、expected_line_ids 未被 line_id/parent_line_id 覆盖、存在重复 line_id 或存在无合法 parent_line_id 的额外 line_id，主控流程必须判定该 TASK 失败并重新分析；不得进入 finish。",
            }
            task_scope = {
                "execution_mode": "balanced_source_device_session",
                "subagent_session_id": session_id,
                "parent_context_group_id": context_id,
                "subtask_index_in_session": chunk_index,
                "subtask_count_in_session": len(task_chunks),
                "max_lines_per_task": DEFAULT_MAX_LINES_PER_MODEL_TASK,
                "split_policy": "source physical device instance first; link/mapping semantics second; line-count cap last",
                "physical_device_instance_ids": task_physical_device_instance_ids,
                "pin_allocation_state_file": str(session_state_file),
                "session_state_snapshot": session_state_snapshot(session_state_file, task_physical_device_instance_ids),
                "session_pin_allocation_context_file": str(session_pin_context_file),
                "global_link_plan_file": str(output_dir / "global_link_plan.json"),
                "previous_task_outputs": list(previous_task_outputs),
                "next_step": "写入 output_contract.output_file 后，更新 pin_allocation_state_file，再处理同 session 的下一个 TASK。跨 TASK 的潜在共享关系先查 session_pin_allocation_context_file。",
            }
            task_payload = {
                "task_id": file_stem,
                "task_display_name": task_display_name,
                "task_scope": task_scope,
                "context_group": task_group,
                "source_device_pins": source_pins_map,
                "pin_selection_policy": {
                    "authoritative_pin_source": "source_device_pins",
                    "candidate_mappings_role": "rough_search_hints_only",
                    "rules": [
                        "selected_pin / selected_pins 必须逐字来自 source_device_pins 中当前源端器件编码对应的完整 pin 列表。",
                        "candidate_mappings 不是可选答案列表，也不是闭集；没有出现在 candidate_mappings 的 pin 仍然可以被选择。",
                        "candidate_mappings 的 rough_lexical_score 不是置信度，不能按最高分直接选 pin。",
                        "必须先判断链路语义、方向、source/target 角色、signal_shape、差分/总线展开和 pin 占用，再查 source_device_pins 选择同功能 pin。",
                        "如果语义判断与候选提示冲突，忽略候选提示；如果 source_device_pins 中找不到同功能 pin，输出 unresolved。",
                    ],
                },
                "sheet_device_context": build_sheet_device_context(group_nc),
                "pin_allocation_context": build_pin_allocation_context(group_nc, candidates_by_id),
                "diagram_link_context": build_diagram_link_context(task_group, group_nc),
                "link_family_summaries": {
                    family_id: link_family_summaries.get(family_id, {})
                    for family_id in (task_group.get("link_family_ids") or [task_group.get("link_family_id") or "LOCAL_DEVICE_MAPPING"])
                },
                "link_family_profiles": {
                    family_id: link_family_profiles.get(family_id, {})
                    for family_id in (task_group.get("link_family_ids") or [task_group.get("link_family_id") or "LOCAL_DEVICE_MAPPING"])
                },
                "line_ids": line_ids,
                "normalized_connections": group_nc,
                "candidate_mappings": [
                    slim_candidate_mapping(candidates_by_id.get(line_id, {"line_id": line_id, "candidates": []}))
                    for line_id in line_ids
                ],
                "rule_source": {
                    "file": str(resolved_rules_path),
                    "usage": "TASK JSON 只内嵌 matched_rule_sections；完整自然语言规则从该文件读取。",
                },
                "matched_rule_sections": match_rule_sections(rule_blocks, task_group, group_nc),
                "needs_model_resolution": [slim_need_row(needs_by_id[line_id]) for line_id in line_ids],
                "output_contract": output_contract,
                "required_output": {
                    "type": "jsonl_file",
                    "schema": "schemas/mapping_decision.schema.json",
                    "one_decision_per_line_id": True,
                    "write_to_file": str(output_file),
                },
                "output_schema_contract": {
                    "schema_file": "schemas/mapping_decision.schema.json",
                    "format": "JSONL",
                    "one_json_object_per_line": True,
                    "allowed_fields": [
                        "line_id",
                        "parent_line_id",
                        "selected_pin",
                        "selected_pins",
                        "decision_type",
                        "confidence",
                        "analysis",
                        "net_name",
                        "net_names",
                        "analyses",
                        "confidences",
                        "needs_human_review",
                    ],
                    "required_fields": [
                        "line_id",
                        "selected_pin",
                        "decision_type",
                        "confidence",
                        "analysis",
                        "net_name",
                    ],
                    "forbidden_fields": [
                        "source_sheet_name",
                        "output_sheet_name",
                        "源Block标识",
                        "源Block名称",
                        "源Port",
                        "目的Block标识",
                        "目的Block名称",
                        "目的Port",
                        "连线ID",
                        "连线名称",
                        "连线方向",
                        "原理图Pin脚",
                        "分析说明",
                        "映射置信度",
                        "网络命名",
                    ],
                    "strict_rules": [
                        "不得输出 JSON 数组；每一行必须是一个 JSON object。",
                        "不得使用中文字段名或最终 Excel 表头字段。",
                        "不得自造字段；额外说明写入 analysis。",
                        "没有值时填空字符串或空数组，必填字段不得省略。",
                    ],
                },
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
                "pin_allocation_context_file": str(session_pin_context_file),
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

    sessions = list(sessions_by_id.values())
    global_link_plan = build_global_link_plan(link_family_summaries, link_family_profiles, sessions)
    global_link_plan_json = output_dir / "global_link_plan.json"
    global_link_plan_md = output_dir / "global_link_plan.md"
    write_json(global_link_plan_json, global_link_plan)
    global_link_plan_md.write_text(render_global_link_plan(global_link_plan), encoding="utf-8")

    session_plan = {
        "execution_mode": "balanced_source_device_sessions",
        "session_count": len(sessions),
        "task_count": len(tasks),
        "line_count": sum(t["line_count"] for t in tasks),
        "max_lines_per_task": DEFAULT_MAX_LINES_PER_MODEL_TASK,
        "global_link_plan_json": str(global_link_plan_json),
        "global_link_plan_md": str(global_link_plan_md),
        "sessions": sessions,
    }
    session_plan_json = output_dir / "subagent_session_plan.json"
    session_plan_md = output_dir / "subagent_session_plan.md"
    write_json(session_plan_json, session_plan)
    session_plan_md.write_text(render_subagent_session_plan(sessions), encoding="utf-8")

    subagent_plan = {
        "execution_mode": "balanced_source_device_sessions",
        "task_count": len(tasks),
        "line_count": sum(t["line_count"] for t in tasks),
        "session_count": len(sessions),
        "max_lines_per_task": DEFAULT_MAX_LINES_PER_MODEL_TASK,
        "skipped_task_count": len(skipped_tasks),
        "skipped_line_count": sum(t["line_count"] for t in skipped_tasks),
        "tasks_dir": str(tasks_dir),
        "subagent_outputs_dir": str(subagent_outputs_dir),
        "subagent_state_dir": str(subagent_state_dir),
        "global_link_plan_json": str(global_link_plan_json),
        "global_link_plan_md": str(global_link_plan_md),
        "subagent_session_plan_json": str(session_plan_json),
        "subagent_session_plan_md": str(session_plan_md),
        "skipped_tasks": skipped_tasks,
        "sessions": sessions,
        "tasks": tasks,
    }
    plan_json = output_dir / "subagent_task_plan.json"
    plan_md = output_dir / "subagent_task_plan.md"
    write_json(plan_json, subagent_plan)
    plan_md.write_text(render_subagent_task_plan(tasks, skipped_tasks), encoding="utf-8")

    manifest = {
        "execution_mode": "balanced_source_device_sessions",
        "task_count": len(tasks),
        "line_count": sum(t["line_count"] for t in tasks),
        "session_count": len(sessions),
        "max_lines_per_task": DEFAULT_MAX_LINES_PER_MODEL_TASK,
        "skipped_task_count": len(skipped_tasks),
        "skipped_line_count": sum(t["line_count"] for t in skipped_tasks),
        "global_link_plan_json": str(global_link_plan_json),
        "global_link_plan_md": str(global_link_plan_md),
        "subagent_session_plan_json": str(session_plan_json),
        "subagent_session_plan_md": str(session_plan_md),
        "subagent_task_plan_json": str(plan_json),
        "subagent_task_plan_md": str(plan_md),
        "subagent_task_prompt_md": str(shared_prompt_path),
        "tasks_dir": str(tasks_dir),
        "subagent_outputs_dir": str(subagent_outputs_dir),
        "subagent_state_dir": str(subagent_state_dir),
        "tasks": [
            {
                "task_id": task.get("task_id", ""),
                "task_display_name": task.get("task_display_name", ""),
                "context_group_id": task.get("context_group_id", ""),
                "subagent_session_id": task.get("subagent_session_id", ""),
                "readable_device_type": task.get("readable_device_type", ""),
                "source_part_id": task.get("source_part_id", ""),
                "line_count": task.get("line_count", 0),
                "task_json": task.get("task_json", ""),
                "output_file": task.get("output_file", ""),
                "pin_allocation_state_file": task.get("pin_allocation_state_file", ""),
                "pin_allocation_context_file": task.get("pin_allocation_context_file", ""),
                "prompt_file": task.get("prompt_file", ""),
            }
            for task in tasks
        ],
    }
    write_json(output_dir / "manifest.json", manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--context-groups", required=True)
    parser.add_argument("--normalized", required=True)
    parser.add_argument("--candidates", required=True)
    parser.add_argument("--needs-model", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--pins", default=None, help="block_info_pin.json 路径，用于注入源器件真实 pin 列表")
    parser.add_argument("--rules", default=None, help="自然语言规则文件路径；默认使用 skill 内置模板")
    args = parser.parse_args()
    result = build_model_resolution_tasks(
        args.context_groups,
        args.normalized,
        args.candidates,
        args.needs_model,
        args.output_dir,
        args.pins,
        args.rules,
    )
    print(f"[OK] model resolution tasks: {result['task_count']} groups, {result['line_count']} lines -> {args.output_dir}")


if __name__ == "__main__":
    main()
