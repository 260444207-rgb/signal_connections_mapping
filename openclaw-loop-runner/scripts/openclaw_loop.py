#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = PLUGIN_ROOT / "runtime"
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

from openclaw_loop_runner.jsonio import ensure_dir, read_json, write_json
from openclaw_loop_runner.loop_controller import LoopConfig, build_controller
from openclaw_loop_runner.task_store import TaskStore


def init_state(state_dir: Path, force: bool = False) -> None:
    ensure_dir(state_dir)
    ensure_dir(state_dir / "outputs")
    ensure_dir(state_dir / "iterations")
    templates = PLUGIN_ROOT / "templates"
    for name in ["prd.json", "progress.md"]:
        target = state_dir / name
        if target.exists() and not force:
            continue
        shutil.copyfile(templates / name, target)
    prd_file = state_dir / "prd.json"
    prd = read_json(prd_file, {"tasks": []})
    changed = False
    for task in prd.get("tasks", []):
        contract = task.get("output_contract")
        if not isinstance(contract, dict):
            continue
        output_file = str(contract.get("output_file", ""))
        if output_file.startswith(".openclaw-loop/") or output_file.startswith(".openclaw-loop\\"):
            task_id = str(task.get("id", "TASK"))
            contract["output_file"] = str(state_dir / "outputs" / f"{task_id}.jsonl")
            changed = True
    if changed:
        write_json(prd_file, prd)
    state_file = state_dir / "state.json"
    if force or not state_file.exists():
        write_json(state_file, {
            "status": "running",
            "iterations": 0,
            "noProgressRounds": 0,
            "currentTask": "",
        })


def print_json(obj: object) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def cmd_status(args: argparse.Namespace) -> None:
    store = TaskStore(Path(args.state_dir) / "prd.json", Path(args.state_dir) / "state.json")
    print_json(store.summary())


def cmd_next(args: argparse.Namespace) -> None:
    store = TaskStore(Path(args.state_dir) / "prd.json", Path(args.state_dir) / "state.json")
    task = store.pick_next_task()
    print_json({"status": "NO_TASK" if not task else "OK", "task": task})


def cmd_run(args: argparse.Namespace) -> None:
    controller = build_controller(
        args.state_dir,
        args.agent_command or "",
        LoopConfig(
            max_iterations=args.max_iterations,
            max_no_progress_rounds=args.max_no_progress_rounds,
        ),
    )
    print_json(controller.run())


def cmd_check(args: argparse.Namespace) -> None:
    store = TaskStore(Path(args.state_dir) / "prd.json", Path(args.state_dir) / "state.json")
    from openclaw_loop_runner.evaluator import OutputContractEvaluator

    evaluator = OutputContractEvaluator()
    reports = []
    for task in store.tasks():
        reports.append({"task_id": task.get("id", ""), **evaluator.evaluate(task)})
    failed = [report for report in reports if report.get("status") != "PASS"]
    print_json({
        "status": "PASS" if not failed else "FAIL",
        "failed_count": len(failed),
        "tasks": reports,
    })
    if failed:
        raise SystemExit(2)


def main() -> None:
    parser = argparse.ArgumentParser(description="OpenClaw Loop Runner runtime CLI")
    parser.add_argument("--state-dir", default=".openclaw-loop")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init")
    init_parser.add_argument("--force", action="store_true")

    subparsers.add_parser("status")
    subparsers.add_parser("next")
    subparsers.add_parser("check")

    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--agent-command", default="", help="Optional command with {prompt_file}, {task_id}, {output_file} placeholders.")
    run_parser.add_argument("--max-iterations", type=int, default=20)
    run_parser.add_argument("--max-no-progress-rounds", type=int, default=3)

    args = parser.parse_args()
    state_dir = Path(args.state_dir)
    if args.command == "init":
        init_state(state_dir, args.force)
        print_json({"status": "OK", "state_dir": str(state_dir)})
    elif args.command == "status":
        cmd_status(args)
    elif args.command == "next":
        cmd_next(args)
    elif args.command == "check":
        cmd_check(args)
    elif args.command == "run":
        cmd_run(args)


if __name__ == "__main__":
    main()
