# 模型上下文隔离工作流

## 目标

把待模型分析的连接按链路族来源、block_info 器件信息、对端器件信息、映射族和疑难状态切分为独立 context group，避免不同硬件语义互相污染。

分析策略是：

```text
以重复链路族为主分析单元
以器件类型为局部规则复用单元
没有链路级数据时，以器件上下文和 mapping_family 为兜底分析单元
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
source_device_signature: DEVICE_INFO:<source_part_id> 或 UNKNOWN_SOURCE_DEVICE_INFO
target_device_signature: DEVICE_INFO:<target_part_id> 或 TARGET_CONTEXT:<目的Block名称/标识>
link_family_id: RF_TX_CHAIN / FEEDBACK_CHAIN / PA_CONTROL_CHAIN / SPI_CONTROL_CHAIN / LOCAL_DEVICE_MAPPING ...
link_family_source: explicit_link_info / inferred_from_connection / fallback_mapping_family / fallback_device_context
analysis_strategy: link_family_first_then_device_template_reuse / mapping_family_first / device_type_pair_with_link_context
mapping_family: RF_CHAIN / POWER_ENABLE / SPI_CTRL / GPIO_CTRL / DATA_BUS / UNKNOWN ...
isolation_level: device_type_pair_and_mapping_family / hard_case
```

`link_info` / `链路信息` sheet 是可选输入。没有显式链路族时，`build_analysis_context_groups` 仍会根据 block_info 器件信息、源/目的 Block、端口名、连线名推断映射族；若无法归入链路族，则进入 `LOCAL_DEVICE_MAPPING` 并按器件上下文启动 subagent。

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
2. link_family_summary
3. normalized_connections
4. candidate_mappings.available_pins
5. natural_language_mapping_rules_template.md
6. needs_model_resolution 原因
```

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
