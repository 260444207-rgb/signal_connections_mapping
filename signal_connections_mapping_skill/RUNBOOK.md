# diagram logical connection mapping Runbook

## 1. 目标

正式信号接口列表必须执行：

```text
model_tasks -> semantic TASK outputs -> finish
```

`stage=all` 不会调用语义 subagent，只适合脚本冒烟验证。

## 2. 输入检查

确认存在：

```text
connections.xlsx
pin_info.json
```

可选规则按以下方式提供：

```text
<task_root>/design/external_device_rules.md
<task_root>/input/external_device_rules.md
<task_root>/rules/external_device_rules.md
<connections 所在目录>/external_device_rules.md
--project-rules
--user-rules
```

脚本把默认规则和外部规则合并为：

```text
<task_root>/signal_interface/intermediate/combined_mapping_rules.md
```

## 3. 生成任务

```powershell
Set-Location -LiteralPath '<signal_connections_mapping_skill>'
python .\scripts\run_pipeline.py --task-dir '<task_root>' --connections '<connections.xlsx>' --pins '<pin_info.json>' --stage model_tasks
```

实际工作目录会规范为：

```text
<task_root>/signal_interface/
```

缺少源端 pin 的连接直接保留 unresolved，不会生成语义 TASK。

## 4. 读取执行计划

主控只需读取：

```text
intermediate/model_resolution_tasks/subagent_session_plan.json
intermediate/model_resolution_tasks/subagent_session_status.json
intermediate/model_resolution_tasks/subagent_task_prompt.md
```

不要同时把 `.md`、task plan、session plan、manifest 和 global plan 全部读入模型。它们有些仅供人工检查或 finish 校验。

`subagent_session_plan.json` 为每个 session 给出：

```text
prompt_file
session_context_file
pin_allocation_state_file
按顺序排列的 TASK 文件
```

## 5. 执行 session

每个 session 必须使用 `sessions_spawn` 命令启动一个隔离模型 subagent；一次最多并行 2 个不同 session。启动或等待 subagent 时，超时时间必须设置为 30 分钟（1800000 ms）。超时表示该 session 未完成，不能进入 finish。

不得用主控脚本、Python、PowerShell、JavaScript 或其他程序读取 TASK 后自动分析 pin、匹配 pin、生成 mapping_decision，或跳过 `sessions_spawn`。subagent 的语义裁决必须由模型完成；工具只允许用于读取输入、写入 JSONL/state，以及做格式、覆盖关系和 pin 合法性校验。

主控必须维护 `subagent_session_status.json`：启动 session 后标记 `spawned=true`；全部 TASK 完成且等待结果确认后标记 `completed=true`、`failed=false`、`timed_out=false`、`rerun_required=false`，并让 `completed_task_ids` 覆盖该 session 全部 TASK。失败、超时或需要重跑时不得进入 finish；必须按 `failed_subagent_rerun_plan.md` 用 `sessions_spawn` 重跑/等待完成后再更新状态。

同一 session 内：

1. 读取一次 `prompt_file` 和 `session_context_file`。
2. 按计划顺序处理 TASK，不并行。
3. 每个 TASK 开始前读取 `pin_allocation_state_file` 最新状态。
4. 只分析 `output_contract.expected_line_ids`。
5. 结果写入 `output_contract.output_file`，每行一个 JSON object。
6. 重新读取输出文件校验覆盖关系。
7. 按 `physical_device_instance_id` 更新 state，再继续下一 TASK。

相同料号的多个实例可以共享器件功能理解；pin 占用和冲突仍按物理实例隔离。后续 TASK 通过同一 subagent、`previous_task_outputs` 和 state 参考前序结果。

## 6. TASK 与 session context

TASK 的逐行事实只在：

```text
normalized_connections
```

省略字段按：

```text
connection_defaults
```

还原。

session 共用信息位于：

```text
session_context_file
  sheet_device_context
  pin_allocation_context
  link_family_profiles
  rule_library
```

TASK 的 `matched_rule_refs` 指向 `rule_library`；不要按引用顺序或 matched terms 选择 pin。

## 7. pin 选择

- `pin_info` 是唯一 pin 来源。
- `inline_full`：直接使用 TASK 中的完整 `source_device_pins`。
- `grouped_large_catalog`：当前语义组无排序且不是闭集；找不到合理 pin 时读取 `group_file` 的其他组或 `all_pins`。
- 完整列表仍找不到时输出 unresolved。
- 不得改写、补全、翻译 pin 名。
- 同一实例普通 scalar pin 默认不得重复分配；只在 session 共享组、扇出、同网、别名或明确规则允许时复用。

## 8. 输出格式

严格遵守 TASK 的 `schema_file`，JSONL 每行一个 mapping decision。必填：

```text
line_id
selected_pin
decision_type
confidence
analysis
net_name
```

模型不负责网络命名：

```json
{"net_name":"","net_names":[]}
```

最终渲染脚本生成网络名和命名依据。

未解决项：

```json
{"selected_pin":"","decision_type":"unresolved","confidence":"Low","needs_human_review":true,"net_name":""}
```

## 9. 完成

全部 TASK 完成后：

```powershell
Set-Location -LiteralPath '<signal_connections_mapping_skill>'
python .\scripts\run_pipeline.py --task-dir '<task_root>/signal_interface' --stage finish
```

不要手工填写上述示例。直接执行 `intermediate/finish_command.txt` 的完整命令；它引用 `pipeline_run_config.json` 中已确定的 connections、pin_info 和模板。不得手工 merge/validate/render，不得调用 `render_outputs.py` 生成正式结果，也不得编写替代渲染脚本。

`finish` 会：

1. 使用 `subagent_session_status.json` 检查每个 sessions_spawn session 是否已完成、无失败、无超时、无待重跑。
2. 使用 `subagent_task_plan.json` 检查每个 output file。
3. 校验 JSONL、line_id/parent_line_id 覆盖、重复和额外行。
4. 合并到 `model_resolved_decisions.jsonl`。
5. 针对原始完整 pin_info 运行 `validate_mapping`。
6. 仅在 `validation_report.json` 为 PASS 后调用 `render_template_sheets.py` 生成正式 Excel。

检查：

```text
intermediate/subagent_output_check.json
intermediate/validation_report.json
output/signal_interface_*.xlsx
```

如果失败，按：

```text
intermediate/failed_subagent_rerun_plan.md
```

重跑失败 TASK，不能手工跳过门禁。
