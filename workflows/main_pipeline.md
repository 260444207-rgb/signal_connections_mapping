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
infer_signal_shapes
  ↓
build_analysis_context_groups
  ↓
pre_resolve_candidates
  ↓
build_model_resolution_tasks
  ↓
semantic subagent resolution
  ↓
check_subagent_outputs
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
3. 读取 block_info 中的框图标识 -> 器件信息，并建立 block_id/block_name 别名
4. 读取可选 link_info / 链路信息 sheet，注入 link_family_id、link_instance_id、user_link_info；没有该 sheet 时保持字段为空，后续按器件上下文兜底
5. 只展开显式总线格式，如 XXX[7:0] 或 XXX*4
```

不得根据器件语义修改端口名，不得把端口改成 default，不得用模型推断覆盖前 9 列。

### generate_candidates

根据 `source_part_id` 从 `pin_info.json` 读取源端器件 pin 列表，生成 `candidate_mappings.jsonl`。

候选分数只用于辅助，不代表最终语义判断。

`available_pins` 必须来自入参 `pin_info.json` 中当前源端器件编码对应的 pin 列表。如果找不到该编码或列表为空，进入缺 pin_info 硬门禁：

```text
available_pins = []
不允许从源Port/目的Port/连线名生成候选 pin
不允许把框图 port 当作原理图 pin
该器件后续跳过语义模型分析，相关连接保持 unresolved
```

此门禁高于 link_info、mapping_family、自然语言规则和端口名称相似度。

### infer_signal_shapes

读取 `normalized_connections.jsonl`、`pin_info.json` 和合并后的自然语言规则，生成 `signal_shape_inference.jsonl`，并把 `signal_shape`、`expected_physical_pin_count`、`signal_shape_info` 写回 `normalized_connections.jsonl`。若一条原始连接对应多个物理 pin，会在进入候选生成和 subagent 前展开为多个 normalized row，`line_id` / `connection_id` 使用 `原ID#数字`。

该阶段只判断 scalar / bus / differential 和预计物理 pin 数，不选择具体 pin；后续 subagent 必须结合当前源端器件 pin 列表和语义上下文独立裁决 `selected_pin`。未自动展开但经上下文判断需要展开的连接，应输出 `parent_line_id#数字` 多行 decision。

### build_analysis_context_groups

按源端 `source_part_id` 对应的器件 pin 体系和 hard-case 状态隔离模型上下文，生成 `analysis_context_groups.json`。

硬分组维度：

```text
source_device_signature
isolation_level
```

组内上下文字段：

```text
link_family_ids / link_family_sources
mapping_families
target_device_signatures
link_contexts / link_instance_ids / user_link_infos / device_role_infos
```

器件类型签名只使用 block_info 的器件信息；源Block名称和 Port 仅用于模型语义判断。链路族、目标上下文和映射族只作为同一个源端器件 subagent 的分析上下文，不再作为重新起 subagent 的理由。

对重复主链路，subagent 必须先按链路族理解全局功能、方向、上下游和索引关系，再在该链路语义约束下复用器件类型局部 pin 规则。

该分组只决定模型分析边界，不决定输出 sheet。

### pre_resolve_candidates

主流程中这是轻量预裁决阶段。

只在候选 pin 分数非常高且明显领先时自动输出；其余行全部进入 `needs_model_resolution.jsonl`，由语义模型处理。

如果 `available_pins=[]`，不是“其余行进入模型分析”，而是直接输出 `unresolved / Low / needs_human_review=true`，并且不写入 `needs_model_resolution.jsonl`。

脚本不承载器件特殊语义，也不允许用框图 port 伪造 pin。

### build_model_resolution_tasks

按 `analysis_context_groups.json` 和 `needs_model_resolution.jsonl` 导出隔离模型任务包：

```text
intermediate/model_resolution_tasks/
├── manifest.json
├── global_link_plan.md
├── global_link_plan.json
├── subagent_session_plan.md
├── subagent_session_plan.json
├── subagent_task_plan.md
├── subagent_task_plan.json
├── subagent_task_prompt.md
└── tasks/
    └── TASK_器件类型_器件编码_链路范围_hash_PARTxx.json
```

任务包包含：

