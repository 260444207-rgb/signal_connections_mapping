# 模型上下文隔离工作流

## 目标

把待模型分析的连接按器件类别、映射族和疑难状态切分为独立 context group，避免不同硬件语义互相污染。

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
device_category: PA / ADC / DAC / POWER / GPIO / SWITCH / UNKNOWN ...
mapping_family: RF_CHAIN / POWER_ENABLE / SPI_CTRL / GPIO_CTRL / DATA_BUS / UNKNOWN ...
isolation_level: device_category_and_mapping_family / hard_case
```

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
2. normalized_connections
3. candidate_mappings.available_pins
4. natural_language_mapping_rules_template.md
5. needs_model_resolution 原因
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

不得使用 context_group、device_category、mapping_family 生成 sheet。
