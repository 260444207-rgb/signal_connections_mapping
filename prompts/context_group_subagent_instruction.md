# Context Group Subagent 指令

这是 `script/build_model_resolution_tasks.py` 生成的共享 `subagent_task_prompt.md` 的说明性版本。真实任务执行时，以 `subagent_task_plan.md/json` 分配的 `TASK_xxx.json` 和同目录生成的 `subagent_task_prompt.md` 为准。

subagent 的核心语义方法见：

```text
prompts/semantic_mapping_resolver.md
```

## 输入任务包

```json
{
  "context_group": {},
  "sheet_device_context": {},
  "pin_allocation_context": {},
  "diagram_link_context": {},
  "link_family_profiles": {},
  "link_family_summaries": {},
  "line_ids": [],
  "normalized_connections": [],
  "candidate_mappings": [],
  "source_device_pins": {},
  "matched_rule_sections": [],
  "rule_source": {},
  "needs_model_resolution": [],
  "required_output": {}
}
```

## 工作方式

```text
1. 只处理当前任务包列出的 line_id。
2. 先阅读 context_group.source_device_signature 和 source_device_pins，建立当前源端器件 pin 功能理解。
3. 必须阅读 diagram_link_context。它来自框图信息表/link_info/链路信息 sheet，用来判断链路归属、链路实例、器件角色和特殊连接说明。
4. 再阅读 matched_rule_sections。它是脚本召回的候选自然语言规则块，只能辅助阅读，不能直接替代逐行判断。
5. 必须阅读 link_family_profiles。它是同一 link_family 跨多个 source_device subagent 共享的链路级上下文，用来借鉴拓扑、方向、实例索引、差分/总线展开规律和用户说明。
6. 必须阅读 sheet_device_context。同一个 source_sheet_name 表示同一个物理器件实例；sheet 内多个 block_id/block_name 是该器件的逻辑块/端口视图。
7. 必须阅读 pin_allocation_context。同一个 physical_device_instance_id 内共享同一个 pin 空间；每条连接的 scalar/bus/differential 已在映射前写入 signal_shape_info；普通 scalar pin 默认不可被不同语义 line_id 重复使用。
8. 再阅读 context_group.link_family_ids、mapping_families、target_device_signatures、link_contexts。
9. 链路级数据、目标上下文和信号族只作为组内上下文，不作为重新拆 subagent 的理由。
10. 同类型不同实例、不同链路可以共享源端 pin 功能理解；同一 link_family 下不同 subagent 可以共享链路级语义，但不能复制其他 line_id 或其他源端器件的 selected_pin。
11. 每条 line_id 的链路归属、实例编号、对端端口、网络名必须独立判断；同时必须在同一个 physical_device_instance_id 内检查 pin 是否被重复分配。
12. 信息不足时输出 unresolved，不得硬猜。
```

## 执行要求

```text
1. 平衡模式下，一个源端器件 subagent 可以顺序读取同一 `subagent_session_id` 下的多个小 `TASK_xxx.json`；不要因为 TASK 变小就为同一源端器件启动多个互不共享状态的 subagent。
2. subagent 必须先读取 `task_scope.global_link_plan_file` 和 `task_scope.pin_allocation_state_file`，再处理当前 TASK。
3. subagent 必须把结果写入 TASK JSON 中 `output_contract.output_file` 指定的 JSONL 文件。
4. 每完成一个 TASK，必须更新 `task_scope.pin_allocation_state_file`，记录已用 pin、允许复用 pin、冲突和 completed_task_ids。
3. JSONL 每行一个 mapping_decision object，不要 Markdown 包裹。
4. 输出前必须自检：assigned_line_ids == output_line_ids。
5. 输出前必须自检：没有重复 line_id，没有额外 line_id。
6. 输出前必须自检：非空 selected_pin / selected_pins 都逐字来自入参 pin_info.json 中当前源端器件编码对应的 source_device_pins；candidate_mappings 只提供 top candidates，不承载完整 pin 列表。不得改写 pin 名、大小写、下划线或使用其他器件的 pin。
7. subagent 最终回复只能摘要输出条数、unresolved 条数和原因；真正结果以 JSONL 文件为准。
8. 如果 source_device_pins 没有当前源端器件编码，必须输出 unresolved，并在 analysis 中说明入参 pin_info 缺少该器件 pin 信息。
9. 输出前必须自检：同一个 physical_device_instance_id 内，除同一源端口扇出到多个目标端口、同一网络/同一 base_connection_id/多端口别名/用户规则明确允许外，不得让多个不同语义 scalar line_id 选择同一个 selected_pin。
10. 如果 selected_pin/selected_pins 为空，net_name/net_names 必须为空；没有原理图 pin 时不得生成网络名。
11. `LINE_xxx`、`line`、包含 `line` 的连线名称是默认连线名，不是有效网络名，不得直接复制到 net_name/net_names。
12. signal_shape_info 是进入映射分析前生成的形态判断结果，来源包括自动总线宽度识别、源端 pin 列表 P/N 对识别和本地自然语言规则提示。只有 needs_model_shape_review=true、证据冲突或明显不符合连接语义时，才修正该判断，并在 analysis 中说明。
13. 如果 normalized_connection.signal_shape_info.is_expanded_member=true，该差分/总线成员已经是独立 line_id；该行只输出单个 selected_pin，不要再输出 selected_pins。
14. 如果某条未展开 line 需要结合上下文才知道是差分/总线，可以直接输出多行展开 decision：`line_id=原line_id#数字`、`parent_line_id=原line_id`，每行一个 selected_pin。
```

## 输出格式

必须写入 `output_contract.output_file`，每行一个 JSON object。只在聊天中输出 JSON 数组或分析说明、不写入 output_file，视为未完成。

```json
{"line_id":"","parent_line_id":"","selected_pin":"","selected_pins":[],"decision_type":"model_resolved|unresolved","confidence":"High|Medium|Low","analysis":"","net_name":"","net_names":[],"needs_human_review":false}
```

如果 TASK 中仍存在未展开的多物理 pin 逻辑连接，优先输出 `parent_line_id#数字` 多行 decision；不要把多个 pin 塞在同一个 `selected_pins` 数组里。只有兼容旧任务时才使用 `selected_pins`、`net_names`、`analyses`、`confidences` 数组。
