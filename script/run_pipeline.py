#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from init_task import init_task
from normalize_connections import normalize_connections
from build_analysis_context_groups import build_analysis_context_groups
from generate_candidates import generate_candidates
from infer_signal_shapes import infer_signal_shapes
from pre_resolve_candidates import pre_resolve_candidates
from build_model_resolution_tasks import build_model_resolution_tasks
from check_subagent_outputs import check_subagent_outputs
from merge_decisions import merge_decisions
from validate_mapping import validate_mapping
from render_outputs import render_outputs
from render_template_sheets import render_template_sheets

REQUIRED_PREPARE_FILES = [
    "normalized_connections.jsonl",
    "candidate_mappings.jsonl",
    "signal_shape_inference.jsonl",
]

def default_rules_path() -> Path:
    return Path(__file__).resolve().parents[1] / "rules" / "natural_language_mapping_rules_template.md"

def collect_rule_paths(project_rules: str = "", user_rules: str = "") -> list[Path]:
    rules_root = Path(__file__).resolve().parents[1] / "rules"

    # 收集顺序：入口模板 → global_mapping → link_family_guide → 子目录按字母序 → project → user
    rule_paths = [rules_root / "natural_language_mapping_rules_template.md"]

    # global_mapping_rules.md
    global_mapping = rules_root / "global_mapping_rules.md"
    if global_mapping.exists():
        rule_paths.append(global_mapping)

    # link_family_guide.md
    link_family = rules_root / "link_family_guide.md"
    if link_family.exists():
        rule_paths.append(link_family)

    # 自动扫描子目录: device_rules/, link_rules/, signal_rules/
    for subdir_name in ["device_rules", "link_rules", "signal_rules"]:
        subdir = rules_root / subdir_name
        if subdir.is_dir():
            for md_file in sorted(subdir.glob("*.md")):
                rule_paths.append(md_file)

    # 项目规则和用户规则
    for value in [project_rules, user_rules]:
        if value:
            rule_paths.append(Path(value))
    return rule_paths

def render_combined_rules(project_rules: str = "", user_rules: str = "") -> str:
    parts = []
    for path in collect_rule_paths(project_rules, user_rules):
        if path.exists():
            parts.append(f"\n\n<!-- SOURCE: {path} -->\n\n" + path.read_text(encoding="utf-8"))
    return "\n".join(parts).strip() + "\n"

def build_combined_rules(task_dir: Path, project_rules: str = "", user_rules: str = "") -> Path:
    intermediate = task_dir / "intermediate"
    intermediate.mkdir(parents=True, exist_ok=True)

    combined = intermediate / "combined_mapping_rules.md"
    combined.write_text(render_combined_rules(project_rules, user_rules), encoding="utf-8")
    return combined

def prepare_outputs_exist(task_dir: Path) -> bool:
    intermediate = task_dir / "intermediate"
    return all((intermediate / name).exists() for name in REQUIRED_PREPARE_FILES)

def combined_rules_are_current(task_dir: Path, project_rules: str = "", user_rules: str = "") -> bool:
    combined = task_dir / "intermediate" / "combined_mapping_rules.md"
    if not combined.exists():
        return False
    return combined.read_text(encoding="utf-8") == render_combined_rules(project_rules, user_rules)

def jsonl_has_rows(path: Path) -> bool:
    if not path.exists():
        return False
    with path.open("r", encoding="utf-8") as handle:
        return any(line.strip() for line in handle)

