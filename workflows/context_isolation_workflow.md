# 模型上下文隔离工作流

## 目标

把待模型分析的连接按源端器件 pin 体系和疑难状态切分为独立 context group。链路族、对端器件、映射族不再作为硬切分维度，而是作为组内上下文传给 subagent。

分析策略是：

```text
以源端器件类型为 subagent 分析单元
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

subagent 只能读取当前任务包：

```text
intermediate/model_resolution_tasks/CTX_xxx.json
```

任务包包含当前组的：

```text
1. context_group
2. diagram_link_context
3. link_family_profiles
4. matched_rule_sections
5. link_family_summary
6. normalized_connections
7. candidate_mappings.available_pins
8. natural_language_mapping_rules_template.md
9. needs_model_resolution 原因
```

`link_family_profiles` 是跨 subagent 共享的链路语义上下文。它让同一 link_family 下的 SROC、TXVGA、91fbsw 等不同源端器件 subagent 借鉴拓扑、方向、实例索引、差分/总线展开规律和用户说明，但不能直接复制其他 line_id 或其他源端器件的 selected_pin。

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
