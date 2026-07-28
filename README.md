# openclaw_signal_mapping_layered_skill

基于框图连接表、`pin_info.json`、自然语言硬件规则，生成标准 13 列信号接口列表。

详细目录和数据结构说明见：

```text
STRUCTURE.md
```

完整语义生成步骤见：

```text
RUNBOOK.md
```

关键提醒：

```text
stage=all 只做脚本冒烟验证，不会自动调用语义 subagent。
正式信号接口列表必须经过 model_tasks -> 语义分析 -> finish。
```

## pin_info 硬门禁

`pin_info.json` 是唯一的原理图 pin 数据源。框图 port、连线名、block 名、link_info 和自然语言规则只能帮助理解信号语义，不能替代 pin_info 生成 pin。

当某个 `source_part_id` 在 `pin_info.json` 中没有对应 pin 列表或列表为空时：

```text
1. candidate_mappings.available_pins = []
2. pre_resolve_candidates 输出 unresolved / Low / needs_human_review=true
3. 不写入 needs_model_resolution.jsonl
4. 不创建 semantic subagent/TASK
5. 最终 Excel 保留连接行；若输入框图连线名称有效，则网络命名使用该连线名称（清洗后），否则原理图Pin脚和网络命名为空
```

不要让模型用框图 `源Port` / `目的Port`、规则文本或器件常识猜 pin；正确动作是等待用户补充该源端器件的 pin 信息。

## 主流程

```text
1. normalize_connections
   读取输入 Excel，保留 sheet 和前 9 列连接事实。

2. generate_candidates
   按 block_info 中的器件 code/料号，从 pin_info.json 取源端 pin 列表并生成候选。
   如果 pin_info.json 没有当前源端器件编码对应的 pin 列表或列表为空，available_pins 为空；该器件后续不进入语义模型分析，相关行保持 unresolved。

3. infer_signal_shapes
   在语义映射前判断 scalar / bus / differential，输出 signal_shape_inference.jsonl，并把 signal_shape_info 写回 normalized_connections。
   如果识别出一条原始连接对应多个物理 pin，会在进入候选生成和 subagent 前展开为多个 line_id，例如 1868#1、1868#2。
   总线只按明确位宽自动展开；差分可根据源端 pin 列表中的 P/N 对和本地规则提示识别。
   如果是否差分/总线必须结合上下文才能判断，则保留原始 line 给 subagent；subagent 可输出 `parent_line_id=原line_id`、`line_id=原line_id#数字` 的多行 decision。

4. build_analysis_context_groups
   按源端器件 pin 体系和 hard-case 状态隔离模型上下文。
   链路族、对端器件、映射族作为组内上下文传给 subagent，不再作为硬切分维度。

5. pre_resolve_candidates
   仅做轻量预裁决：候选分数高且明显领先时自动输出，其余进入模型分析。

6. build_model_resolution_tasks
   为每个 context_group 导出隔离 subagent 任务包，并把同一 link_family 的共享链路语义整理为 link_family_profiles。

7. semantic subagent resolution
   模型读取任务包，结合框图表链路上下文、自然语言规则和 pin 列表做语义映射。

8. merge_decisions / validate_mapping / render_template_sheets
   合并、校验并渲染 output/signal_interface_YYYYMMDD_HHMMSS.xlsx。
