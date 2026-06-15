#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Dict, List

from common import ensure_dir, iter_jsonl, pins_for_part, read_json, resolve_catalog_key, write_json


def load_by_line_id(path: str | Path) -> Dict[str, Dict[str, Any]]:
    return {row["line_id"]: row for row in iter_jsonl(path)}


def build_link_family_summary(groups: List[Dict[str, Any]]) -> Dict[str, Any]:
    families: Dict[str, Dict[str, Any]] = {}
    for group in groups:
        family_id = group.get("link_family_id") or "LOCAL_DEVICE_MAPPING"
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
        entry["link_family_sources"].add(group.get("link_family_source", ""))
        entry["source_device_signatures"].add(group.get("source_device_signature", ""))
        entry["target_device_signatures"].add(group.get("target_device_signature", ""))
        entry["mapping_families"].add(group.get("mapping_family", ""))
        if len(entry["representative_context_group_ids"]) < 5:
            entry["representative_context_group_ids"].append(group.get("context_group_id", ""))
    for entry in families.values():
        for key in ["analysis_strategies", "link_family_sources", "source_device_signatures", "target_device_signatures", "mapping_families"]:
            entry[key] = sorted(x for x in entry[key] if x)
    return families


def describe_subagent_task(task: Dict[str, Any], group: Dict[str, Any]) -> str:
    strategy = group.get("analysis_strategy", "")
    family = group.get("link_family_id", "")
    family_source = group.get("link_family_source", "")
    source = group.get("source_device_signature", "")
    target = group.get("target_device_signature", "")
    role_infos = "; ".join(group.get("device_role_infos", [])[:3])
    user_infos = "; ".join(group.get("user_link_infos", [])[:3])
    if family_source in {"fallback_device_context", "fallback_mapping_family"}:
        goal = f"没有显式链路级数据，按 {source} 到 {target} 的器件上下文和 {group.get('mapping_family', '')} 映射族启动分析。"
    elif strategy == "link_family_first_then_device_template_reuse":
        goal = f"先理解 {family} 链路族的全局功能和上下游角色，再为 {source} 到 {target} 的连接选择源端 pin。"
    elif strategy == "mapping_family_first":
        goal = f"按 {group.get('mapping_family', '')} 映射族优先分析，再结合源端器件 pin 列表裁决。"
    else:
        goal = f"按源/目的器件上下文分析 {source} 到 {target} 的局部映射。"
    details = []
    if user_infos:
        details.append(f"用户链路说明：{user_infos}")
    if role_infos:
        details.append(f"器件角色说明：{role_infos}")
    return goal + (" " + " ".join(details) if details else "")


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
        source_target = f"{task.get('source_device_signature', '')} -> {task.get('target_device_signature', '')}"
        lines.append(
            "| {i} | {context} | {subagent} | {family} | {family_source} | {strategy} | {source_target} | {lines_count} | {task_json} | {goal} |".format(
                i=i,
                context=task.get("context_group_id", ""),
                subagent=task.get("recommended_subagent", ""),
                family=task.get("link_family_id", ""),
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


def render_prompt(task: Dict[str, Any]) -> str:
    lines = [
        "# Context Group Model Resolution Task",
        "",
        "你是当前 context_group 的硬件信号接口映射专家。只能分析本文件列出的 line_id。",
        "请按 prompts/semantic_mapping_resolver.md 的语义分析方法处理，优先使用链路族语义理解全局功能，再在链路约束下复用器件类型局部 pin 规则。",
        "",
        "## 必须遵守",
        "",
        "1. 不得新增、删除或修改 normalized_connection。",
        "2. 不得输出 output_sheet_name/source_sheet_name。",
        "3. 每个输入 line_id 必须输出一个 mapping_decision。",
        "4. 一条逻辑连接对应多个物理 pin 时，在同一个 decision 中输出 selected_pins 数组；不要自行新增 line_id。",
        "5. 信息不足时输出 selected_pin 为空、decision_type=unresolved、confidence=Low、needs_human_review=true。",
        "6. 输出必须是 JSON 数组，不要 Markdown 包裹。",
        "7. 同组不同器件实例可以共享 pin 功能分析逻辑，但每条 line_id 的实例编号、对端端口和网络名必须独立判断。",
        "8. 如果 task_json 中存在 link_family_summary，先用它判断当前连接属于重复链路族、控制族、总线族还是局部映射，再做单行 pin 选择。",
        "9. 如果没有显式 link_info/link_family 数据，必须按 context_group 的源/目的器件类型、源Block名称、源Port 和 mapping_family 继续分析，不得要求用户必须补充链路表。",
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
    natural_language_rules = split_natural_language_rules(rules_path.read_text(encoding="utf-8") if rules_path.exists() else "")
    needs_rows = list(iter_jsonl(needs_model_path))
    needs_by_id = {row["line_id"]: row for row in needs_rows}
    needed_ids = set(needs_by_id)

    context_data = read_json(context_groups_path, {"context_groups": []})
    context_groups = context_data.get("context_groups", [])
    link_family_summaries = build_link_family_summary(context_groups)
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
            "link_family_summary": link_family_summaries.get(group.get("link_family_id") or "LOCAL_DEVICE_MAPPING", {}),
            "line_ids": line_ids,
            "normalized_connections": group_nc,
            "candidate_mappings": [candidates_by_id.get(line_id, {"line_id": line_id, "candidates": []}) for line_id in line_ids],
            "source_device_pins": source_pins_map,   # ← 关键修复：从 block_info_pin.json 读取
            "natural_language_rules": natural_language_rules,
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
            "analysis_strategy": group.get("analysis_strategy", ""),
            "source_device_signature": group.get("source_device_signature", ""),
            "target_device_signature": group.get("target_device_signature", ""),
            "link_instance_ids": group.get("link_instance_ids", []),
            "link_member_sheets": group.get("link_member_sheets", []),
            "user_link_infos": group.get("user_link_infos", []),
            "device_role_infos": group.get("device_role_infos", []),
            "mapping_family": group.get("mapping_family", ""),
            "source_sheets": group.get("source_sheets", []),
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
