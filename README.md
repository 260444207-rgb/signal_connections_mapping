# openclaw_signal_mapping_layered_skill

基于框图连接表、`pin_info.json`、自然语言硬件规则，生成标准 13 列信号接口列表。

## 主流程

```text
1. normalize_connections
   读取输入 Excel，保留 sheet 和前 9 列连接事实。

2. generate_candidates
   按 block_info 中的器件 code/料号，从 pin_info.json 取源端 pin 列表并生成候选。

3. build_analysis_context_groups
   按器件类别、映射族、hard-case 状态隔离模型上下文。

4. pre_resolve_candidates
   仅做轻量预裁决：候选分数高且明显领先时自动输出，其余进入模型分析。

5. build_model_resolution_tasks
   为每个 context_group 导出隔离 subagent 任务包。

6. semantic subagent resolution
   模型读取任务包，结合自然语言规则和 pin 列表做语义映射。

7. merge_decisions / validate_mapping / render_template_sheets
   合并、校验并渲染 output/signal_interface.xlsx。
```

## 规则维护

用户优先维护自然语言规则：

```text
rules/natural_language_mapping_rules_template.md
```

规则分三层：

```text
1. 链路级规则：描述业务链路拓扑、方向、索引关系，例如 TX 控制链路中 SROC 的 SW0/TX_SW0 控制 TXVGA0。
2. 器件级规则：描述某个器件 code/料号下各 pin 的功能。
3. 通用信号规则：描述 SPI、差分、电源、总线等通用语义。
```

模型语义分析使用：

```text
prompts/semantic_mapping_resolver.md
```

不要把复杂硬件语义强行写成脚本正则。脚本只负责流程与数据约束；信号作用判断交给隔离模型上下文。

## 输出约束

输出 Excel：

```text
output/signal_interface.xlsx
```

约束：

```text
1. 输入 workbook 的 sheet 结构必须保留。
2. block_info 原样保留。
3. 其他连接 sheet 重建为标准 13 列。
4. 前 9 列是原始连接事实，模型不得修改。
5. 信息不足时输出 unresolved。
```

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

## 常用命令

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

模型分析后，把结果写入：

```text
data/{uuid}/intermediate/model_resolved_decisions.jsonl
```

完成渲染：

```bash
python script/run_pipeline.py \
  --task-dir data/{uuid} \
  --connections input_block_diagram.xlsx \
  --template-excel input_block_diagram.xlsx \
  --pins pin_info.json \
  --output-mode template_sheets \
  --stage finish
```

单次脚本验证：

```bash
python script/run_pipeline.py \
  --task-dir data/{uuid} \
  --connections input_block_diagram.xlsx \
  --template-excel input_block_diagram.xlsx \
  --pins pin_info.json \
  --output-mode template_sheets \
  --stage all
```

`all` 只执行脚本路径，不会自动调用真实 subagent；未解决项会保留为 `unresolved`。
