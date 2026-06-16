#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any, Dict, List

from build_analysis_context_groups import infer_link_family, infer_mapping_family
from common import ensure_dir, iter_jsonl, pins_for_part, read_json, resolve_catalog_key, write_json


def load_by_line_id(path: str | Path) -> Dict[str, Dict[str, Any]]:
    return {row["line_id"]: row for row in iter_jsonl(path)}


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


def render_global_subagent_plan(tasks: List[Dict[str, Any]]) -> str:
    lines = [
        "# Global Subagent Task Plan",
        "",
        "在启动语义 subagent 前，先按全局 context group 汇总任务。每个 subagent 只处理自己的 task_json 中列出的 line_id。",
        "",
        "| # | context_group | subagent | link_family | source | strategy | source -> target | lines | task | 要做什么 |",
        "|---|---|---|---|---|---|---|---:|---|---|",
    ]
    for i, task in enumerate(tasks, start=1):
        source_target = f"{task.get('source_device_signature', '')} -> {', '.join(task.get('target_device_signatures', [])[:3]) or task.get('target_device_signature', '')}"
        family_label = ", ".join(task.get("link_family_ids", [])[:4]) or task.get("link_family_id", "")
        lines.append(
            "| {i} | {context} | {subagent} | {family} | {family_source} | {strategy} | {source_target} | {lines_count} | {task_json} | {goal} |".format(
                i=i,
                context=task.get("context_group_id", ""),
                subagent=task.get("recommended_subagent", ""),
                family=family_label,
                family_source=task.get("link_family_source", ""),
                strategy=task.get("analysis_strategy", ""),
                source_target=source_target,
                lines_count=task.get("line_count", 0),
                task_json=Path(task.get("task_json", "")).name,
                goal=str(task.get("task_goal", "")).replace("|", "/"),
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


def render_prompt(task: Dict[str, Any]) -> str:
    lines = [
        "# Context Group Model Resolution Task",
        "",
        "你是当前 context_group 的硬件信号接口映射专家。只能分析本文件列出的 line_id。",
        "请按 prompts/semantic_mapping_resolver.md 的语义分析方法处理，优先使用链路族语义理解全局功能，再在链路约束下复用器件类型局部 pin 规则。",
        "本任务的结果必须回写给调用方指定的 JSON/JSONL；只在聊天回复中解释而不产出 mapping_decision 文件，视为未完成。",
        "",
        "## 必须遵守",
        "",
        "1. 不得新增、删除或修改 normalized_connection。",
        "2. 不得输出 output_sheet_name/source_sheet_name。",
        "3. 每个输入 line_id 必须输出一个 mapping_decision。",
        "4. 一条逻辑连接对应多个物理 pin 时，在同一个 decision 中输出 selected_pins 数组；不要自行新增 line_id。",
        "5. 信息不足时输出 selected_pin 为空、decision_type=unresolved、confidence=Low、needs_human_review=true。",
        "6. 输出必须是 JSON 数组，不要 Markdown 包裹。",
        "7. 当前 context_group 代表同一个源端器件 pin 体系；可以共享该器件的 pin 功能理解，但每条 line_id 的实例编号、对端端口和网络名必须独立判断。",
        "8. 必须先阅读 task_json.diagram_link_context；它来自输入框图表/link_info/链路信息 sheet，用于判断链路归属、上下游角色、实例编号和特殊连接方式。",
        "9. 必须阅读 task_json.matched_rule_sections；它只是脚本召回的候选自然语言规则块，不能替代逐行语义判断。",
        "10. 必须阅读 task_json.link_family_profiles；它是同一 link_family 跨 subagent 共享的链路级语义上下文，用于借鉴拓扑、方向、实例索引和用户说明。",
        "11. 借鉴 link_family_profiles 时，只能复用链路语义和分析方法，不能直接复制其他 line_id 或其他源端器件的 selected_pin。",
        "12. 如果 task_json 中存在 link_family_summary/link_family_summaries，先用它们理解组内链路族、控制族、总线族和局部映射，再做单行 pin 选择。",
        "13. 如果没有显式 link_info/link_family 数据，必须按 context_group 的源/目的器件类型、源Block名称、源Port 和 mapping_family 继续分析，不得要求用户必须补充链路表。",
        "14. 输出前自检：输出 line_id 集合必须等于 task_json.line_ids；不得遗漏、重复或额外输出。",
        "15. selected_pin/selected_pins 必须来自 task_json.source_device_pins 或 candidate_mappings.available_pins；不能编造 pin。",
        "",
        "## 输出格式",
        "",
        "[",
        "  {",
        '    "line_id": "",',
        '    "selected_pin": "",',
        '    "selected_pins": [],',
        '    "decision_type": "model_resolved|unresolved",',
        '    "confidence": "High|Medium|Low",',
        '    "analysis": "",',
        '    "net_name": "",',
        '    "net_names": [],',
        '    "needs_human_review": false',
        "  }",
        "]",
        "",
        "## 输入文件",
        "",
        f"- task_json: {task['task_json']}",
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
) -> Dict[str, Any]:
    output_dir = ensure_dir(output_dir)
    normalized_by_id = load_by_line_id(normalized_path)
    candidates_by_id = load_by_line_id(candidates_path)

    # 加载 block_info_pin.json，构建 code -> [pin_list] 映射
    device_pins: Dict[str, List[str]] = {}
    if pins_path and Path(pins_path).exists():
        device_pins = read_json(pins_path, {})
    skill_root = Path(__file__).resolve().parents[1]
    rules_path = skill_root / "rules" / "natural_language_mapping_rules_template.md"
    rules_text = rules_path.read_text(encoding="utf-8") if rules_path.exists() else ""
    natural_language_rules = split_natural_language_rules(rules_text)
    rule_blocks = extract_rule_blocks(rules_text)
    needs_rows = list(iter_jsonl(needs_model_path))
    needs_by_id = {row["line_id"]: row for row in needs_rows}
    needed_ids = set(needs_by_id)

    context_data = read_json(context_groups_path, {"context_groups": []})
    context_groups = context_data.get("context_groups", [])
    link_family_summaries = build_link_family_summary(context_groups)
    link_family_profiles = build_link_family_profiles(context_groups, normalized_by_id)
    tasks: List[Dict[str, Any]] = []

    for group in context_groups:
        line_ids = [line_id for line_id in group.get("line_ids", []) if line_id in needed_ids]
        if not line_ids:
            continue
        context_id = group.get("context_group_id") or f"CTX_{len(tasks)+1}"
        # 收集本组所有 normalized_connections 中的 source_part_id -> 真实 pin 列表
        group_nc = [normalized_by_id[lid] for lid in line_ids if lid in normalized_by_id]
        source_pins_map: Dict[str, List[str]] = {}
        for nc in group_nc:
            code = nc.get("source_part_id", "")
            if code and code not in source_pins_map:
                source_pins_map[code] = pins_for_part(device_pins, code)
                resolved_code = resolve_catalog_key(device_pins, code)
                if resolved_code != code:
                    source_pins_map[resolved_code] = source_pins_map[code]

        task_payload = {
            "context_group": group,
            "diagram_link_context": build_diagram_link_context(group, group_nc),
            "link_family_summary": {
                family_id: link_family_summaries.get(family_id, {})
                for family_id in (group.get("link_family_ids") or [group.get("link_family_id") or "LOCAL_DEVICE_MAPPING"])
            },
            "link_family_summaries": {
                family_id: link_family_summaries.get(family_id, {})
                for family_id in (group.get("link_family_ids") or [group.get("link_family_id") or "LOCAL_DEVICE_MAPPING"])
            },
            "link_family_profiles": {
                family_id: link_family_profiles.get(family_id, {})
                for family_id in (group.get("link_family_ids") or [group.get("link_family_id") or "LOCAL_DEVICE_MAPPING"])
            },
            "line_ids": line_ids,
            "normalized_connections": group_nc,
            "candidate_mappings": [candidates_by_id.get(line_id, {"line_id": line_id, "candidates": []}) for line_id in line_ids],
            "source_device_pins": source_pins_map,   # ← 关键修复：从 block_info_pin.json 读取
            "natural_language_rules": natural_language_rules,
            "matched_rule_sections": match_rule_sections(rule_blocks, group, group_nc),
            "needs_model_resolution": [needs_by_id[line_id] for line_id in line_ids],
            "required_output": {
                "type": "json_array",
                "schema": "schemas/mapping_decision.schema.json",
                "one_decision_per_line_id": True,
            },
        }
        task_json = output_dir / f"{context_id}.json"
        write_json(task_json, task_payload)

        task_info = {
            "context_group_id": context_id,
            "line_ids": line_ids,
            "line_count": len(line_ids),
            "task_json": str(task_json),
            "prompt_file": str(output_dir / f"{context_id}.prompt.md"),
            "recommended_subagent": group.get("recommended_subagent", "semantic-mapping-subagent"),
            "device_category": group.get("device_category", ""),
            "link_family_id": group.get("link_family_id", ""),
            "link_family_source": group.get("link_family_source", ""),
            "link_family_ids": group.get("link_family_ids", []),
            "link_family_sources": group.get("link_family_sources", []),
            "analysis_strategy": group.get("analysis_strategy", ""),
            "source_device_signature": group.get("source_device_signature", ""),
            "target_device_signature": group.get("target_device_signature", ""),
            "target_device_signatures": group.get("target_device_signatures", []),
            "link_instance_ids": group.get("link_instance_ids", []),
            "link_member_sheets": group.get("link_member_sheets", []),
            "user_link_infos": group.get("user_link_infos", []),
            "device_role_infos": group.get("device_role_infos", []),
            "mapping_family": group.get("mapping_family", ""),
            "mapping_families": group.get("mapping_families", []),
            "source_sheets": group.get("source_sheets", []),
            "link_family_profile_ids": list((group.get("link_family_ids") or [group.get("link_family_id") or "LOCAL_DEVICE_MAPPING"])),
        }
        task_info["task_goal"] = describe_subagent_task(task_info, group)
        (output_dir / f"{context_id}.prompt.md").write_text(render_prompt(task_info), encoding="utf-8")
        tasks.append(task_info)

    global_plan = {
        "task_count": len(tasks),
        "line_count": sum(t["line_count"] for t in tasks),
        "tasks": tasks,
    }
    write_json(output_dir / "global_subagent_plan.json", global_plan)
    (output_dir / "global_subagent_plan.md").write_text(render_global_subagent_plan(tasks), encoding="utf-8")

    index = {
        "task_count": len(tasks),
        "line_count": sum(t["line_count"] for t in tasks),
        "global_subagent_plan_json": str(output_dir / "global_subagent_plan.json"),
        "global_subagent_plan_md": str(output_dir / "global_subagent_plan.md"),
        "tasks": tasks,
    }
    write_json(output_dir / "index.json", index)
    return index


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--context-groups", required=True)
    parser.add_argument("--normalized", required=True)
    parser.add_argument("--candidates", required=True)
    parser.add_argument("--needs-model", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--pins", default=None, help="block_info_pin.json 路径，用于注入源器件真实 pin 列表")
    args = parser.parse_args()
    result = build_model_resolution_tasks(
        args.context_groups,
        args.normalized,
        args.candidates,
        args.needs_model,
        args.output_dir,
        args.pins,
    )
    print(f"[OK] model resolution tasks: {result['task_count']} groups, {result['line_count']} lines -> {args.output_dir}")


if __name__ == "__main__":
    main()
