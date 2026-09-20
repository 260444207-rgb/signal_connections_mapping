---
name: checkpoint-research-example
description: Three-stage research workflow demonstrating durable stage checkpoints.
---

Use the configured workflow `research-report`, whose stages are A -> C -> D.
The user task defines the objective; do not ask the user to provide a checkpoint summary.

## A — Research

Collect and analyze sources. Save important results in files, and ensure tool
results identify their exact paths. Wait for all tools in this stage to finish.
Call `workflow_checkpoint` ALONE:

```json
{"workflow_id":"research-report","stage_id":"A","status":"completed","next_stage":"C","reason":"stage_boundary"}
```

On success, END THIS RUN. The coordinator archives local context, resets the model context, and sends a saved restart prompt. Do not start C or call any additional tools. On failure,
follow `retryable`; do not advance. Do not describe the stage as checkpointed
unless the tool succeeded.

## C — Synthesis

Resume only after the workflow continuation state selects C. Treat A as completed.
Read its artifact paths and prepare the report. Respect any newer user constraints.
Call `workflow_checkpoint` alone and then end the run:

```json
{"workflow_id":"research-report","stage_id":"C","status":"completed","next_stage":"D","reason":"stage_boundary"}
```

## D — Validation

Validate the report and save final artifacts. Declare the final checkpoint, with
no next_stage, then report completion without more tool calls:

```json
{"workflow_id":"research-report","stage_id":"D","status":"completed","reason":"stage_boundary"}
```

Never repeat a completed stage just because its old transcript is visible. If its
output is invalid, stop and ask the operator for a new workflow instance; this MVP
does not implement rollback. A paused/failed checkpoint does not schedule any run.
