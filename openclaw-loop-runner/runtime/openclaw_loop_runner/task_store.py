from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from .jsonio import read_json, write_json


class TaskStore:
    def __init__(self, prd_file: str | Path, state_file: str | Path):
        self.prd_file = Path(prd_file)
        self.state_file = Path(state_file)

    def load_prd(self) -> Dict[str, Any]:
        return read_json(self.prd_file, {"status": "running", "tasks": []})

    def save_prd(self, data: Dict[str, Any]) -> None:
        write_json(self.prd_file, data)

    def load_state(self) -> Dict[str, Any]:
        return read_json(self.state_file, {
            "status": "running",
            "iterations": 0,
            "noProgressRounds": 0,
            "currentTask": "",
        })

    def save_state(self, state: Dict[str, Any]) -> None:
        write_json(self.state_file, state)

    def tasks(self) -> List[Dict[str, Any]]:
        return self.load_prd().get("tasks", [])

    def pick_next_task(self) -> Optional[Dict[str, Any]]:
        data = self.load_prd()
        tasks = data.get("tasks", [])
        by_id = {task.get("id"): task for task in tasks}
        for task in tasks:
            status = task.get("status", "todo")
            if status not in {"todo", "failed"}:
                continue
            attempts = int(task.get("attempts", 0) or 0)
            max_attempts = int(task.get("maxAttempts", 3) or 3)
            if attempts >= max_attempts:
                continue
            deps = task.get("dependsOn", []) or []
            if all(by_id.get(dep, {}).get("status") == "done" for dep in deps):
                return task
        return None

    def mark_running(self, task_id: str) -> None:
        data = self.load_prd()
        for task in data.get("tasks", []):
            if task.get("id") == task_id:
                task["status"] = "running"
        self.save_prd(data)
        state = self.load_state()
        state["currentTask"] = task_id
        self.save_state(state)

    def mark_done(self, task_id: str, summary: str) -> None:
        data = self.load_prd()
        for task in data.get("tasks", []):
            if task.get("id") == task_id:
                task["status"] = "done"
                task["summary"] = summary
        if all(task.get("status") in {"done", "skipped"} for task in data.get("tasks", [])):
            data["status"] = "done"
        self.save_prd(data)

    def mark_failed_attempt(self, task_id: str, reason: str) -> None:
        data = self.load_prd()
        for task in data.get("tasks", []):
            if task.get("id") == task_id:
                attempts = int(task.get("attempts", 0) or 0) + 1
                task["attempts"] = attempts
                task["lastError"] = reason
                max_attempts = int(task.get("maxAttempts", 3) or 3)
                task["status"] = "blocked" if attempts >= max_attempts else "failed"
        self.save_prd(data)

    def summary(self) -> Dict[str, Any]:
        data = self.load_prd()
        counts: Dict[str, int] = {}
        for task in data.get("tasks", []):
            status = task.get("status", "todo")
            counts[status] = counts.get(status, 0) + 1
        return {
            "project": data.get("project", ""),
            "goal": data.get("goal", ""),
            "status": data.get("status", "running"),
            "counts": counts,
            "state": self.load_state(),
        }
