# Standards

- Keep state in `.openclaw-loop/state.json`.
- Keep human-readable progress in `.openclaw-loop/progress.md`.
- Each task must have `output_contract.output_file`.
- Completion requires evaluator PASS.
- Failed tasks should be retried only up to their max attempts.
