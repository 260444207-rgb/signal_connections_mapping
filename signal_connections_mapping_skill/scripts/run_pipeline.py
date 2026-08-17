#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
from datetime import datetime
import os
from pathlib import Path
import sys

from init_task import init_task
from normalize_connections import normalize_connections
from build_analysis_context_groups import build_analysis_context_groups
from infer_signal_shapes import infer_signal_shapes
from route_model_resolution import route_model_resolution
from build_model_resolution_tasks import build_model_resolution_tasks
from check_subagent_outputs import check_subagent_outputs
from merge_decisions import merge_decisions
from validate_mapping import validate_mapping
from render_outputs import render_outputs
from render_template_sheets import render_template_sheets
from common import read_json, write_json

REQUIRED_PREPARE_FILES = [
    "normalized_connections.jsonl",
    "signal_shape_inference.jsonl",
]

EXTERNAL_DEVICE_RULES_FILENAME = "external_device_rules.md"

SIGNAL_INTERFACE_TASK_SUBDIR = "signal_interface"
PIPELINE_CONFIG_FILENAME = "pipeline_run_config.json"
FINISH_COMMAND_FILENAME = "finish_command.txt"

def _norm_rule_path(path: Path) -> str:
    return str(path.expanduser())

def default_rules_path() -> Path:
    return Path(__file__).resolve().parents[1] / "rules" / "natural_language_mapping_rules_template.md"

def resolve_signal_interface_task_dir(task_dir: Path) -> Path:
    """把本 skill 的全部运行产物收拢到 task_dir/signal_interface 下。"""
    task_dir = Path(task_dir)
    if task_dir.name == SIGNAL_INTERFACE_TASK_SUBDIR:
        return task_dir
    return task_dir / SIGNAL_INTERFACE_TASK_SUBDIR

def split_rule_paths(rule_paths: str = "") -> list[Path]:
    paths: list[Path] = []
    for value in str(rule_paths or "").split(os.pathsep):
        value = value.strip()
        if value:
            paths.append(Path(value))
    return paths

def append_rule_path(rule_paths: str, rule_path: str | Path | None) -> str:
    if not rule_path:
        return rule_paths or ""
    existing = [_norm_rule_path(path) for path in split_rule_paths(rule_paths)]
    candidate = _norm_rule_path(Path(rule_path))
    if candidate in existing:
        return rule_paths or ""
    return os.pathsep.join(existing + [candidate])

def absolute_rule_paths(rule_paths: str = "") -> str:
    return os.pathsep.join(_absolute_path(path) for path in split_rule_paths(rule_paths))

def discover_external_device_rules(task_dir: Path, connections: str = "") -> Path | None:
    """
    自动发现上游编排生成的外部器件规则文件。

    这样编排流程只需要在约定位置写入 external_device_rules.md；
    本 pipeline 会把它当作 project rules 合入 combined_mapping_rules.md。
    """
    candidates = [
        task_dir / "design" / EXTERNAL_DEVICE_RULES_FILENAME,
        task_dir / EXTERNAL_DEVICE_RULES_FILENAME,
        task_dir / "input" / EXTERNAL_DEVICE_RULES_FILENAME,
        task_dir / "rules" / EXTERNAL_DEVICE_RULES_FILENAME,
    ]
    if connections:
        connection_path = Path(connections)
        if connection_path.parent:
            candidates.append(connection_path.parent / EXTERNAL_DEVICE_RULES_FILENAME)
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate
    return None

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
    for value in split_rule_paths(project_rules) + split_rule_paths(user_rules):
        rule_paths.append(value)
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

def _absolute_path(value: str | Path | None) -> str:
    if not value:
        return ""
    return str(Path(value).expanduser().resolve())

def default_template_excel(connections: str = "") -> str:
    if connections and Path(connections).suffix.lower() in {".xlsx", ".xlsm"}:
        return connections
    return ""

