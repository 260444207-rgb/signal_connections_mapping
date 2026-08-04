# Semantic Mapping Resolver

本文件是语义 subagent 的唯一裁决规则。生成的 `subagent_task_prompt.md` 只说明文件路径和执行顺序，不重复本规则。

必须由 `sessions_spawn` 启动的模型 subagent 完成每个 TASK 的语义裁决。不得编写脚本自动分析 TASK、匹配 pin、生成 mapping_decision，或跳过 `sessions_spawn`；脚本/工具只可用于读取输入、写入 JSONL/state，以及校验格式、覆盖关系和 pin 合法性。

## 输入

每个 `TASK_xxx.json` 只包含当前小批次：

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

`task_scope.session_context_file` 保存同一源端器件 session 共用的：

```text
sheet_device_context
pin_allocation_context
link_family_profiles
rule_library
```

`connection_defaults` 是逐行省略字段的确定默认值；不是推测。逐行连接事实只读取 `normalized_connections`，不要从其他汇总结构复制或改写。

## 硬门禁

1. 原始 `pin_info` 是唯一 pin 来源。
2. `selected_pin` / `selected_pins` 必须逐字来自当前源端器件的完整 pin 列表，不得翻译、改写、补全或使用其他器件的 pin。
3. `inline_full` 模式下，`source_device_pins` 是完整列表。
4. `grouped_large_catalog` 模式下，当前组无排序且不是闭集；找不到合理 pin 时必须读取 `group_file` 的其他 `groups` 或 `all_pins`。
5. 查看完整列表后仍无合理 pin，输出 `unresolved / Low / needs_human_review=true`，不得把框图 port、规则文本或器件常识伪造成 pin。

## 分析顺序

1. 读取 `task_scope.session_context_file`；同一 session 只需完整读取一次。
2. 每个 TASK 开始前读取 `pin_allocation_state_file` 最新状态。不同物理实例分别记录 pin 占用。
3. 阅读 `context_group` 和 `diagram_link_context`，理解链路族、上下游角色、实例编号和用户说明。
4. 阅读 session context 中当前 `link_family_profiles`。只能借鉴链路拓扑、方向、索引和分析方法，不能复制其他 line_id 或其他器件的 pin 结论。
5. 按 TASK 的 `matched_rule_refs.rule_key` 到 `rule_library` 取规则正文。规则优先级：

```text
custom/user > link > device > signal > global > lexical fallback
```

`match_type` 和 `matched_terms` 只解释召回原因，不代表 pin 排名。若某条规则实际影响裁决，在 `analysis` 中简短记录：

```text
规则依据：<layer>/<rule_id>/<match_type>
```

6. 对每条 `normalized_connection` 先判断链路语义、方向、源/目的角色、端口编号和 `signal_shape_info`，再从权威 pin 列表选择同功能 pin。
7. 只有 `needs_model_shape_review=true`、证据冲突或明显违背连接语义时，才修正前置形态判断，并在 `analysis` 中说明。

## 物理实例与 pin 复用

- 同一个 `source_sheet_name` 表示一个物理器件实例；同 sheet 内不同 block 是逻辑块或端口视图。
- 普通 scalar pin 在同一物理实例内默认不能分配给多个不同语义 line。
- 只有 session context 的 `potential_shared_pin_groups`、同一源端口扇出、同一网络、同一 `base_connection_id`、多端口别名或明确规则允许时，才可共享。
- 不同 `physical_device_instance_id` 可以各自使用同名 pin。
- 两条不同语义连接竞争同一个 pin 时，不得硬分配；保留更匹配的一条，另一条输出 unresolved 并说明冲突。

## 差分、总线和展开

- 已有 `signal_shape_info.is_expanded_member=true`：当前行只输出一个 `selected_pin`，不得再次使用 `selected_pins` 展开。
- 未展开连接需要多个物理 pin：优先输出多行 decision：

```text
line_id = 原line_id#数字
parent_line_id = 原line_id
selected_pin = 单个 pin
```

- 只有兼容旧任务时才使用 `selected_pins` 数组。
- 不得把普通 scalar 因名称相似而拆成多个 pin。

## 输出

输出必须写入 `output_contract.output_file`，格式为 JSONL，每行一个 object，不要 Markdown 或 JSON 数组。必须遵守 `schema_file`。

允许字段：

```text
line_id, parent_line_id, selected_pin, selected_pins,
decision_type, confidence, analysis, net_name, net_names,
analyses, confidences, needs_human_review
```

必填字段：

```text
line_id, selected_pin, decision_type, confidence, analysis, net_name
```

约束：

- `decision_type` 只能是 `model_resolved` 或 `unresolved`。
- `confidence` 只能是 `High`、`Medium`、`Low` 或空字符串。
- 不得输出中文 Excel 列名、`source_sheet_name`、`output_sheet_name` 或自造字段。
- 模型不负责网络命名：`net_name=""`，`net_names=[]`。最终渲染脚本统一生成网络名和命名依据。
- 每个 `expected_line_ids` 必须由同名 `line_id`，或合法的 `parent_line_id` 展开行覆盖。

推荐单行格式：

```json
{"line_id":"","parent_line_id":"","selected_pin":"","selected_pins":[],"decision_type":"model_resolved|unresolved","confidence":"High|Medium|Low","analysis":"","net_name":"","net_names":[],"needs_human_review":false}
```

写入后重新读取输出文件，检查 JSONL、覆盖、重复/额外 line_id 和 pin 合法性。然后更新 `pin_allocation_state_file`；只有来自完整原始 pin 列表的非空 pin 才能写入 `used_pins`。
