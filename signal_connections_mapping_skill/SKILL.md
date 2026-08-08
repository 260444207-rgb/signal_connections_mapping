---
name: diagram-logical-connection-mapping
description: 基于框图 Excel、pin_info 和自然语言硬件规则生成标准 13 列信号接口列表。用于从框图逻辑连接推导源端原理图 pin、处理差分/总线展开、跨相同器件实例复用分析经验，并输出经过校验的正式 Excel。
---

# diagram-logical-connection-mapping

## 完成标准

正式结果必须经过：

```text
model_tasks
  -> 按 session 执行语义 TASK
  -> 每个 TASK 写入 output_contract.output_file
  -> 更新 pin_allocation_state_file
  -> finish
  -> validation_report.json 为 PASS
```

`finish` 不是任务生成入口。新任务必须先运行 `model_tasks`，再执行并等待全部 subagent session；输出文件未齐全时禁止调用 `finish`。`stage=all` 只用于脚本冒烟验证。

完整命令和故障处理见 [RUNBOOK.md](RUNBOOK.md)。只有需要维护内部结构时才阅读 [STRUCTURE.md](STRUCTURE.md)。

## 输入与输出

必需输入：

```text
框图 Excel
pin_info.json
```

可选输入：

```text
link_info / 链路信息 sheet
external_device_rules.md
--project-rules / --user-rules
```

正式输出：

```text
output/signal_interface_YYYYMMDD_HHMMSS.xlsx
```

必须保持输入 workbook 的 sheet 结构：

- `block_info`、`link_info` / `链路信息` 原样保留。
- 其他连接 sheet 重建为标准 13 列。
- 不得按模型结果新建、删除或合并 sheet。
- 前 9 列是原始连接事实，模型不得修改。

## 核心门禁

`pin_info` 是唯一可信 pin 来源。

- `selected_pin` / `selected_pins` 必须逐字来自当前源端器件的原始完整 pin 列表。
- 不得用框图 port、连线名、block 名、规则文本或器件常识生成 pin。
- 缺少源端 pin 时直接保留 `unresolved / Low`，不生成该器件的语义 TASK。
- 信息不足时输出 unresolved，不得硬猜。
- 最终 `validate_mapping` 始终针对原始完整 `pin_info`。

## pin 数量超过 100

只在单器件 pin 数量 `>100` 时生成一个 session 级 `*.pin_groups.json`：

- 无损：`all_pins` 保留原始完整列表。
- 多标签：同一 pin 可以属于多个语义组。
- 不排名：组内顺序只保持原始 pin 顺序。
- TASK 只内嵌当前相关组。
- 当前组找不到合理 pin 时，必须读取其他组或 `all_pins`。
- 不把语义组称为 candidates。

100 个及以下 pin 直接内嵌完整列表，不生成分组文件。

## 任务执行

运行 `model_tasks` 后，只需先读取：

```text
intermediate/model_resolution_tasks/subagent_session_plan.json
intermediate/model_resolution_tasks/subagent_session_status.json
intermediate/model_resolution_tasks/subagent_task_prompt.md
```

Markdown 计划、task plan 和 global plan 仅用于人工检查或 finish 校验，不要求模型重复读取。

每个 session 对应一个源端器件 pin 体系：

1. 必须使用 `sessions_spawn` 命令真实启动模型 subagent 分析每个 session / TASK；不得由主控、脚本或其他命令替代模型语义分析，也不得用脚本跳过 subagent。
2. 启动或等待每个 subagent 时，超时时间必须设置为 30 分钟（1800000 ms）。超时表示该 session 未完成，不能进入 finish。
3. subagent 不得编写 Python / PowerShell / JavaScript 等脚本来分析 TASK、匹配 pin 或生成 mapping_decision；语义判断必须由模型完成。
4. subagent 只允许使用工具读取输入、写入 `output_contract.output_file` 和更新 state，或做 JSONL 格式/覆盖校验；这些工具操作不得替代 pin 语义裁决。
5. 同一 session 的 TASK 由同一个 subagent 顺序处理。
6. session 开始时读取一次 `session_context_file`，其中包含共享链路 profile、规则正文和跨 TASK pin 共享关系。
7. 每个 TASK 开始前读取最新 `pin_allocation_state_file`。
8. 只处理 `output_contract.expected_line_ids`。
9. 写入 `output_contract.output_file` 后更新 state，再处理下一 TASK。

主控必须维护 `subagent_session_status.json`。每个 session 只有同时满足 `spawned=true`、`completed=true`、`failed=false`、`timed_out=false`、`rerun_required=false`，且 `completed_task_ids` 覆盖该 session 全部 TASK，才允许进入 `finish`。失败或超时后必须按 `failed_subagent_rerun_plan.md` 用 `sessions_spawn` 重跑/等待完成，并更新状态文件；不得只因为 output_file 存在就 finish。

同料号的多个物理实例可以共享器件 pin 功能理解，但 pin 占用按 `physical_device_instance_id` 隔离。后续实例和 TASK 可以参考前面分析方法及 state，不得直接复制不匹配的 line_id 结论。

并行时一次最多启动 2 个不同 session；同一 session 内不得并行。

## TASK 数据边界

TASK 只包含当前批次：

```text
task_scope
context_group
source_device_pins
pin_catalog_context
diagram_link_context
connection_defaults
normalized_connections
matched_rule_refs
output_contract
schema_file
```

`normalized_connections` 是唯一逐行事实。其他结构不得重复逐行 block、port、shape 或 line 信息。

`connection_defaults` 表示省略字段的确定默认值；异常字段仍保留在对应 connection 中。

共享内容只放在 `session_context_file`：

```text
sheet_device_context
pin_allocation_context
link_family_profiles
rule_library
```

规则优先级：

```text
custom/user > link > device > signal > global > lexical fallback
```

规则召回不选择 pin；subagent 根据 `matched_rule_refs` 读取规则正文后逐行判断。

## 差分、总线和 pin 复用

- 前置 `signal_shape_info` 是默认形态判断；只有标记复核或明显冲突时才修正。
- 已展开成员只输出一个 `selected_pin`。
- 未展开的多 pin 连接优先输出 `原line_id#数字` 多行，并设置 `parent_line_id`。
- 普通 scalar pin 在同一物理实例内默认不能被不同语义 line 重复使用。
- 只有同一源端口扇出、同一网络、同一 base connection、多端口别名、session 共享组或明确规则允许时才可复用。

## 网络命名

模型不负责网络命名；为兼容 schema 输出 `net_name=""`、`net_names=[]`。`render_template_sheets.py` 根据源/目的 block 和 port 统一生成网络名并追加命名依据。没有 selected pin 时网络名为空。

## 阶段命令

生成模型任务：

```bash
python scripts/run_pipeline.py \
  --task-dir data/{uuid} \
  --connections input_block_diagram.xlsx \
  --pins pin_info.json \
  --stage model_tasks
```

subagent 完成全部 TASK 后：

```bash
python scripts/run_pipeline.py \
  --task-dir data/{uuid} \
  --connections input_block_diagram.xlsx \
  --template-excel input_block_diagram.xlsx \
  --pins pin_info.json \
  --output-mode template_sheets \
  --stage finish
```

`finish` 会先检查 `subagent_session_status.json` 的 sessions_spawn 完成状态，再检查 JSONL 格式、line 覆盖、重复/额外 line、pin 合法性、合并结果和最终 workbook。失败项按 `failed_subagent_rerun_plan.md` 重跑，不得绕过。
