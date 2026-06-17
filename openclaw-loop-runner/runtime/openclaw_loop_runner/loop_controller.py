from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

from .agent_runner import AgentRunner
from .evaluator import OutputContractEvaluator
from .progress_writer import ProgressWriter
from .task_store import TaskStore


@dataclass
class LoopConfig:
    max_iterations: int = 20
    max_no_progress_rounds: int = 3


class LoopController:
    def __init__(
        self,
        task_store: TaskStore,
        agent_runner: AgentRunner,
        evaluator: OutputContractEvaluator,
        progress_writer: ProgressWriter,
        config: LoopConfig,
    ):
        self.task_store = task_store
        self.agent_runner = agent_runner
        self.evaluator = evaluator
        self.progress_writer = progress_writer
        self.config = config

    def run(self) -> Dict[str, Any]:
        state = self.task_store.load_state()
        iteration = int(state.get("iterations", 0) or 0)
        no_progress = int(state.get("noProgressRounds", 0) or 0)

        while iteration < self.config.max_iterations:
            task = self.task_store.pick_next_task()
            if not task:
                state["status"] = "complete"
                self.task_store.save_state(state)
                self.progress_writer.append("Loop complete", "No runnable tasks remain.")
                return {"status": "complete", "iterations": iteration}

            iteration += 1
            state["iterations"] = iteration
            self.task_store.save_state(state)
            task_id = str(task.get("id", ""))
            self.task_store.mark_running(task_id)

            agent_result = self.agent_runner.run(task, self.progress_writer.recent(), iteration)
            evaluation = self.evaluator.evaluate(task)

            if evaluation.get("passed"):
                self.task_store.mark_done(task_id, evaluation.get("summary", "done"))
                no_progress = 0
            else:
                self.task_store.mark_failed_attempt(task_id, evaluation.get("summary", "failed"))
                no_progress += 1

            state = self.task_store.load_state()
            state["iterations"] = iteration
            state["noProgressRounds"] = no_progress
            self.task_store.save_state(state)
            self.progress_writer.write_iteration(iteration, task, evaluation)

            if not self.task_store.pick_next_task():
                state = self.task_store.load_state()
                state["status"] = "complete"
                self.task_store.save_state(state)
                self.progress_writer.append("Loop complete", "No runnable tasks remain after the latest evaluation.")
                return {
                    "status": "complete",
                    "iterations": iteration,
                    "last_agent_result": agent_result,
                    "last_evaluation": evaluation,
                }

            if no_progress >= self.config.max_no_progress_rounds:
                state["status"] = "stopped_no_progress"
                self.task_store.save_state(state)
                return {
                    "status": "stopped_no_progress",
                    "iterations": iteration,
                    "last_agent_result": agent_result,
                    "last_evaluation": evaluation,
                }

        state["status"] = "stopped_max_iterations"
        self.task_store.save_state(state)
        return {"status": "stopped_max_iterations", "iterations": iteration}


def build_controller(state_dir: str | Path, agent_command: str = "", config: LoopConfig | None = None) -> LoopController:
    state_dir = Path(state_dir)
    return LoopController(
        task_store=TaskStore(state_dir / "prd.json", state_dir / "state.json"),
        agent_runner=AgentRunner(state_dir / "iterations", agent_command),
        evaluator=OutputContractEvaluator(),
        progress_writer=ProgressWriter(state_dir / "progress.md"),
        config=config or LoopConfig(),
    )
