#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path
from datetime import datetime

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


def render_template(name: str, **values: str) -> str:
    text = (PLUGIN_ROOT / "templates" / name).read_text(encoding="utf-8")
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", value)
    return text


def task_title_from_line(line: str) -> str:
    text = line.strip()
    while text and text[0] in "-*0123456789.、)） ":
        text = text[1:].strip()
    return text or "Execute described work"


def extract_task_titles(description: str) -> list[str]:
    inline_parts = [
        part.strip()
        for part in re.split(r"(?:^|\s)\d+[\.\)、]\s*", description)
        if part.strip()
    ]
    if len(inline_parts) > 1:
        return inline_parts

    titles: list[str] = []
    for raw_line in description.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        starts_like_item = (
            line.startswith("- ")
            or line.startswith("* ")
            or line[:2].isdigit()
            or (len(line) > 2 and line[0].isdigit() and line[1] in {".", "、", ")", "）"})
        )
        if starts_like_item:
            titles.append(task_title_from_line(line))
    if titles:
        return titles
    return [
        "Clarify user goal and acceptance criteria",
        "Create executable task plan and output contracts",
        "Execute planned work with durable artifacts",
        "Verify outputs and prepare final delivery",
    ]


def build_prd_from_description(state_dir: Path, description: str) -> dict:
    tasks = []
    for index, title in enumerate(extract_task_titles(description), start=1):
        task_id = f"T{index:03d}"
        tasks.append({
            "id": task_id,
            "title": title,
            "description": title,
            "status": "todo",
            "attempts": 0,
            "maxAttempts": 3,
            "dependsOn": [f"T{index - 1:03d}"] if index > 1 else [],
            "output_contract": {
                "must_write_file": True,
                "output_file": str(state_dir / "outputs" / f"{task_id}.jsonl"),
                "format": "jsonl",
                "id_field": "line_id",
                "expected_ids": [task_id],
                "chat_output_is_not_completion": True,
            },
        })
    return {
        "project": "openclaw-loop-project",
        "goal": description.strip(),
        "status": "running",
        "createdAt": datetime.now().isoformat(timespec="seconds"),
        "tasks": tasks,
    }


def write_anchor_files(state_dir: Path, description: str, force: bool = False) -> None:
    ensure_dir(state_dir)
    ensure_dir(state_dir / "outputs")
    ensure_dir(state_dir / "iterations")
    prd = build_prd_from_description(state_dir, description)
    prd_file = state_dir / "prd.json"
    if prd_file.exists() and not force:
        raise FileExistsError(f"{prd_file} already exists. Re-run plan with --force to overwrite.")
    write_json(prd_file, prd)
    write_json(state_dir / "state.json", {
        "status": "running",
        "iterations": 0,
        "noProgressRounds": 0,
        "currentTask": "",
        "goalMode": {
            "active": True,
            "awaitingPrompt": False,
            "startedAt": datetime.now().isoformat(timespec="seconds"),
        },
    })
    task_table_lines = [
        "| id | title | dependsOn | output_file |",
        "|---|---|---|---|",
    ]
    for task in prd["tasks"]:
        contract = task["output_contract"]
        task_table_lines.append(
            f"| {task['id']} | {task['title']} | {', '.join(task.get('dependsOn', []))} | {contract['output_file']} |"
        )
    (state_dir / "goal.md").write_text(render_template("goal.md", description=description.strip()), encoding="utf-8")
    (state_dir / "plans.md").write_text(render_template("plans.md", task_table="\n".join(task_table_lines)), encoding="utf-8")
    (state_dir / "standards.md").write_text(render_template("standards.md"), encoding="utf-8")
    (state_dir / "implement.md").write_text(render_template("implement.md"), encoding="utf-8")
    (state_dir / "progress.md").write_text(
        "# OpenClaw Loop Progress\n\n"
        f"## {datetime.now().isoformat(timespec='seconds')} - Anchor files generated\n\n"
        "Generated from user description.\n",
        encoding="utf-8",
    )


def print_json(obj: object) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def cmd_status(args: argparse.Namespace) -> None:
    store = TaskStore(Path(args.state_dir) / "prd.json", Path(args.state_dir) / "state.json")
    print_json(store.summary())


