# openclaw_signal_mapping_layered_skill

基于框图连接表、`pin_info.json`、自然语言硬件规则，生成标准 14 列信号接口列表。

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
1. route_model_resolution 输出 unresolved / Low / needs_human_review=true
2. 不写入 needs_model_resolution.jsonl
3. 不创建 semantic subagent/TASK
4. 最终 Excel 保留连接行，原理图Pin脚为空，网络命名也固定为空
```

不要让模型用框图 `源Port` / `目的Port`、规则文本或器件常识猜 pin；正确动作是等待用户补充该源端器件的 pin 信息。

## 主流程

```text
1. normalize_connections
   读取输入 Excel，保留 sheet 和前 10 列连接事实；第 10 列为“连线属性”。

2. infer_signal_shapes
   在语义映射前判断 scalar / bus / differential，输出 signal_shape_inference.jsonl，并把 signal_shape_info 写回 normalized_connections。
   如果识别出一条原始连接对应多个物理 pin，会在进入 subagent 前展开为多个 line_id，例如 1868#1、1868#2。
   总线只按明确位宽自动展开；差分可根据源端 pin 列表中的 P/N 对和本地规则提示识别。
   如果是否差分/总线必须结合上下文才能判断，则保留原始 line 给 subagent；subagent 可输出 `parent_line_id=原line_id`、`line_id=原line_id#数字` 的多行 decision。

3. build_analysis_context_groups
   按源端器件 pin 体系和 hard-case 状态隔离模型上下文。
   链路族、对端器件、映射族作为组内上下文传给 subagent，不再作为硬切分维度。

4. route_model_resolution
   直接检查 pin_info 门禁；有源端 pin 的连接全部进入语义模型，不做相似度候选或自动 pin 预裁决。

5. build_model_resolution_tasks
   为每个 context_group 导出隔离 subagent 任务包，并把同一 link_family 的共享链路语义整理为 link_family_profiles。器件 pin 数量超过 100 时生成一个无损、多标签、无排名的 session 级 pin_groups 文件；TASK 只内嵌当前组，并保留其他组和 all_pins 回退。

6. semantic subagent resolution
   模型读取任务包，结合框图表链路上下文、自然语言规则和 pin 列表做语义映射。

7. merge_decisions / validate_mapping / render_template_sheets
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

脚本会识别 RULE 所在的 link/device/signal/global 层级，先按 source_part_id、link_family、mapping_family、signal_shape 和适用条件确定性召回，再用关键词补充。规则正文按 session 去重写入 `session_context.rule_library`，TASK 只保存 `matched_rule_refs`；召回不会直接裁决 pin。

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

该 sheet 会被原样保留，不参与最终 14 列重建。

不提供 `link_info` / `链路信息` 时流程仍然正常工作：系统会根据 block_info 的器件信息、源/目的 Block、端口名、连线名推断 mapping_family，并按器件上下文生成 subagent 任务。

导出 `model_tasks` 时，每个 `TASK_xxx.json` 只保留当前批次：

```text
diagram_link_context
connection_defaults
normalized_connections
matched_rule_refs
```

`normalized_connections` 是唯一逐行事实；`diagram_link_context` 只保留组级链路总览。物理实例、pin 共享关系、link family profiles 和规则正文统一放入 session 级 `session_context_file`，同一 subagent 只读一次。

导出 `model_tasks` 时会先生成全局任务规划：

```text
intermediate/model_resolution_tasks/global_link_plan.md
intermediate/model_resolution_tasks/global_link_plan.json
intermediate/model_resolution_tasks/subagent_session_plan.md
intermediate/model_resolution_tasks/subagent_session_plan.json
intermediate/model_resolution_tasks/subagent_session_status.json
intermediate/model_resolution_tasks/subagent_task_plan.md
intermediate/model_resolution_tasks/subagent_task_plan.json
```

模型只需读取 `subagent_session_plan.json`、`subagent_session_status.json` 和共享 prompt。其他计划文件供人工检查或 finish 校验，不要求重复载入。小 TASK 先按物理实例、再按链路/信号语义、最后按数量上限切分；同一 session 的 TASK 由同一 subagent 顺序处理。每个 TASK 前读取最新 `pin_allocation_state_file`，不再嵌入生成时即过期的 state snapshot。主控必须在 sessions_spawn 启动/等待/失败重跑后维护 status；未完成、失败、超时或待重跑的 session 会阻止 finish。

