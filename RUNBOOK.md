# 完整语义生成 Runbook

本 runbook 面向执行模型。用户要求“生成信号接口列表”“调用 skill 输出结果”“根据框图和 pin_info 推出映射”时，默认需要走完整语义流程，而不是只跑脚本兜底。

## 一句话原则

```text
stage=all 只能做脚本冒烟验证；它不会调用语义 subagent。
真正的信号接口列表必须经过 model_tasks -> 语义分析写入 output_contract.output_file -> finish 前主控检查 -> 合并 -> finish。
```

如果最终 `mapping_decisions.jsonl` 中大部分都是 `unresolved`，不能把它当作已经完成的信号接口列表。

## pin_info 缺失时的硬门禁

在任何语义分析或 subagent 规划之前，先确认每条连接的 `source_part_id` 能在 `pin_info.json` 中找到非空 pin 列表。

如果找不到，执行路径固定为：

```text
generate_candidates: available_pins=[]
pre_resolve_candidates: selected_pin="", decision_type=unresolved, confidence=Low, net_name="", needs_human_review=true
needs_model_resolution.jsonl: 不写入该行
model_resolution_tasks: 不为该源端器件创建 TASK，不启动 semantic subagent
final Excel: 保留连接事实，原理图Pin脚="", 网络命名=""
```

框图 `源Port`、`目的Port`、连线名、block 名、link_info、规则文本和器件常识都不能代替 pin_info。没有源端器件 pin 列表时，不允许用这些信息生成 subagent 任务，也不允许让模型猜 `selected_pin`。

## 强制执行流程

### 1. 准备任务目录

```bash
python script/run_pipeline.py \
  --task-dir <task_dir> \
  --connections <框图信息表.xlsx> \
  --pins <pin_info.json> \
  --stage prepare
```

产物：

```text
<task_dir>/intermediate/normalized_connections.jsonl
<task_dir>/intermediate/analysis_context_groups.json
<task_dir>/intermediate/candidate_mappings.jsonl
```

### 2. 导出模型任务包

```bash
python script/run_pipeline.py \
  --task-dir <task_dir> \
  --connections <框图信息表.xlsx> \
  --pins <pin_info.json> \
  --stage model_tasks
```

产物：

```text
<task_dir>/intermediate/needs_model_resolution.jsonl
<task_dir>/intermediate/model_resolution_tasks/manifest.json
<task_dir>/intermediate/model_resolution_tasks/global_link_plan.md
<task_dir>/intermediate/model_resolution_tasks/global_link_plan.json
<task_dir>/intermediate/model_resolution_tasks/subagent_session_plan.md
<task_dir>/intermediate/model_resolution_tasks/subagent_session_plan.json
<task_dir>/intermediate/model_resolution_tasks/subagent_task_plan.md
<task_dir>/intermediate/model_resolution_tasks/subagent_task_plan.json
<task_dir>/intermediate/model_resolution_tasks/subagent_task_prompt.md
<task_dir>/intermediate/model_resolution_tasks/tasks/TASK_器件类型_器件编码_链路范围_hash.json
```

必须先阅读持久化到本地的 `global_link_plan.md/json`、`subagent_session_plan.md/json` 和 `subagent_task_plan.md/json`，再启动语义分析。`global_link_plan` 是链路族全局摘要；`subagent_session_plan` 说明每个源端器件 subagent 要顺序处理哪些小 TASK；`subagent_task_plan` 是给脚本检查输出的扁平任务表；`subagent_task_prompt.md` 是所有 TASK 共享的模型分析说明。

### 3. 规划 subagent 批次

按 `subagent_session_plan.json` 中的 session 分组。平衡模式下，一个 session 就是一个源端器件 pin 体系的 subagent 分析单元；同一个 session 可以包含多个小 `TASK_xxx.json`，由同一个 subagent 顺序处理。推荐优先按以下维度检查任务：

```text
1. source_device_signature
2. isolation_level
3. link_family_ids
4. mapping_families
5. target_device_signatures
6. line_count
```

不要再因为小 TASK 数量变多、link_family、mapping_family 或 target_device_signature 不同而启动多个互不共享状态的 subagent；这些信息已经作为同一源端器件 session 的上下文提供。只有 hard_case 或未知源端器件需要额外隔离。

每个 subagent 必须拥有互不重叠的 `TASK_xxx.json` 列表。**必须启动隔离 subagent**去分析这些 TASK；同一个 session 内的 TASK 需要顺序执行。处理每个 TASK 前先看 `task_scope.session_state_snapshot`，再读取 session 级 `pin_allocation_context_file` 和权威 `pin_allocation_state_file`；前者提供跨 TASK 的 potential_shared_pin_groups，后者按 `physical_device_instance_id` 传递已用 pin、允许复用 pin 和冲突信息。TASK 分片原则是源端物理器件实例优先、链路/信号语义其次、数量上限最后。

### 4. 给 subagent 的任务必须包含这些约束

每个 subagent prompt 至少要写清楚：