def cmd_plan(args: argparse.Namespace) -> None:
    description = args.description or ""
    if args.description_file:
        description = Path(args.description_file).read_text(encoding="utf-8")
    if not description.strip():
        raise ValueError("plan requires --description or --description-file")
    write_anchor_files(Path(args.state_dir), description, args.force)
    print_json({
        "status": "OK",
        "state_dir": args.state_dir,
        "anchor_files": [
            "goal.md",
            "plans.md",
            "standards.md",
            "implement.md",
            "progress.md",
            "prd.json",
            "state.json",
        ],
    })


def state_is_awaiting_goal(state_dir: Path) -> bool:
    state = read_json(state_dir / "state.json", {})
    goal_mode = state.get("goalMode") if isinstance(state.get("goalMode"), dict) else {}
    return state.get("status") == "awaiting_goal_prompt" or bool(goal_mode.get("awaitingPrompt"))


def write_awaiting_goal_state(state_dir: Path) -> None:
    ensure_dir(state_dir)
    ensure_dir(state_dir / "outputs")
    ensure_dir(state_dir / "iterations")
    started_at = datetime.now().isoformat(timespec="seconds")
    write_json(state_dir / "state.json", {
        "status": "awaiting_goal_prompt",
        "iterations": 0,
        "noProgressRounds": 0,
        "currentTask": "",
        "goalMode": {
            "active": True,
            "awaitingPrompt": True,
            "startedAt": started_at,
        },
    })
    progress = state_dir / "progress.md"
    if not progress.exists():
        progress.write_text(
            "# OpenClaw Loop Progress\n\n"
            f"## {started_at} - Goal mode entered\n\n"
            "Waiting for the next user message as the goal prompt.\n",
            encoding="utf-8",
        )


def strip_goal_prefix(message: str) -> str:
    text = message.strip()
    match = re.match(r"^goal(?:\s+|[:：]\s*)(.*)$", text, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    return match.group(1).strip()


def cmd_goal(args: argparse.Namespace) -> None:
    state_dir = Path(args.state_dir)
    message = str(args.message or "").strip()
    if not message:
        print_json({"status": "NOOP", "reason": "empty message"})
        return

    inline_goal = strip_goal_prefix(message)
    is_goal_command = message.lower() == "goal" or bool(inline_goal)
    awaiting_goal = state_is_awaiting_goal(state_dir)

    if message.lower() == "goal":
        if (state_dir / "prd.json").exists() and not args.force:
            print_json({
                "status": "NEED_FORCE",
                "reason": "existing prd.json found; use --force to replace the current goal or archive it first",
                "state_dir": str(state_dir),
            })
            return
        write_awaiting_goal_state(state_dir)
        print_json({
            "status": "AWAITING_GOAL_PROMPT",
            "state_dir": str(state_dir),
            "message": "Goal mode entered. Send the next user message as the goal description.",
        })
        return

    description = inline_goal if is_goal_command else (message if awaiting_goal else "")
    if not description:
        print_json({"status": "NOOP", "reason": "message is not a goal command and state is not awaiting a goal prompt"})
        return

    if (state_dir / "prd.json").exists() and not args.force:
        print_json({
            "status": "NEED_FORCE",
            "reason": "existing prd.json found; use --force to replace the current goal or archive it first",
            "state_dir": str(state_dir),
        })
        return

    write_anchor_files(state_dir, description, force=args.force)
    print_json({
        "status": "OK",
        "state_dir": str(state_dir),
        "goal": description,
        "anchor_files": [
            "goal.md",
            "plans.md",
            "standards.md",
            "implement.md",
            "progress.md",
            "prd.json",
            "state.json",
        ],
    })


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

    plan_parser = subparsers.add_parser("plan")
    plan_parser.add_argument("--description", default="")
    plan_parser.add_argument("--description-file", default="")
    plan_parser.add_argument("--force", action="store_true")

    goal_parser = subparsers.add_parser("goal")
    goal_parser.add_argument("--message", required=True)
    goal_parser.add_argument("--force", action="store_true")

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
    elif args.command == "plan":
        cmd_plan(args)
    elif args.command == "goal":
        cmd_goal(args)
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
