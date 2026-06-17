from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Dict

from .jsonio import ensure_dir


class AgentRunner:
    """
    Adapter boundary for OpenClaw.

    If agent_command is provided, it is executed as a subprocess with these
    placeholders available:
      {prompt_file}, {task_id}, {output_file}

    If no command is provided, the runner only writes a dispatch prompt. This
    mode is useful when OpenClaw or Codex will launch the worker externally.
    """

    def __init__(self, iterations_dir: str | Path, agent_command: str = ""):
        self.iterations_dir = Path(iterations_dir)
        self.agent_command = agent_command

    def build_prompt(self, task: Dict[str, Any], recent_progress: str, iteration: int) -> Path:
        ensure_dir(self.iterations_dir)
        task_id = task.get("id", "TASK")
        prompt_path = self.iterations_dir / f"{iteration:03d}_{task_id}_prompt.md"
        prompt_path.write_text(
            "\n".join([
                "# OpenClaw Loop Worker Prompt",
                "",
                "You are a worker inside an external loop controller.",
                "Only solve the current task. You are not the loop controller.",
                "Read output_contract and write the required artifact.",
                "",
                "## Task",
                "",
                str(task),
                "",
                "## Recent Progress",
                "",
                recent_progress or "(none)",
            ]),
            encoding="utf-8",
        )
        return prompt_path

    def run(self, task: Dict[str, Any], recent_progress: str, iteration: int) -> Dict[str, Any]:
        prompt_file = self.build_prompt(task, recent_progress, iteration)
        contract = task.get("output_contract") if isinstance(task.get("output_contract"), dict) else {}
        output_file = str(contract.get("output_file", ""))
        if not self.agent_command:
            return {
                "status": "DISPATCHED",
                "prompt_file": str(prompt_file),
                "message": "No agent command configured; dispatch this prompt to an OpenClaw worker.",
            }

        command = self.agent_command.format(
            prompt_file=str(prompt_file),
            task_id=str(task.get("id", "")),
            output_file=output_file,
        )
        result = subprocess.run(command, shell=True, capture_output=True, text=True)
        return {
            "status": "RAN",
            "prompt_file": str(prompt_file),
            "exit_code": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