```text
1. 只处理分配给自己的 session/TASK_xxx.json；同一 session 的多个 TASK 由同一个 subagent 顺序处理。
2. 只输出这些任务包内的 line_id。
3. selected_pin / selected_pins 必须逐字来自入参 pin_info.json 中当前源端器件编码对应的 source_device_pins；candidate_mappings 只是粗糙搜索提示，不是候选闭集，不是答案列表，score 不是置信度。
4. 如果当前源端器件在 pin_info.json 中没有非空 pin 列表，主控不应给该器件创建 TASK；若误收到这类 TASK，只能输出 unresolved，不能用框图 port 猜 pin。
5. 不得修改 normalized_connection，不得输出 output_sheet_name/source_sheet_name。
6. 多物理 pin 优先输出 `parent_line_id=原line_id` 且 `line_id=原line_id#数字` 的多行 decision；兼容旧任务时才使用 selected_pins。
7. 信息不足必须 unresolved，不得硬猜。
8. 输出 JSONL 到 TASK JSON 中 `output_contract.output_file` 指定的文件；每行一个 mapping_decision object。
9. 链路族、信号族、目标上下文只作为组内分析上下文，不作为要求用户重新拆 subagent 的理由。
10. 必须先阅读 task_json.diagram_link_context；这里是框图信息表中的链路上下文。
11. 必须阅读 task_json.matched_rule_sections；这里是脚本按层级确定性召回并用关键词补充的候选自然语言规则块。每块的 layer/source_file/match_type 表示层级、来源和召回原因，但不能替代逐行语义判断。
12. 必须阅读 task_json.link_family_profiles；这里是同一 link_family 跨 source_device subagent 共享的链路级语义上下文。
13. link_family_profiles 只能用于借鉴拓扑、方向、实例索引、差分/总线展开规律和用户说明；不得复制其他 line_id 或其他源端器件的 selected_pin。
14. 必须阅读 task_json.sheet_device_context；同一个 source_sheet_name 表示一个物理器件实例，sheet 内多个 block_id/block_name 是该器件的逻辑块或端口视图。
15. 必须阅读 task_json.pin_allocation_context；先判断连接是 scalar、bus 还是 differential。同一 physical_device_instance_id 内普通 scalar 的同一个 pin 默认不能分配给多个不同语义 line_id，除非同一源端口扇出到多个目标端口、同网、同 base_connection、多端口别名或用户规则明确允许。
16. 不得翻译、补全、改写、大小写规范化 pin 名；`原理图Pin脚` 必须保持 pin_info.json 中的原始 pin 字符串。
17. 如果 pin_info.json 没有当前源端器件编码对应的 pin 列表或列表为空，该器件不启动语义分析，不建 subagent/TASK；相关行保持 unresolved，等待用户补充 pin 信息。
18. 必须阅读 task_json.task_scope.global_link_plan_file 和 task_json.task_scope.pin_allocation_state_file；每完成一个 TASK 后按 physical_device_instance_id 更新 state 文件。
```

自动输出目录：

```text
<task_dir>/intermediate/subagent_outputs/
```

每个 TASK 的 `output_contract.output_file` 会指向类似：

```text
<task_dir>/intermediate/subagent_outputs/TASK_01_xxx.jsonl
```

只在聊天中粘贴 JSON、没有写入该文件，视为 subagent 失败。

### 5. 校验 subagent 批次输出

每个批次都要检查：

```text
1. assigned_line_ids == output_line_ids
2. 没有额外 line_id
3. 非空 selected_pin / selected_pins 都逐字来自该 line_id 源端器件编码对应的可用 pin 列表
4. 同一 physical_device_instance_id 内，没有未经说明的重复 selected_pin。
5. 输出字段符合 schemas/mapping_decision.schema.json
```

如果某批次失败，必须重新启动失败 subagent 分析并写入对应 output_file，不能直接 finish。

### 6. 主控检查并合并模型结果

运行 `stage=finish` 时，主控流程会先检查所有 TASK 的 `output_contract.output_file`：

```text
1. 输出文件必须存在。
2. 必须是 JSONL，每行一个 object。
3. 每个 TASK line_id 必须被同名 line_id 覆盖；如果上下文判断需要展开，可由 parent_line_id=TASK line_id 且 line_id=TASK line_id#数字 的多行 decision 覆盖。
4. 不得遗漏 TASK line_id；不得输出无合法 parent_line_id 的额外 line_id；不得重复输出 line_id。
```

检查通过后，主控流程自动合并所有 subagent 输出为：

```text
<task_dir>/intermediate/model_resolved_decisions.jsonl
```

检查失败时，主控流程会生成：

```text
<task_dir>/intermediate/subagent_output_check.json
<task_dir>/intermediate/failed_subagent_rerun_plan.md
```

并直接中止，不进入 merge/validate/render。必须按 `failed_subagent_rerun_plan.md` 重新启动失败 subagent，再重新运行 `stage=finish`。

### 7. 渲染最终 Excel

```bash
python script/run_pipeline.py \
  --task-dir <task_dir> \
  --connections <框图信息表.xlsx> \
  --template-excel <框图信息表.xlsx> \
  --pins <pin_info.json> \
  --output-mode template_sheets \
  --stage finish
```

最终输出：

```text
<task_dir>/output/signal_interface_YYYYMMDD_HHMMSS.xlsx
```

### 8. 最终检查

必须检查：

```text
1. validation_report.json status == PASS
2. normalized_count == decision_count
3. error_count == 0
4. 输出 workbook 的 sheet 顺序来自输入 workbook
5. block_info 原样保留
6. link_info / 链路信息 如果存在，原样保留
7. 连接 sheet 表头是标准 13 列
8. unresolved 数量和原因明确列出
```

## 不允许的完成条件

以下情况不能宣称“最终信号接口列表已完成”：

```text
1. 只跑了 stage=all，且没有执行语义分析。
2. subagent 没有写入 TASK JSON 中指定的 output_contract.output_file。
3. subagent_output_check.json 不是 PASS。
4. 没有生成 model_resolved_decisions.jsonl。
5. model_resolved_decisions.jsonl 没有覆盖 needs_model_resolution.jsonl 中的 line_id。
6. validation_report.json 不是 PASS。
7. 大部分行是 unresolved，但没有说明这是脚本兜底结果。
```
