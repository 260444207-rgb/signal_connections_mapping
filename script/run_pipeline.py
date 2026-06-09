#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
from pathlib import Path

from init_task import init_task
from normalize_connections import normalize_connections
from build_analysis_context_groups import build_analysis_context_groups
from generate_candidates import generate_candidates
from pre_resolve_candidates import pre_resolve_candidates
from build_model_resolution_tasks import build_model_resolution_tasks
from merge_decisions import merge_decisions
from validate_mapping import validate_mapping
from render_outputs import render_outputs
from render_template_sheets import render_template_sheets

def run_prepare(task_dir: Path, connections: str, pins: str) -> None:
    init_task(task_dir)
    intermediate = task_dir / "intermediate"

    normalize_connections(
        connections,
        intermediate / "normalized_connections.jsonl"
    )
    build_analysis_context_groups(
        intermediate / "normalized_connections.jsonl",
        intermediate / "analysis_context_groups.json"
    )
    generate_candidates(
        intermediate / "normalized_connections.jsonl",
        pins,
        intermediate / "candidate_mappings.jsonl"
    )

def run_apply(task_dir: Path) -> None:
    intermediate = task_dir / "intermediate"

    pre_resolve_candidates(
        intermediate / "normalized_connections.jsonl",
        intermediate / "candidate_mappings.jsonl",
        intermediate / "template_applied_decisions.jsonl",
        intermediate / "needs_model_resolution.jsonl",
    )

def run_model_tasks(task_dir: Path, pins: str) -> None:
    intermediate = task_dir / "intermediate"
    run_apply(task_dir)
    build_analysis_context_groups(
        intermediate / "normalized_connections.jsonl",
        intermediate / "analysis_context_groups.json",
    )
    build_model_resolution_tasks(
        intermediate / "analysis_context_groups.json",
        intermediate / "normalized_connections.jsonl",
        intermediate / "candidate_mappings.jsonl",
        intermediate / "needs_model_resolution.jsonl",
        intermediate / "model_resolution_tasks",
        pins,
    )

def run_finish(task_dir: Path, pins: str, template_excel: str | None, output_mode: str) -> None:
    intermediate = task_dir / "intermediate"
    output = task_dir / "output"

    run_apply(task_dir)

    merge_decisions(
        intermediate / "mapping_decisions.jsonl",
        [
            str(intermediate / "template_applied_decisions.jsonl"),
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
        render_template_sheets(
            template_excel,
            intermediate / "normalized_connections.jsonl",
            intermediate / "mapping_decisions.jsonl",
            output / "signal_interface.xlsx",
        )
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
        run_prepare(task_dir, args.connections, args.pins)

    if args.stage == "apply":
        run_apply(task_dir)

    if args.stage == "model_tasks":
        run_model_tasks(task_dir, args.pins)

    if args.stage in {"finish", "all"}:
        template_excel = args.template_excel or (args.connections if Path(args.connections).suffix.lower() in {".xlsx", ".xlsm"} else "")
        run_finish(task_dir, args.pins, template_excel, args.output_mode)

    print(f"[OK] stage={args.stage} task_dir={task_dir}")

if __name__ == "__main__":
    main()
