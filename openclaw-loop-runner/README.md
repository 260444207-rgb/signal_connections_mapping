# OpenClaw Loop Runner

OpenClaw Loop Runner is a local Codex/OpenClaw plugin pattern for long-running OpenClaw-style work.

Install instructions: see `INSTALL_OPENCLAW.md`.

It turns a vague long task into a loop:

```text
state init -> pick task -> fresh worker prompt -> output_contract file -> evaluator -> state update -> continue or stop
```

The important contract is simple: a worker/subagent is not done because it replied in chat. It is done only when it writes the required artifact and the supervisor verifies it.

## Files

```text
openclaw-loop-runner/
├── .codex-plugin/plugin.json
├── openclaw.plugin.yaml
├── templates/
│   ├── prd.json
│   ├── progress.md
│   └── loop_prompt.md
├── runtime/openclaw_loop_runner/
│   ├── loop_controller.py
│   ├── task_store.py
│   ├── agent_runner.py
│   ├── evaluator.py
│   └── progress_writer.py
├── skills/openclaw-loop-runner/SKILL.md
└── scripts/
    ├── openclaw_loop.py
    └── openclaw_loop_guard.py
```

## Runtime CLI

Initialize state:

```bash
powershell -ExecutionPolicy Bypass -File .\scripts\openclaw_loop.ps1 -StateDir .openclaw-loop init
```

Check status:

```bash
powershell -ExecutionPolicy Bypass -File .\scripts\openclaw_loop.ps1 -StateDir .openclaw-loop status
```

Pick next runnable task:

```bash
powershell -ExecutionPolicy Bypass -File .\scripts\openclaw_loop.ps1 -StateDir .openclaw-loop next
```

Run the loop. Without `--agent-command`, it writes dispatch prompts under `.openclaw-loop/iterations/` and evaluates the declared output contracts. With an OpenClaw agent command, placeholders are available:

```bash
powershell -ExecutionPolicy Bypass -File .\scripts\openclaw_loop.ps1 -StateDir .openclaw-loop run `
  --agent-command "openclaw agent run --prompt-file {prompt_file}"
```

Available placeholders:

```text
{prompt_file}
{task_id}
{output_file}
```

Check all task output contracts:

```bash
powershell -ExecutionPolicy Bypass -File .\scripts\openclaw_loop.ps1 -StateDir .openclaw-loop check
```

## Standalone Guard Script

Validate a task plan and merge successful worker outputs:

```bash
python scripts/openclaw_loop_guard.py check \
  --plan <task_plan.json> \
  --merged-output <merged_output.jsonl> \
  --report <loop_gate_report.json> \
  --rerun-plan <failed_task_rerun_plan.md>
```

Expected task shape:

```json
{
  "tasks": [
    {
      "task_id": "TASK_01",
      "task_json": "path/to/TASK_01.json",
      "line_ids": ["L1", "L2"],
      "output_contract": {
        "output_file": "path/to/TASK_01.jsonl",
        "format": "jsonl",
        "expected_line_ids": ["L1", "L2"]
      }
    }
  ]
}
```

If any output file is missing, malformed, incomplete, duplicated, or has extra IDs, the script fails and writes a rerun plan.
