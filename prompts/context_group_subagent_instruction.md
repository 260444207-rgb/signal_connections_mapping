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
1. subagent 必须读取分配给自己的所有 TASK_xxx.json。
2. subagent 必须把结果写入调用方指定的 batch JSONL 文件。
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
```

## 输出格式

只输出 JSON 数组：

```json
[
  {
    "line_id": "",
    "selected_pin": "",
    "selected_pins": [],
    "decision_type": "model_resolved|unresolved",
    "confidence": "High|Medium|Low",
    "analysis": "",
    "net_name": "",
    "net_names": [],
    "needs_human_review": false
  }
]
```

一条逻辑连接对应多个物理 pin 时，使用 `selected_pins`、`net_names`、`analyses`、`confidences` 数组；不要在模型输出里新增 `line_id`。渲染阶段会按 `主连线ID#数字` 展开输出行。