## 输出约束

输出 Excel：

```text
output/signal_interface_YYYYMMDD_HHMMSS.xlsx
```

约束：

```text
1. 输入 workbook 的 sheet 结构必须保留。
2. block_info 原样保留。
3. 其他连接 sheet 重建为标准 14 列。
4. 前 10 列是原始连接事实，模型不得修改；旧的 9 列输入会补空“连线属性”。
5. 信息不足时输出 unresolved。
6. 一条逻辑连接对应多个物理 pin 时，优先在映射前或 subagent 输出阶段展开为 `主line_id#数字` 多行；兼容旧任务时才使用 `selected_pins` 数组。
7. `原理图Pin脚` 必须逐字来自入参 `pin_info.json` 中该源端器件编码对应的 pin 列表；不得改写、翻译、补全、大小写规范化或使用其他器件 pin。
8. pin decision 不包含网络命名字段；最终 Excel 为保持标准 14 列，“网络命名”列固定为空。
9. 网络命名是独立后处理，使用 `signal-interface-net-naming` skill，不属于本 skill 的完成标准。
```

标准 14 列：

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
连线属性
原理图Pin脚
分析说明
映射置信度
网络命名
```

## 常用命令

正式生成推荐顺序：

```text
1. 运行 model_tasks，生成 session plan 和 TASK_xxx.json。
2. 检查 intermediate/signal_shape_inference.jsonl，确认 bus/differential 的前置判断是否合理。
3. 只读取 subagent_session_plan.json 和 subagent_task_prompt.md，按 source_device session 规划 subagent 批次。
4. 每个 subagent 先读取一次 session_context_file，再顺序处理 TASK；每个 TASK 前读取最新 state，写入 output_file 后更新 state。
5. 主控更新 subagent_session_status.json；只有所有 session 都 spawned/completed、无 failed/timed_out/rerun_required，且 completed_task_ids 覆盖全部 TASK，才运行 finish。
6. 直接执行 intermediate/finish_command.txt；不得手动 merge/validate/render 或自写替代脚本。主控流程会先检查 session 状态和所有 subagent output_file，失败则生成 failed_subagent_rerun_plan.md 并中止。
7. 检查通过后自动合并为 intermediate/model_resolved_decisions.jsonl，并输出 output/signal_interface_YYYYMMDD_HHMMSS.xlsx。
8. 检查 validation_report.json 和 unresolved 列表。
```

准备中间数据：

```powershell
python '<signal_connections_mapping_skill>\scripts\run_pipeline.py' --task-dir '<task_root>' --connections '<connections.xlsx>' --pins '<pin_info.json>' --stage prepare
```

导出模型任务包：

```powershell
python '<signal_connections_mapping_skill>\scripts\run_pipeline.py' --task-dir '<task_root>' --connections '<connections.xlsx>' --pins '<pin_info.json>' --stage model_tasks
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

```powershell
python '<signal_connections_mapping_skill>\scripts\run_pipeline.py' --task-dir '<task_root>\signal_interface' --stage finish
```

实际运行时直接执行 `intermediate/finish_command.txt`；其中脚本和 task_dir 都是绝对路径。禁止从 TASK_ROOT 调用 `.\scripts\run_pipeline.py` 或复制 skill 的 `scripts`。`pipeline_run_config.json` 已记录原始连接表、pin_info、模板和输出模式，finish 不需要重新猜参数。正式结果不得使用 `render_outputs.py` 或自写脚本生成。

单次脚本冒烟验证：

```powershell
python '<signal_connections_mapping_skill>\scripts\run_pipeline.py' --task-dir '<task_root>' --connections '<connections.xlsx>' --template-excel '<connections.xlsx>' --pins '<pin_info.json>' --output-mode template_sheets --stage all
```

`all` 只执行脚本路径，不会自动调用真实 subagent；未解决项会保留为 `unresolved`。如果用户要的是正式语义结果，不要停在 `all`。
