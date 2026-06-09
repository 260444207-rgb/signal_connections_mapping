#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Dict, List

from common import ensure_dir, iter_jsonl, read_json, write_json


def load_by_line_id(path: str | Path) -> Dict[str, Dict[str, Any]]:
    return {row["line_id"]: row for row in iter_jsonl(path)}


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
        "请按 prompts/semantic_mapping_resolver.md 的语义分析方法处理，结合自然语言规则、源端 pin 列表、目的端描述和局部拓扑判断信号作用。",
        "",
        "## 必须遵守",
        "",
        "1. 不得新增、删除或修改 normalized_connection。",
        "2. 不得输出 output_sheet_name/source_sheet_name。",
        "3. 每个输入 line_id 必须输出一个 mapping_decision。",
        "4. 信息不足时输出 selected_pin 为空、decision_type=unresolved、confidence=Low、needs_human_review=true。",
        "5. 输出必须是 JSON 数组，不要 Markdown 包裹。",
        "",
        "## 输出格式",
        "",
        "[",
        "  {",
        '    "line_id": "",',
        '    "selected_pin": "",',
        '    "decision_type": "model_resolved|unresolved",',
        '    "confidence": "High|Medium|Low",',
        '    "analysis": "",',
        '    "net_name": "",',
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
) -> Dict[str, Any]:
    output_dir = ensure_dir(output_dir)
    normalized_by_id = load_by_line_id(normalized_path)
    candidates_by_id = load_by_line_id(candidates_path)
    skill_root = Path(__file__).resolve().parents[1]
    rules_path = skill_root / "rules" / "natural_language_mapping_rules_template.md"
    natural_language_rules = split_natural_language_rules(rules_path.read_text(encoding="utf-8") if rules_path.exists() else "")
    needs_rows = list(iter_jsonl(needs_model_path))
    needs_by_id = {row["line_id"]: row for row in needs_rows}
    needed_ids = set(needs_by_id)

    context_data = read_json(context_groups_path, {"context_groups": []})
    tasks: List[Dict[str, Any]] = []

    for group in context_data.get("context_groups", []):
        line_ids = [line_id for line_id in group.get("line_ids", []) if line_id in needed_ids]
        if not line_ids:
            continue
        context_id = group.get("context_group_id") or f"CTX_{len(tasks)+1}"
        task_payload = {
            "context_group": group,
            "line_ids": line_ids,
            "normalized_connections": [normalized_by_id[line_id] for line_id in line_ids if line_id in normalized_by_id],
            "candidate_mappings": [candidates_by_id.get(line_id, {"line_id": line_id, "candidates": []}) for line_id in line_ids],
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
            "recommended_subagent": group.get("recommended_subagent", "candidate-resolver-subagent"),
            "device_category": group.get("device_category", ""),
            "mapping_family": group.get("mapping_family", ""),
            "source_sheets": group.get("source_sheets", []),
        }
        (output_dir / f"{context_id}.prompt.md").write_text(render_prompt(task_info), encoding="utf-8")
        tasks.append(task_info)

    index = {
        "task_count": len(tasks),
        "line_count": sum(t["line_count"] for t in tasks),
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
    args = parser.parse_args()
    result = build_model_resolution_tasks(
        args.context_groups,
        args.normalized,
        args.candidates,
        args.needs_model,
        args.output_dir,
    )
    print(f"[OK] model resolution tasks: {result['task_count']} groups, {result['line_count']} lines -> {args.output_dir}")


if __name__ == "__main__":
    main()
