# Context Group Subagent 指令

这是 `script/build_model_resolution_tasks.py` 生成的 `TASK_xxx.prompt.md` 的说明性版本。真实任务执行时，以任务包中的 `TASK_xxx.json` 和同目录生成的 `TASK_xxx.prompt.md` 为准。

subagent 的核心语义方法见：

```text
prompts/semantic_mapping_resolver.md
```

## 输入任务包

```json
{
  "context_group": {},
  "diagram_link_context": {},
  "link_family_profiles": {},
  "link_family_summary": {},
  "line_ids": [],
  "normalized_connections": [],
  "candidate_mappings": [],
  "source_device_pins": {},
  "matched_rule_sections": [],
  "natural_language_rules": {
    "full_text": "",
    "link_level_rules": "",
    "device_level_rules": "",
    "general_signal_rules": ""
  },
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
6. 再阅读 context_group.link_family_ids、mapping_families、target_device_signatures、link_contexts。
7. 链路级数据、目标上下文和信号族只作为组内上下文，不作为重新拆 subagent 的理由。
8. 同类型不同实例、不同链路可以共享源端 pin 功能理解；同一 link_family 下不同 subagent 可以共享链路级语义，但不能复制其他 line_id 或其他源端器件的 selected_pin。
9. 每条 line_id 的链路归属、实例编号、对端端口、网络名必须独立判断。
10. 信息不足时输出 unresolved，不得硬猜。
```

## 执行要求

```text
1. subagent 必须读取分配给自己的所有 TASK_xxx.json。
2. subagent 必须把结果写入调用方指定的 batch JSONL 文件。
3. JSONL 每行一个 mapping_decision object，不要 Markdown 包裹。
4. 输出前必须自检：assigned_line_ids == output_line_ids。
5. 输出前必须自检：没有重复 line_id，没有额外 line_id。
6. 输出前必须自检：非空 selected_pin / selected_pins 都逐字来自入参 pin_info.json 中当前源端器件编码对应的 source_device_pins 或 candidate_mappings.available_pins；不得改写 pin 名、大小写、下划线或使用其他器件的 pin。
7. subagent 最终回复只能摘要输出条数、unresolved 条数和原因；真正结果以 JSONL 文件为准。
8. 如果 source_device_pins 没有当前源端器件编码，或当前 line_id 的 available_pins 为空，必须输出 unresolved，并在 analysis 中说明入参 pin_info 缺少该器件 pin 信息。
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

一条逻辑连接对应多个物理 pin 时，使用 `selected_pins`、`net_names`、`analyses`、`confidences` 数组；不要在模型输出里新增 `line_id`。
