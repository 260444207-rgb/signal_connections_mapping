# 模型上下文隔离工作流

## 目标

把待模型分析的连接按源端器件 pin 体系和疑难状态切分为独立 context group。链路族、对端器件、映射族不再作为硬切分维度，而是作为组内上下文传给 subagent。

分析策略是：

```text
以源端器件类型为 subagent 分析单元
同一个源端器件 subagent 可以顺序处理多个小 TASK，以降低单次推理上下文
链路族/链路级信息作为组内上下文
同一 link_family 会生成共享 link_family_profiles，注入给相关 source_device subagent
同一源端器件下的不同实例共享 pin 功能理解
hard_case 单独隔离
```

上下文隔离只影响模型分析，不影响最终输出分页。

## 位置

```text
normalize_connections
  ↓
generate_candidates
  ↓
pre_resolve_candidates
  ↓
build_analysis_context_groups
  ↓
build_model_resolution_tasks
  ↓
semantic subagent resolution
```

## 隔离维度

```text
source_device_signature: DEVICE_INFO:<source_part_id> 或 UNKNOWN_SOURCE:<sheet/block>
isolation_level: source_device_context / hard_case
```

以下字段作为 context_group 内部上下文，不参与硬切分：

```text
link_family_ids: RF_TX_CHAIN / FEEDBACK_CHAIN / PA_CONTROL_CHAIN / SPI_CONTROL_CHAIN / LOCAL_DEVICE_MAPPING ...
link_family_sources: explicit_link_info / inferred_from_connection / fallback_mapping_family / fallback_device_context
target_device_signatures: DEVICE_INFO:<target_part_id> 或 TARGET_CONTEXT:<目的Block名称/标识>
mapping_families: RF_CHAIN / POWER_ENABLE / SPI_CTRL / GPIO_CTRL / DATA_BUS / UNKNOWN ...
link_contexts / link_instance_ids / user_link_infos / device_role_infos
```

`link_info` / `链路信息` sheet 是可选输入。它只增强当前源端器件 subagent 的链路上下文，不会单独触发新的 subagent 分组。没有显式链路族时，系统仍会根据 block_info 器件信息、源/目的 Block、端口名、连线名推断映射族；若无法归入链路族，则进入 `LOCAL_DEVICE_MAPPING` 作为组内上下文。

## subagent

统一使用：

```text
prompts/semantic_mapping_resolver.md
```

subagent 按 `subagent_session_plan` 启动。一个 session 对应一个源端器件 pin 体系；同一 session 下可以有多个小任务包：

```text
intermediate/model_resolution_tasks/tasks/TASK_器件类型_器件编码_链路范围_hash.json
```

任务包包含当前组的：

```text
1. task_scope
2. context_group
3. sheet_device_context
4. pin_allocation_context
5. diagram_link_context
6. link_family_profiles
7. matched_rule_sections
8. link_family_summaries
9. normalized_connections
10. source_device_pins
11. pin_selection_policy
12. candidate_mappings rough search hints
13. rule_source 指向运行时收集全部分层规则后的 combined_mapping_rules.md
14. needs_model_resolution 原因
```

`task_scope` 指向 `global_link_plan_file` 和 `pin_allocation_state_file`。同一个 session 的 TASK 必须顺序处理：处理前读取 state，处理后更新 state，记录已用 pin、允许复用 pin、冲突和 completed_task_ids。

`link_family_profiles` 是跨 subagent 共享的链路语义上下文。它让同一 link_family 下的 SROC、TXVGA、91fbsw 等不同源端器件 subagent 借鉴拓扑、方向、实例索引、差分/总线展开规律和用户说明，但不能直接复制其他 line_id 或其他源端器件的 selected_pin。

`sheet_device_context` 表达 sheet 与物理器件实例的关系：同一 source_sheet_name 是一个物理器件实例，sheet 内多个 block_id/block_name 是该器件的逻辑块/端口视图。`pin_allocation_context` 表达同一物理器件实例内 pin 的默认互斥使用关系、scalar/bus/differential 判断和允许共享的候选分组。

如果 `source_device_pins` 为空，或没有当前 `source_part_id` 对应的非空 pin 列表，表示入参 `pin_info.json` 缺少当前源端器件的 pin 信息。该 context 不应启动语义 subagent；保留 unresolved，等待用户补充 pin 信息。

不要因为源Block/源Port/目的Port 看起来像 pin 名就绕过此门禁。port 是框图逻辑接口，不是原理图 pin；没有 pin_info 时不能创建“让 subagent 猜 pin”的任务。

## 输出约束

subagent 只能输出当前任务包中的 line_id。

禁止输出：

```text
output_sheet_name
source_sheet_name
修改后的前 9 列连接事实
```

信息不足时输出：

```text
decision_type = unresolved
confidence = Low
needs_human_review = true
```

## 与输出分页的关系

最终输出分页只来自：

```text
normalized_connection.output_sheet_name
```

不得使用 context_group、link_family_id、device_category、mapping_family 生成 sheet。
