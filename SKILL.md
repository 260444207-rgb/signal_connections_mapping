---
name: openclaw-signal-mapping-layered
description: 基于输入框图 Excel、pin_info.json 和自然语言硬件规则，按输入 sheet 结构生成标准 13 列信号接口列表；模型分析按器件/映射族隔离。
---

# OpenClaw Signal Mapping Layered Skill

## 核心目标

根据输入框图连接事实、源端器件 pin 列表、自然语言硬件规则，生成：

```text
output/signal_interface.xlsx
```

输出必须严格沿用输入 Excel 的 sheet 结构：

```text
block_info 原样保留
其他连接 sheet 重建为标准 13 列
```

## 主逻辑

```text
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

脚本负责事实整理、候选生成、任务隔离、校验和渲染。

模型负责根据自然语言规则和 pin 列表做语义判断。

## 必须遵守

1. 不得根据模型、group、context_group 新建输出 sheet。
2. 最终输出 sheet 只能来自输入 Excel。
3. `block_info` 原样保留。
4. 连接 sheet 输出标准 13 列。
5. 前 9 列是原始连接事实，模型不得修改。
6. 信息不足时输出 `unresolved`，不得硬猜。

## 关键文件

主流程：

```text
workflows/main_pipeline.md
```

自然语言规则入口：

```text
rules/natural_language_mapping_rules_template.md
```

自然语言规则分为：

```text
链路级规则：跨器件业务链路拓扑、方向、索引关系
器件级规则：单个器件 code/料号下的 pin 功能
通用信号规则：SPI、差分、电源、总线等通用语义
```

语义模型 prompt：

```text
prompts/semantic_mapping_resolver.md
```

规则层级：

```text
rules/rule_layers.md
```

核心脚本：

```text
script/run_pipeline.py
script/normalize_connections.py
script/generate_candidates.py
script/build_analysis_context_groups.py
script/pre_resolve_candidates.py
script/build_model_resolution_tasks.py
script/merge_decisions.py
script/validate_mapping.py
script/render_template_sheets.py
```

## 阶段命令

准备中间数据：

```bash
python script/run_pipeline.py \
  --task-dir data/{uuid} \
  --connections input_block_diagram.xlsx \
  --pins pin_info.json \
  --stage prepare
```

导出模型任务包：

```bash
python script/run_pipeline.py \
  --task-dir data/{uuid} \
  --connections input_block_diagram.xlsx \
  --pins pin_info.json \
  --stage model_tasks
```

模型分析后，将结果写入：

```text
data/{uuid}/intermediate/model_resolved_decisions.jsonl
```

合并、校验并渲染：

```bash
python script/run_pipeline.py \
  --task-dir data/{uuid} \
  --connections input_block_diagram.xlsx \
  --template-excel input_block_diagram.xlsx \
  --pins pin_info.json \
  --output-mode template_sheets \
  --stage finish
```

一键脚本流程：

```bash
python script/run_pipeline.py \
  --task-dir data/{uuid} \
  --connections input_block_diagram.xlsx \
  --template-excel input_block_diagram.xlsx \
  --pins pin_info.json \
  --output-mode template_sheets \
  --stage all
```

注意：`all` 不会自动调用真实 subagent；它会把未解决项保留为 `unresolved`。需要模型语义分析时使用 `model_tasks` 阶段导出任务包。
