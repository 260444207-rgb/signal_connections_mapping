---
name: openclaw-loop-runner
description: Use when a long OpenClaw-style task should be completed through a supervisor loop: split into task bundles, require file-based output contracts, verify coverage, generate rerun plans, and keep iterating until gates pass.
---

# OpenClaw Loop Runner

Use this skill when the user wants a long task to keep moving without losing state, especially when weak workers/subagents may read task files but fail to write required outputs.

## Core Idea

A worker response is not completion. Completion requires a durable artifact that passes a gate.

```text
STATE INIT
  -> pick next task from .openclaw-loop/prd.json
  -> fresh worker prompt
  -> worker writes output_contract.output_file
  -> evaluator checks file existence, parseability, ID coverage, and quality gates
  -> update .openclaw-loop/state.json and progress.md
  -> continue, rerun, or stop by runtime condition
```

## Runtime Files

```text
.openclaw-loop/
  prd.json
  state.json
  progress.md
  outputs/
  iterations/
```

`prd.json` is the task database. `state.json` is machine-readable loop state. `progress.md` is human-readable working memory.

## OpenClaw Task Contract

Every generated task should contain:

```json
{
  "task_id": "TASK_01_DEVICE_SCOPE",
  "line_ids": [],
  "task_inputs": {},
  "output_contract": {
    "must_write_file": true,
    "output_file": "intermediate/subagent_outputs/TASK_01_DEVICE_SCOPE.jsonl",
    "format": "jsonl",
    "expected_line_ids": [],
    "one_record_per_line_id": true,
    "chat_output_is_not_completion": true
  },
  "gate_contract": {
    "block_finish_on_failure": true,
    "rerun_failed_task_only": true,
    "max_attempts": 3
  }
}
```

Adapt `line_ids` to the domain. For signal mapping it is connection line IDs. For code migration it can be file IDs, test IDs, issue IDs, or checklist item IDs.

## Supervisor Loop

1. Initialize `.openclaw-loop`.
2. Keep tasks in `.openclaw-loop/prd.json`.
3. Pick the next dependency-ready task.
4. Run a fresh worker context for that one task.
5. Require the worker to write `output_contract.output_file`.
6. Evaluate the artifact externally.
7. Update `state.json` and `progress.md`.
8. Repeat until all tasks are done or stop conditions trigger.

## Required Worker Prompt

Give workers this hard instruction:

```text
You are assigned exactly one TASK JSON.
Read task_json.output_contract.
Write your result to task_json.output_contract.output_file.
Do not paste the full result in chat instead of writing the file.
After writing, reopen the file and verify expected IDs are complete.
Final chat reply only: status, output_file, record_count, unresolved_count.
```

## Gate Script

Use the runtime CLI:

```bash
powershell -ExecutionPolicy Bypass -File .\scripts\openclaw_loop.ps1 -StateDir .openclaw-loop init
powershell -ExecutionPolicy Bypass -File .\scripts\openclaw_loop.ps1 -StateDir .openclaw-loop status
powershell -ExecutionPolicy Bypass -File .\scripts\openclaw_loop.ps1 -StateDir .openclaw-loop next
powershell -ExecutionPolicy Bypass -File .\scripts\openclaw_loop.ps1 -StateDir .openclaw-loop run
powershell -ExecutionPolicy Bypass -File .\scripts\openclaw_loop.ps1 -StateDir .openclaw-loop check
```

For already generated task plans, use the standalone guard:

```bash
python scripts/openclaw_loop_guard.py check \
  --plan intermediate/task_plan.json \
  --merged-output intermediate/merged_worker_outputs.jsonl \
  --report intermediate/loop_gate_report.json \
  --rerun-plan intermediate/failed_task_rerun_plan.md
```

The script fails if:

```text
1. output_file is missing.
2. output_file is not valid JSONL.
3. expected IDs are missing.
4. duplicate IDs exist.
5. extra IDs exist.
6. any row has a blank ID.
```

## Finish Rule

Never run final `finish`, `render`, `merge`, `commit`, or `deliver` while the gate report is not `PASS`.

If the gate fails, restart the failed workers from the rerun plan. Do not ask the user to manually inspect all outputs unless the same task has failed repeatedly and the failure reason needs domain input.
