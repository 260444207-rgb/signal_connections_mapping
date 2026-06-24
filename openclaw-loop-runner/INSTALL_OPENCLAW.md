# Install OpenClaw Loop Runner into OpenClaw

This plugin is designed as an OpenClaw-compatible local plugin bundle. It has two layers:

```text
1. Skill layer: skills/openclaw-loop-runner/SKILL.md
2. Runtime layer: scripts/openclaw_loop.py + runtime/openclaw_loop_runner/
```

Because OpenClaw installations may use different plugin directories, install by copying this bundle into your OpenClaw root.

## 1. Locate OpenClaw Root

Find the directory that contains your OpenClaw app/repo configuration. In examples below it is:

```text
D:\path\to\openclaw
```

It should typically contain directories such as:

```text
plugins/
skills/
config/
```

If `plugins/` or `skills/` do not exist, the install script can create them.

## 2. Install

From this plugin directory:

```powershell
cd D:\codex\signal_connect\plugins\openclaw-loop-runner
powershell -ExecutionPolicy Bypass -File .\scripts\install_to_openclaw.ps1 -OpenClawRoot D:\path\to\openclaw
```

What it does:

```text
1. Copies this plugin to <OpenClawRoot>\plugins\openclaw-loop-runner
2. Copies the skill to <OpenClawRoot>\skills\openclaw-loop-runner
3. Prints commands for init/status/run/check
```

Use `-Force` to overwrite an existing installed copy:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install_to_openclaw.ps1 -OpenClawRoot D:\path\to\openclaw -Force
```

## 3. Generate Anchor Files from a User Description

Inside the OpenClaw workspace/project where you want loop state, use `plan` instead of hand-writing `prd.json`:

```powershell
powershell -ExecutionPolicy Bypass -File D:\path\to\openclaw\plugins\openclaw-loop-runner\scripts\openclaw_loop.ps1 `
  -StateDir .openclaw-loop plan `
  -Description "你的长任务目标描述"
```

You can also use Codex-style goal mode.

One-step:

```powershell
powershell -ExecutionPolicy Bypass -File D:\path\to\openclaw\plugins\openclaw-loop-runner\scripts\openclaw_loop.ps1 `
  -StateDir .openclaw-loop goal `
  -Message "goal 你的长任务目标描述"
```

Two-step:

```powershell
powershell -ExecutionPolicy Bypass -File D:\path\to\openclaw\plugins\openclaw-loop-runner\scripts\openclaw_loop.ps1 `
  -StateDir .openclaw-loop goal `
  -Message "goal"

powershell -ExecutionPolicy Bypass -File D:\path\to\openclaw\plugins\openclaw-loop-runner\scripts\openclaw_loop.ps1 `
  -StateDir .openclaw-loop goal `
  -Message "你的长任务目标描述"
```

If OpenClaw supports chat middleware, wire each user message to `loop.goal --message "{message}"`. If it returns `NOOP`, continue to the default agent.

This creates:

```text
.openclaw-loop/
  goal.md
  plans.md
  standards.md
  implement.md
  prd.json
  state.json
  progress.md
  outputs/
  iterations/
```

If your description is long, use a file:

```powershell
powershell -ExecutionPolicy Bypass -File D:\path\to\openclaw\plugins\openclaw-loop-runner\scripts\openclaw_loop.ps1 `
  -StateDir .openclaw-loop plan `
  -DescriptionFile .\task-description.md `
  -Force
```

`plan` extracts numbered/bulleted items into tasks. If no list is found, it creates a default four-step loop plan and keeps the original description in `goal.md` and `prd.json`.

## 4. Run

Without an OpenClaw agent command, the runtime dispatches prompt files into `.openclaw-loop/iterations/`:

```powershell
powershell -ExecutionPolicy Bypass -File D:\path\to\openclaw\plugins\openclaw-loop-runner\scripts\openclaw_loop.ps1 -StateDir .openclaw-loop run
```

With an OpenClaw agent command, pass it through `--agent-command`.

Example placeholder form:

```powershell
powershell -ExecutionPolicy Bypass -File D:\path\to\openclaw\plugins\openclaw-loop-runner\scripts\openclaw_loop.ps1 -StateDir .openclaw-loop run `
  --agent-command "openclaw agent run --prompt-file {prompt_file}"
```

Available placeholders:

```text
{prompt_file}
{task_id}
{output_file}
```

Replace the command with the actual OpenClaw agent invocation used by your installation.

## 5. Check Status

```powershell
powershell -ExecutionPolicy Bypass -File D:\path\to\openclaw\plugins\openclaw-loop-runner\scripts\openclaw_loop.ps1 -StateDir .openclaw-loop status
powershell -ExecutionPolicy Bypass -File D:\path\to\openclaw\plugins\openclaw-loop-runner\scripts\openclaw_loop.ps1 -StateDir .openclaw-loop next
powershell -ExecutionPolicy Bypass -File D:\path\to\openclaw\plugins\openclaw-loop-runner\scripts\openclaw_loop.ps1 -StateDir .openclaw-loop check
```

## 6. Completion Rule

OpenClaw Loop Runner treats a task as done only when:

```text
1. The worker writes output_contract.output_file.
2. The evaluator can parse the output.
3. The expected IDs are fully covered.
4. No duplicate or extra IDs are present.
```

Chat output alone is not completion.

## Notes

`openclaw.plugin.yaml` is included as a registration descriptor for OpenClaw-style command registration. If your OpenClaw distribution supports plugin discovery, point it at:

```text
<OpenClawRoot>\plugins\openclaw-loop-runner\openclaw.plugin.yaml
```

If your distribution only supports skills, the copied `skills/openclaw-loop-runner/SKILL.md` is still usable as a prompt-level loop controller, while the Python runtime can be invoked manually.