def save_pipeline_run_config(
    task_dir: Path,
    connections: str,
    pins: str,
    template_excel: str = "",
    output_mode: str = "template_sheets",
    project_rules: str = "",
    user_rules: str = "",
) -> Path:
    """Persist the canonical inputs so finish never has to rediscover intermediate paths."""
    intermediate = task_dir / "intermediate"
    resolved_connections = _absolute_path(connections)
    resolved_template = _absolute_path(template_excel or default_template_excel(resolved_connections))
    config_path = intermediate / PIPELINE_CONFIG_FILENAME
    finish_command_path = intermediate / FINISH_COMMAND_FILENAME
    config = {
        "contract": "Formal output must be produced only by run_pipeline.py --stage finish.",
        "task_dir": _absolute_path(task_dir),
        "connections": resolved_connections,
        "pins": _absolute_path(pins),
        "template_excel": resolved_template,
        "output_mode": output_mode,
        "project_rules": absolute_rule_paths(project_rules),
        "user_rules": absolute_rule_paths(user_rules),
        "finish_command_file": str(finish_command_path.resolve()),
    }
    write_json(config_path, config)
    script_path = Path(__file__).resolve()
    python_path = Path(sys.executable).resolve()
    command_prefix = f'& "{python_path}"' if os.name == "nt" else f'"{python_path}"'
    finish_command_path.write_text(
        f'{command_prefix} "{script_path}" --task-dir "{Path(task_dir).resolve()}" --stage finish\n',
        encoding="utf-8",
    )
    return config_path

def load_pipeline_run_config(task_dir: Path) -> dict:
    return read_json(task_dir / "intermediate" / PIPELINE_CONFIG_FILENAME, {}) or {}