注意：只有 source_device_pins 中存在当前源端器件的非空 pin 列表时，才允许生成 TASK。缺 pin_info 的对象已经在 pre_resolve 阶段保持 unresolved，不应出现在 subagent 任务中。

```text
1. 当前 task_scope（session、global_link_plan_file、pin_allocation_state_file、前序 TASK 输出）
2. 当前 context_group 小批次
3. 当前 sheet_device_context
4. 当前 pin_allocation_context
5. 当前 diagram_link_context
6. 当前 link_family_profiles
7. 当前 matched_rule_sections
8. 当前 link_family_summaries
9. 当前 TASK normalized_connections
10. 当前 TASK source_device_pins
11. 当前 TASK pin_selection_policy
12. 当前 TASK candidate_mappings rough search hints
13. rule_source 指向运行时收集全部分层规则后的 combined_mapping_rules.md
14. needs_model_resolution 原因
```

`link_family_profiles` 会把同一 link_family 的共享链路语义注入到所有相关 source_device subagent 中。它用于借鉴链路拓扑、方向、实例索引和用户说明，不用于脚本裁决 pin。

`sheet_device_context` 会告诉 subagent：一个连接 sheet 表示一个物理器件实例，sheet 内不同 block_id/block_name 只是该器件的逻辑块/端口视图。`pin_allocation_context` 会告诉 subagent：前置 signal_shape_info、同一 pin 空间、以及普通 scalar 的 pin 默认不可被不同语义 line_id 重复使用，除非同一源端口扇出到多个目标端口、同网、同 base_connection、多端口别名或用户规则明确允许。

在真正启动 subagent 前，应先阅读本地持久化的 `global_link_plan.md`、`subagent_session_plan.md` 和 `subagent_task_plan.md`。subagent 按 source_device session 启动；同一个 session 内的多个小 TASK 由同一个 subagent 顺序处理，并通过 `pin_allocation_state_file` 传递已用 pin、允许复用 pin 和冲突信息。不要因为 TASK 文件变多就为同一个源端器件启动多个互不共享状态的 subagent。

### semantic subagent resolution

subagent 使用 `prompts/semantic_mapping_resolver.md`。

模型根据源端 pin 列表、目的端描述、连接方向、网络名、自然语言规则判断信号作用，再选择承担同样作用的源端 pin。

模型输出写入：

```text
intermediate/subagent_outputs/TASK_xxx.jsonl
```

信息不足时输出 `unresolved`。

### check / merge / validate / render

`finish` 前先运行 `check_subagent_outputs`。它按 `subagent_task_plan.json` 检查每个 TASK 的 `output_contract.output_file` 是否存在、是否为 JSONL、line_id 是否完整覆盖。检查失败会生成：

```text
intermediate/subagent_output_check.json
intermediate/failed_subagent_rerun_plan.md
```

并中止，不进入合并、校验和渲染。失败 subagent 必须重新启动分析并写入对应 output_file。

全部通过后自动合并为 `intermediate/model_resolved_decisions.jsonl`，再合并脚本预裁决和模型裁决，校验后渲染正式 Excel：

```text
output/signal_interface_YYYYMMDD_HHMMSS.xlsx
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

如果模型阶段判断一条逻辑连接对应多个物理 pin，应输出多行 decision：`line_id=原line_id#数字`、`parent_line_id=原line_id`、每行一个 `selected_pin`。渲染阶段会复制 parent 原始连接事实并把连线ID改为 `主连线ID#数字`，除连线ID和后 4 列外，前置字段不得变化。

`原理图Pin脚` 只能逐字使用入参 `pin_info.json` 中当前源端器件编码对应的 pin 字符串。模型不得补全、改写、翻译、调整大小写或使用其他器件的 pin。

同一物理器件实例内重复使用同一个 pin 时，必须有同网、同 base_connection、多端口别名或用户规则依据；否则应 unresolved 或在 validation 中暴露 warning。

## 5. 规则入口

用户维护自然语言规则：

```text
rules/natural_language_mapping_rules_template.md
```

命令行 `--project-rules` / `--user-rules` 会追加外部自然语言规则。运行 prepare/model_tasks/finish 时，脚本会在 task 目录中生成：

```text
intermediate/combined_mapping_rules.md
```

前置 `infer_signal_shapes` 和 subagent 任务构建都读取这份合并后的规则，避免两个阶段看到不同规则。

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