```

## 规则维护

用户优先维护自然语言规则：

```text
rules/natural_language_mapping_rules_template.md
```

运行时可通过 `--project-rules` / `--user-rules` 追加外部规则文件。脚本也会自动发现上游编排生成的外部器件规则文件：

```text
external_device_rules.md
```

自动发现位置按顺序为：

```text
<task_root>/design/external_device_rules.md
<task_root>/input/external_device_rules.md
<task_root>/rules/external_device_rules.md
<connections 所在目录>/external_device_rules.md
```

发现后会作为 project rules 追加，并与默认规则、显式 `--project-rules` / `--user-rules` 合并为：

```text
<task_root>/signal_interface/intermediate/combined_mapping_rules.md
```

`infer_signal_shapes` 和 `build_model_resolution_tasks` 会读取同一份 combined rules，保证前置形态判断和 subagent 规则召回使用一致的规则上下文。

规则分四层：

```text
0. 链路族规则：重复主链路的整体功能、方向、器件角色、索引和 P/N 传播。
1. 链路级规则：业务链路拓扑、方向、索引关系，例如 TX 控制链路中 SROC 的 SW0/TX_SW0 控制 TXVGA0。
2. 器件级规则：某个器件 code/料号下各 pin 的功能。
3. 通用信号规则：SPI、差分、电源、总线等通用语义。
```

模型语义分析使用：

```text
prompts/semantic_mapping_resolver.md
```

不要把复杂硬件语义强行写成脚本正则。脚本只负责流程与数据约束；信号作用判断交给隔离模型上下文。

规则模板可以使用轻量 RULE 块：

```text
### RULE: SROC_PA_CONTROL SROC 功放/前端控制
适用条件：
源端器件：SROC / 0302078562
链路类型：PA_CONTROL_CHAIN
典型端口：PA_SW0, FEM_TDDSW00
```

脚本会识别 RULE 所在的 link/device/signal/global 层级，先按 source_part_id、link_family、mapping_family、signal_shape 和适用条件确定性召回，再用关键词补充；结果写入 `matched_rule_sections`，不会根据规则块直接裁决 pin。

subagent 分析优先级：

```text
用户当前明确说明
  > 链路族/链路级语义
  > 当前器件上下游
  > 器件级局部规则
  > 通用信号规则
  > pin 名称相似度
```

## 可选链路信息 Sheet

输入 Excel 可以新增一个 `link_info` 或 `链路信息` sheet，用于手工标注链路族和链路实例。推荐表头：

```text
链路类型
链路编号
器件Sheet
用户标识的链路信息
器件角色说明
相关连线ID
```

其中 `链路类型` 相同表示同一个 link family，`链路编号` 表示一条具体链路，`器件Sheet` 写这条链路涉及的器件 sheet 名，`器件角色说明` 用自然语言描述同一个 sheet 在不同链路里的角色。`相关连线ID` 是可选列，只在需要精确约束时填写；多个值可用逗号、分号或顿号分隔，连线 ID 也可以写成 `sheet:连线ID`。这些链路信息会作为对应源端器件 subagent 的上下文，不会单独触发新的 subagent 分组。

该 sheet 会被原样保留，不参与最终 13 列重建。

不提供 `link_info` / `链路信息` 时流程仍然正常工作：系统会根据 block_info 的器件信息、源/目的 Block、端口名、连线名推断 mapping_family，并按器件上下文生成 subagent 任务。

导出 `model_tasks` 时，框图信息表中的链路信息会被整理到每个 `TASK_xxx.json` 的：

```text
diagram_link_context
sheet_device_context
pin_allocation_context
link_family_profiles
matched_rule_sections
```

`diagram_link_context` 包含组内链路族、链路编号、用户链路说明、器件角色说明、相关 sheet、逐行 line_id 的链路上下文。`sheet_device_context` 说明同一个 source_sheet_name 是一个物理器件实例，sheet 内多个 block_id/block_name 是该器件的逻辑块/端口视图。`pin_allocation_context` 说明同一物理器件实例内的 pin 复用约束、每条 line 的 scalar/bus/differential 判断、候选 pin 空间和可能允许共享 pin 的同源端口扇出/同网/同 base_connection 分组。`link_family_profiles` 包含同一 link_family 跨 source_device subagent 的共享链路语义、涉及器件、链路实例、用户说明和代表性 line 示例；它用于借鉴链路逻辑，不能直接复制其他 line_id 的 pin 结论。`matched_rule_sections` 包含脚本召回的候选自然语言规则块及 layer/source_file/match_type。subagent 必须按 custom/user > link > device > signal > global > 名称相似度阅读，再做 pin 映射判断。

导出 `model_tasks` 时会先生成全局任务规划：

```text
intermediate/model_resolution_tasks/global_link_plan.md
intermediate/model_resolution_tasks/global_link_plan.json
intermediate/model_resolution_tasks/subagent_session_plan.md
intermediate/model_resolution_tasks/subagent_session_plan.json
intermediate/model_resolution_tasks/subagent_task_plan.md
intermediate/model_resolution_tasks/subagent_task_plan.json
```

这里会持久化列出全局 link_family 摘要、每个 source_device subagent session、session 内小 TASK 的顺序、pin_allocation_state_file、session 级 pin_allocation_context_file、line 数量、任务目标和任务文件名。平衡模式下，小 TASK 先按源端物理器件实例切分，再按链路/信号语义切分，最后才按 50 条左右的数量上限截断；数量不是第一切分依据。subagent 数量仍按源端器件 pin 体系控制，同一个 session 的多个 TASK 由同一个 subagent 顺序处理。每个 TASK 内会嵌入 `task_scope.session_state_snapshot`，这是生成任务时从 state 文件读取的轻量摘要；权威动态状态仍是 `pin_allocation_state_file`。任务包放在 `intermediate/model_resolution_tasks/tasks/`，文件名类似 `TASK_01_SROC_302078562_MULTI_LINK_61889c68782d_PART01.json`，方便用户按器件类型和批次检查。所有任务共用 `intermediate/model_resolution_tasks/subagent_task_prompt.md`，不再为每个器件重复生成一份几乎相同的 md。

## 输出约束

输出 Excel：

```text
output/signal_interface_YYYYMMDD_HHMMSS.xlsx
```

约束：

```text
1. 输入 workbook 的 sheet 结构必须保留。
2. block_info 原样保留。
3. 其他连接 sheet 重建为标准 13 列。
4. 前 9 列是原始连接事实，模型不得修改。
5. 信息不足时输出 unresolved。
6. 一条逻辑连接对应多个物理 pin 时，优先在映射前或 subagent 输出阶段展开为 `主line_id#数字` 多行；兼容旧任务时才使用 `selected_pins` 数组。
7. `原理图Pin脚` 必须逐字来自入参 `pin_info.json` 中该源端器件编码对应的 pin 列表；不得改写、翻译、补全、大小写规范化或使用其他器件 pin。
8. 输入框图中的连线名称和模型输出的 `net_name` 只作为诊断信息，不覆盖脚本生成的规范 `网络命名`；没有 `原理图Pin脚` 时，`网络命名` 必须为空。
9. `LINE_xxx`、`line`、包含 `line` 的连线名称是默认连线名，不得直接作为网络名。
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