def timestamped_signal_interface_path(output_dir: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return output_dir / f"signal_interface_{timestamp}.xlsx"

def run_prepare(task_dir: Path, connections: str, pins: str, project_rules: str = "", user_rules: str = "") -> None:
    init_task(task_dir)
    intermediate = task_dir / "intermediate"
    rules_path = build_combined_rules(task_dir, project_rules, user_rules)

    normalize_connections(
        connections,
        intermediate / "normalized_connections.jsonl"
    )
    infer_signal_shapes(
        intermediate / "normalized_connections.jsonl",
        "",
        pins,
        intermediate / "normalized_connections.jsonl",
        intermediate / "signal_shape_inference.jsonl",
        rules_path,
    )
    generate_candidates(
        intermediate / "normalized_connections.jsonl",
        pins,
        intermediate / "candidate_mappings.jsonl"
    )
    build_analysis_context_groups(
        intermediate / "normalized_connections.jsonl",
        intermediate / "analysis_context_groups.json"
    )

def run_apply(
    task_dir: Path,
    connections: str | None = None,
    pins: str | None = None,
    project_rules: str = "",
    user_rules: str = "",
) -> None:
    if not prepare_outputs_exist(task_dir) or not combined_rules_are_current(task_dir, project_rules, user_rules):
        if not connections or not pins:
            raise FileNotFoundError(
                "prepare outputs are missing or rules changed; run stage=prepare first or provide --connections and --pins"
            )
        run_prepare(task_dir, connections, pins, project_rules, user_rules)

    intermediate = task_dir / "intermediate"

    pre_resolve_candidates(
        intermediate / "normalized_connections.jsonl",
        intermediate / "candidate_mappings.jsonl",
        intermediate / "pre_resolved_decisions.jsonl",
        intermediate / "needs_model_resolution.jsonl",
    )

def run_model_tasks(task_dir: Path, connections: str, pins: str, project_rules: str = "", user_rules: str = "") -> None:
    intermediate = task_dir / "intermediate"
    run_apply(task_dir, connections, pins, project_rules, user_rules)
    build_analysis_context_groups(
        intermediate / "normalized_connections.jsonl",
        intermediate / "analysis_context_groups.json",
        intermediate / "needs_model_resolution.jsonl",
    )
    build_model_resolution_tasks(
        intermediate / "analysis_context_groups.json",
        intermediate / "normalized_connections.jsonl",
        intermediate / "candidate_mappings.jsonl",
        intermediate / "needs_model_resolution.jsonl",
        intermediate / "model_resolution_tasks",
        pins,
        intermediate / "combined_mapping_rules.md",
    )

def run_finish(
    task_dir: Path,
    connections: str,
    pins: str,
    template_excel: str | None,
    output_mode: str,
    project_rules: str = "",
    user_rules: str = "",
) -> None:
    intermediate = task_dir / "intermediate"
    output = task_dir / "output"

    run_apply(task_dir, connections, pins, project_rules, user_rules)

    if jsonl_has_rows(intermediate / "needs_model_resolution.jsonl"):
        build_analysis_context_groups(
            intermediate / "normalized_connections.jsonl",
            intermediate / "analysis_context_groups.json",
            intermediate / "needs_model_resolution.jsonl",
        )
        build_model_resolution_tasks(
            intermediate / "analysis_context_groups.json",
            intermediate / "normalized_connections.jsonl",
            intermediate / "candidate_mappings.jsonl",
            intermediate / "needs_model_resolution.jsonl",
            intermediate / "model_resolution_tasks",
            pins,
            intermediate / "combined_mapping_rules.md",
        )
        subagent_report = check_subagent_outputs(
            intermediate / "model_resolution_tasks" / "subagent_task_plan.json",
            intermediate / "model_resolved_decisions.jsonl",
            intermediate / "subagent_output_check.json",
            intermediate / "failed_subagent_rerun_plan.md",
        )
        if subagent_report.get("status") != "PASS":
            raise RuntimeError(
                "Subagent output check failed; restart failed subagents listed in "
                f"{intermediate / 'failed_subagent_rerun_plan.md'} before running finish."
            )

    merge_decisions(
        intermediate / "mapping_decisions.jsonl",
        [
            str(intermediate / "pre_resolved_decisions.jsonl"),
            str(intermediate / "model_resolved_decisions.jsonl"),
            str(intermediate / "manual_override_decisions.jsonl"),
        ],
    )

    validate_mapping(
        intermediate / "normalized_connections.jsonl",
        intermediate / "mapping_decisions.jsonl",
        pins,
        intermediate / "validation_report.json",
    )

    if output_mode == "template_sheets":
        if not template_excel:
            raise ValueError("--template-excel is required when --output-mode template_sheets")
        output_excel = timestamped_signal_interface_path(output)
        render_template_sheets(
            template_excel,
            intermediate / "normalized_connections.jsonl",
            intermediate / "mapping_decisions.jsonl",
            output_excel,
        )
        print(f"[OK] rendered signal interface -> {output_excel}")
    elif output_mode == "flat_debug":
        render_outputs(
            intermediate / "normalized_connections.jsonl",
            intermediate / "mapping_decisions.jsonl",
            output,
        )
    else:
        raise ValueError(f"Unsupported output_mode: {output_mode}")

def main():
    parser = argparse.ArgumentParser(description="Layered signal mapping pipeline")
    parser.add_argument("--task-dir", required=True)
    parser.add_argument("--connections", required=True, help="输入框图连接表。若为 xlsx，则输出分页严格沿用该 xlsx 的 sheet")
    parser.add_argument("--pins", required=True)
    parser.add_argument("--project-rules", default="")
    parser.add_argument("--user-rules", default="")
    parser.add_argument("--template-excel", default="", help="正式输出模板 Excel。通常与 --connections 相同")
    parser.add_argument("--stage", choices=["prepare", "apply", "model_tasks", "finish", "all"], default="all")
    parser.add_argument(
        "--output-mode",
        choices=["template_sheets", "flat_debug"],
        default="template_sheets",
        help="template_sheets=正式模式，严格按输入 Excel sheet 输出；flat_debug=仅调试用平铺 CSV"
    )
    args = parser.parse_args()

    task_dir = Path(args.task_dir)

    if args.stage in {"prepare", "all"}:
        run_prepare(task_dir, args.connections, args.pins, args.project_rules, args.user_rules)

    if args.stage == "apply":
        run_apply(task_dir, args.connections, args.pins, args.project_rules, args.user_rules)

    if args.stage == "model_tasks":
        run_model_tasks(task_dir, args.connections, args.pins, args.project_rules, args.user_rules)

    if args.stage in {"finish", "all"}:
        template_excel = args.template_excel or (args.connections if Path(args.connections).suffix.lower() in {".xlsx", ".xlsm"} else "")
        run_finish(task_dir, args.connections, args.pins, template_excel, args.output_mode, args.project_rules, args.user_rules)

    print(f"[OK] stage={args.stage} task_dir={task_dir}")

if __name__ == "__main__":
    main()
