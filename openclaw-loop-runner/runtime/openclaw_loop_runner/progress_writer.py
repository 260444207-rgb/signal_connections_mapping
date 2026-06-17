from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from .jsonio import ensure_dir


class ProgressWriter:
    def __init__(self, progress_file: str | Path):
        self.progress_file = Path(progress_file)

    def append(self, title: str, content: str) -> None:
        ensure_dir(self.progress_file.parent)
        stamp = datetime.now().isoformat(timespec="seconds")
        with self.progress_file.open("a", encoding="utf-8") as handle:
            handle.write(f"\n## {stamp} - {title}\n\n{content.strip()}\n")

    def recent(self, max_chars: int = 4000) -> str:
        if not self.progress_file.exists():
            return ""
        return self.progress_file.read_text(encoding="utf-8")[-max_chars:]

    def write_iteration(self, iteration: int, task: Dict[str, Any], evaluation: Dict[str, Any]) -> None:
        self.append(
            f"Iteration {iteration}: {task.get('id', '')}",
            "\n".join([
                f"Task: {task.get('id', '')} - {task.get('title', '')}",
                f"Evaluation: {evaluation.get('status', '')}",
                f"Summary: {evaluation.get('summary', '')}",
            ]),
        )