正式生成推荐顺序：

```text
1. 运行 model_tasks，生成 subagent_task_plan 和 TASK_xxx.json。
2. 检查 intermediate/signal_shape_inference.jsonl，确认 bus/differential 的前置判断是否合理。
3. 阅读 global_link_plan.md/json、subagent_session_plan.md/json 和 subagent_task_plan.md/json，按 source_device session 规划 subagent 批次。
4. 让每个 subagent 顺序读取同一 session 下的 TASK_xxx.json，先看 task_scope、signal_shape_info、diagram_link_context、sheet_device_context、pin_allocation_context、link_family_profiles 和 pin_allocation_state_file，再写入 TASK 的 output_contract.output_file，并更新 state 文件。
5. 运行 finish；主控流程会先检查所有 subagent output_file，失败则生成 failed_subagent_rerun_plan.md 并中止。
6. 检查通过后自动合并为 intermediate/model_resolved_decisions.jsonl，并输出 output/signal_interface_YYYYMMDD_HHMMSS.xlsx。
7. 检查 validation_report.json 和 unresolved 列表。
```

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

模型分析后，把每个 TASK 的结果写入：

```text
data/{uuid}/signal_interface/intermediate/subagent_outputs/TASK_xxx.jsonl
```

`stage=finish` 会检查并合并所有 TASK 输出，生成：

```text
data/{uuid}/signal_interface/intermediate/model_resolved_decisions.jsonl
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

单次脚本冒烟验证：

```bash
python script/run_pipeline.py \
  --task-dir data/{uuid} \
  --connections input_block_diagram.xlsx \
  --template-excel input_block_diagram.xlsx \
  --pins pin_info.json \
  --output-mode template_sheets \
  --stage all
```

`all` 只执行脚本路径，不会自动调用真实 subagent；未解决项会保留为 `unresolved`。如果用户要的是正式语义结果，不要停在 `all`。
