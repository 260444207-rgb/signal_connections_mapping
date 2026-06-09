# 主流程：语义隔离映射 Pipeline

## 1. 核心目标

根据输入框图 Excel 的连接事实、`pin_info.json` 的源端器件 pin 列表、自然语言项目规则，生成标准 13 列信号接口列表。

最终输出严格沿用输入 Excel 的 sheet 结构：

```text
block_info 原样保留
其他连接 sheet 重建为标准 13 列
```

## 2. 主流程

```text
init_task
  ↓
normalize_connections
  ↓
generate_candidates
  ↓
build_analysis_context_groups
  ↓
pre_resolve_candidates
  ↓
build_model_resolution_tasks
  ↓
semantic subagent resolution
  ↓
merge_decisions
  ↓
validate_mapping
  ↓
render_template_sheets
```

## 3. 阶段职责

### normalize_connections

读取输入 Excel/JSON/CSV，生成 `intermediate/normalized_connections.jsonl`。

只做事实标准化：

```text
1. 保留 source_sheet_name / output_sheet_name
2. 保留前 9 列连接事实
3. 读取 block_info 中的 sheet -> 器件 code/料号
4. 只展开显式总线格式，如 XXX[7:0] 或 XXX*4
```

不得根据器件语义修改端口名，不得把端口改成 default，不得用模型推断覆盖前 9 列。

### generate_candidates

根据 `source_part_id` 从 `pin_info.json` 读取源端器件 pin 列表，生成 `candidate_mappings.jsonl`。

候选分数只用于辅助，不代表最终语义判断。

### build_analysis_context_groups

按器件类别、映射族、hard-case 状态隔离模型上下文，生成 `analysis_context_groups.json`。

该分组只决定模型分析边界，不决定输出 sheet。

### pre_resolve_candidates

主流程中这是轻量预裁决阶段。

只在候选 pin 分数非常高且明显领先时自动输出；其余行全部进入 `needs_model_resolution.jsonl`，由语义模型处理。

脚本不承载器件特殊语义。

### build_model_resolution_tasks

按 `analysis_context_groups.json` 和 `needs_model_resolution.jsonl` 导出隔离模型任务包：

```text
intermediate/model_resolution_tasks/
├── index.json
├── CTX_xxx.json
└── CTX_xxx.prompt.md
```

任务包包含：

```text
1. 当前 context_group
2. 当前组 normalized_connections
3. 当前组 candidate_mappings 和 available_pins
4. natural_language_mapping_rules_template.md 内容
5. needs_model_resolution 原因
```

### semantic subagent resolution

subagent 使用 `prompts/semantic_mapping_resolver.md`。

模型根据源端 pin 列表、目的端描述、连接方向、网络名、自然语言规则判断信号作用，再选择承担同样作用的源端 pin。

模型输出写入：

```text
intermediate/model_resolved_decisions.jsonl
```

信息不足时输出 `unresolved`。

### merge / validate / render

合并脚本预裁决和模型裁决，校验后渲染正式 Excel：

```text
output/signal_interface.xlsx
```

## 4. 正式输出约束

标准 13 列：

```text
源Block标识
源Block名称
源Port
目的Block标识
目的Block名称
目的Port
连线ID
连线名称
连线方向
原理图Pin脚
分析说明
映射置信度
网络命名
```

前 9 列是连接事实字段，模型不得修改。

如果未来模型阶段需要把一条逻辑连接展开为多条物理 pin，必须先形成明确的展开计划，再生成 `主连线ID#数字` 的 normalized row；不得在最终渲染阶段临时新增行。

## 5. 规则入口

用户维护自然语言规则：

```text
rules/natural_language_mapping_rules_template.md
```

通用硬件规则：

```text
rules/global_mapping_rules.md
rules/net_naming_rules.md
rules/validation_rules.md
```

模型语义分析 prompt：

```text
prompts/semantic_mapping_resolver.md
```