def run_prepare(
    task_dir: Path,
    connections: str,
    pins: str,
    project_rules: str = "",
    user_rules: str = "",
    template_excel: str = "",
    output_mode: str = "template_sheets",
) -> None:
    init_task(task_dir)
    intermediate = task_dir / "intermediate"
    save_pipeline_run_config(
        task_dir, connections, pins, template_excel, output_mode, project_rules, user_rules
    )
    rules_path = build_combined_rules(task_dir, project_rules, user_rules)

    normalize_connections(
        connections,
        intermediate / "normalized_connections.jsonl"
    )
    infer_signal_shapes(
        intermediate / "normalized_connections.jsonl",
        pins,
        intermediate / "normalized_connections.jsonl",
        intermediate / "signal_shape_inference.jsonl",
        rules_path,
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

    route_model_resolution(
        intermediate / "normalized_connections.jsonl",
        pins,
        intermediate / "pre_resolved_decisions.jsonl",
        intermediate / "needs_model_resolution.jsonl",
    )

def run_model_tasks(
    task_dir: Path,
    connections: str,
    pins: str,
    project_rules: str = "",
    user_rules: str = "",
    template_excel: str = "",
    output_mode: str = "template_sheets",
) -> None:
    intermediate = task_dir / "intermediate"
    run_apply(task_dir, connections, pins, project_rules, user_rules)
    save_pipeline_run_config(
        task_dir, connections, pins, template_excel, output_mode, project_rules, user_rules
    )
    build_analysis_context_groups(
        intermediate / "normalized_connections.jsonl",
        intermediate / "analysis_context_groups.json",
        intermediate / "needs_model_resolution.jsonl",
    )
    build_model_resolution_tasks(
        intermediate / "analysis_context_groups.json",
        intermediate / "normalized_connections.jsonl",
        intermediate / "needs_model_resolution.jsonl",
        intermediate / "model_resolution_tasks",
        pins,
        intermediate / "combined_mapping_rules.md",
    )
    print(
        "[NEXT] Execute every session in model_resolution_tasks/subagent_session_plan.json "
        "and write all TASK output files. Then execute the exact command in "
        f"{intermediate / FINISH_COMMAND_FILENAME}; do not manually merge, validate, or render."
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
        task_plan = intermediate / "model_resolution_tasks" / "subagent_task_plan.json"
        if not task_plan.exists():
            raise RuntimeError(
                "Pipeline order error: model task plan is missing. Run stage=model_tasks, "
                "execute every subagent session, and only then run stage=finish."
            )
        build_analysis_context_groups(
            intermediate / "normalized_connections.jsonl",
            intermediate / "analysis_context_groups.json",
            intermediate / "needs_model_resolution.jsonl",
        )
        build_model_resolution_tasks(
            intermediate / "analysis_context_groups.json",
            intermediate / "normalized_connections.jsonl",
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
                "Finish blocked: "
                f"{subagent_report.get('failed_task_count', 0)}/"
                f"{subagent_report.get('task_count', 0)} subagent outputs failed. "
                "Session status must also show every sessions_spawn run as completed. "
                "Restart or wait only the failed/incomplete tasks listed in "
                f"{intermediate / 'failed_subagent_rerun_plan.md'}, then run finish again."
            )

    merge_decisions(
        intermediate / "mapping_decisions.jsonl",
        [
            str(intermediate / "pre_resolved_decisions.jsonl"),
            str(intermediate / "model_resolved_decisions.jsonl"),
            str(intermediate / "manual_override_decisions.jsonl"),
        ],
    )

    validation_report = validate_mapping(
        intermediate / "normalized_connections.jsonl",
        intermediate / "mapping_decisions.jsonl",
        pins,
        intermediate / "validation_report.json",
    )
    if validation_report.get("status") != "PASS":
        raise RuntimeError(
            "Finish blocked: validation_report.json is not PASS. Fix or rerun the failed "
            "semantic TASKs; do not render or write a replacement rendering script."
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
    parser.add_argument("--connections", default="", help="输入框图连接表。finish 可从 pipeline_run_config.json 自动恢复")
    parser.add_argument("--pins", default="", help="pin_info。finish 可从 pipeline_run_config.json 自动恢复")
    parser.add_argument("--project-rules", default="")
    parser.add_argument("--user-rules", default="")
    parser.add_argument("--template-excel", default="", help="正式输出模板 Excel。通常与 --connections 相同")
    parser.add_argument("--stage", choices=["prepare", "apply", "model_tasks", "finish", "all"], default="all")
    parser.add_argument(
        "--output-mode",
        choices=["template_sheets", "flat_debug"],
        default=None,
        help="template_sheets=正式模式，严格按输入 Excel sheet 输出；flat_debug=仅调试用平铺 CSV"
    )
    args = parser.parse_args()

    task_root = Path(args.task_dir)
    task_dir = resolve_signal_interface_task_dir(task_root)

    saved_config = load_pipeline_run_config(task_dir) if args.stage == "finish" else {}
    connections = args.connections or str(saved_config.get("connections", ""))
    pins = args.pins or str(saved_config.get("pins", ""))
    template_excel = args.template_excel or str(saved_config.get("template_excel", ""))
    output_mode = args.output_mode or str(saved_config.get("output_mode", "template_sheets"))
    if not connections or not pins:
        raise ValueError(
            "--connections and --pins are required for prepare/model_tasks, or must exist in "
            "intermediate/pipeline_run_config.json for finish"
        )

    project_rules = args.project_rules or str(saved_config.get("project_rules", ""))
    user_rules = args.user_rules or str(saved_config.get("user_rules", ""))
    external_device_rules = discover_external_device_rules(task_root, connections)
    if external_device_rules:
        project_rules = append_rule_path(project_rules, external_device_rules)
        print(f"[INFO] external device rules detected -> {external_device_rules}")
    project_rules = absolute_rule_paths(project_rules)
    user_rules = absolute_rule_paths(user_rules)

    if args.stage in {"prepare", "all"}:
        run_prepare(task_dir, connections, pins, project_rules, user_rules, template_excel, output_mode)

    if args.stage == "apply":
        run_apply(task_dir, connections, pins, project_rules, user_rules)

    if args.stage == "model_tasks":
        run_model_tasks(task_dir, connections, pins, project_rules, user_rules, template_excel, output_mode)

    if args.stage in {"finish", "all"}:
        template_excel = template_excel or default_template_excel(connections)
        run_finish(task_dir, connections, pins, template_excel, output_mode, project_rules, user_rules)

    print(f"[OK] stage={args.stage} task_dir={task_dir} task_root={task_root}")

if __name__ == "__main__":
    main()
