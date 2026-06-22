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

## 3. Initialize Loop State in an OpenClaw Project

Inside the OpenClaw workspace/project where you want loop state:

```powershell
powershell -ExecutionPolicy Bypass -File D:\path\to\openclaw\plugins\openclaw-loop-runner\scripts\openclaw_loop.ps1 -StateDir .openclaw-loop init
```

This creates:

```text
.openclaw-loop/
  prd.json
  state.json
  progress.md
  outputs/
  iterations/
```

Edit `.openclaw-loop/prd.json` and replace the template task with your real tasks.

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
