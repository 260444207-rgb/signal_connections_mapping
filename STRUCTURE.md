# openclaw Signal Mapping Skill 结构说明

本文档说明 `D:\github\signal\signal_connections_mapping` 这个 skill 的目录结构、主流程、关键数据契约和 subagent 分组逻辑。

## 1. 总体目标

该 skill 用于把输入框图 Excel 和 `pin_info.json` 转换成标准 13 列信号接口列表。

核心约束：

```text
1. 输出 workbook 沿用输入 workbook 的 sheet 顺序和分页结构。
2. block_info 原样保留。
3. link_info / 链路信息 如果存在，也原样保留。
4. 其他连接 sheet 重建为标准 13 列。
5. 前 9 列连接事实来自输入框图，除多物理 pin 展开时连线ID追加 #数字外，不得被模型或脚本改写。
6. 后 4 列由脚本预裁决、模型语义分析、人工覆盖结果合并得到。
7. `原理图Pin脚` 必须逐字来自入参 `pin_info.json` 中当前源端器件编码对应的 pin 列表；不得改写 pin 字符串。入参没有该器件编码时，跳过该器件语义分析并保持 unresolved。
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

## 2. 顶层目录

```text
signal_connections_mapping/
├── SKILL.md
├── README.md
├── RUNBOOK.md
├── STRUCTURE.md
├── .gitignore
├── script/
├── prompts/
├── rules/
├── schemas/
└── workflows/
```

### SKILL.md

Codex 调用该 skill 时最先读取的入口说明。它描述：

```text
1. skill 的核心目标。
2. 主流程顺序。
3. 必须遵守的输出约束。
4. 关键脚本、prompt、规则文件。
5. 常用阶段命令。
```

### README.md

面向使用者的快速说明。它描述如何准备输入、如何运行 prepare/model_tasks/finish/all，以及最终输出约束。

### RUNBOOK.md

面向执行模型的完整语义生成步骤。它明确说明：

```text
1. stage=all 不是完整语义流程。
2. 正式输出必须经过 model_tasks、subagent 语义分析、model_resolved_decisions.jsonl、finish。
3. subagent 批次如何规划、如何约束输出、如何合并和校验。
```

### STRUCTURE.md

当前文件。面向维护者，用于解释目录职责、数据流、schema、subagent 分组和扩展点。

### .gitignore

忽略 Python 缓存、调试输出、任务中间目录，避免 `__pycache__` 和本地验证产物进入 skill。

## 3. 主流程

主入口脚本：

```text
script/run_pipeline.py
```

流程：

```text
init_task
  ↓
normalize_connections
  ↓
build_analysis_context_groups
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
  ↓
merge_decisions
  ↓
validate_mapping
  ↓
render_template_sheets
```

阶段命令：

```text
prepare:     生成 normalized_connections、analysis_context_groups、candidate_mappings
apply:       生成 pre_resolved_decisions 和 needs_model_resolution
model_tasks: 生成按源端器件 pin 体系隔离的 subagent 任务包和 subagent_task_plan
finish:      合并模型/人工结果，校验并渲染 Excel
all:         只走脚本路径，不会自动调用真实 subagent；只适合冒烟验证，未解决项保持 unresolved
```

正式语义输出必须按 `RUNBOOK.md` 执行，不得停在 `stage=all`。

## 4. script 目录

### script/common.py

公共工具：

```text
1. JSON/JSONL/CSV/XLSX 读写。
2. 文本标准化、方向标准化、简单名称相似度。
3. pin_info.json 加载。
4. 前导零料号兼容匹配。
5. 标准 13 列表头常量。
```

`pin_info.json` 原生格式：

```json
{
  "47151290": ["PIN_A", "PIN_B"],
  "0302078562": ["PIN_C", "PIN_D"]
}
```

脚本直接使用 `{器件料号: [pin名...]}`，不转换为 `{device_part_id, pin}` 对象列表。

### script/init_task.py

创建任务目录：

```text
task_dir/
├── intermediate/
└── output/
```

### script/normalize_connections.py

把输入框图表标准化为 `intermediate/normalized_connections.jsonl`。

职责：

```text
1. 读取 Excel 的所有连接 sheet。
2. 跳过 block_info、link_info / 链路信息、说明、目录等非连接 sheet。
3. 读取 block_info 中的 框图标识 -> 器件信息。
4. 建立 block_id/block_name/sheet_name 到器件信息的别名。
5. 读取可选 link_info / 链路信息 sheet。
6. 保留输入前 9 列连接事实。
7. 只展开显式总线格式，例如 XXX[7:0] 或 XXX*4。
8. 生成 source_part_id、target_part_id、link_contexts 等模型上下文字段。
```

可选链路信息 sheet 推荐列：

```text
链路类型 | 链路编号 | 器件Sheet | 用户标识的链路信息 | 器件角色说明 | 相关连线ID
```

说明：

```text
1. 链路类型相同表示一个 link_family。
2. 链路编号表示具体链路实例。
3. 器件Sheet 表示这条链路涉及哪些 sheet。
4. 相关连线ID 可空；为空时表示 sheet 参与该链路，但具体连接归属交给 subagent 判断。
5. 同一个 sheet 可以出现在多条链路中，例如 HBF 同时属于 TX/RX 链路。
```

### script/build_analysis_context_groups.py

生成 `intermediate/analysis_context_groups.json`。

硬分组维度：

```text
source_device_signature
isolation_level
```

也就是说，context_group 表示“同一个源端器件 pin 体系下的一组待分析连接”。如果 `source_part_id` 存在，同料号不同实例会合并分析；如果源端器件信息缺失，则按 sheet/block 上下文隔离未知源端。

组内上下文字段：

```text
link_family_ids
link_family_sources
target_device_signatures
mapping_families
link_contexts
link_instance_ids
user_link_infos
device_role_infos
```

`link_family_sources` 含义：

```text
explicit_link_info: 来自 link_info / 链路信息 sheet
inferred_from_connection: 从连接文本推断出链路族
fallback_mapping_family: 无显式链路族，按 RF/SPI/POWER/CLOCK 等映射族兜底
fallback_device_context: 无显式链路族和明确映射族，按器件上下文兜底
```

链路级数据、信号族和目标上下文不再用于重新起 subagent；它们只帮助同一个源端器件 subagent 判断每条连接的作用。

### script/generate_candidates.py

读取 `normalized_connections.jsonl` 和 `pin_info.json`，输出 `candidate_mappings.jsonl`。

职责：

```text
1. 根据 source_part_id 查找源端可用 pin。
2. 兼容前导零料号，例如 302078562 匹配 0302078562。
3. 基于 source_port、target_port、索引、方向生成轻量候选分数。
4. 输出 available_pins 和 top_k candidates。
5. 如果 source_part_id 在 pin_info.json 中没有对应 pin 列表，则 available_pins 为空；后续 pre_resolve 会保持 unresolved，并跳过该器件的语义模型分析。
```

候选分数只用于辅助，不代表最终语义判断。

### script/pre_resolve_candidates.py

脚本预裁决阶段。

仅当候选分数非常高且明显领先时自动输出 `project_rule_applied`。其余连接进入 `needs_model_resolution.jsonl`。

该脚本不得承载器件特殊语义，不得固化 TXVGA、SROC、SPI 等规则。

如果入参 `pin_info.json` 没有当前源端器件编码对应的 pin 列表，该脚本直接输出 unresolved，不写入 `needs_model_resolution.jsonl`，避免模型凭经验生成不存在的 pin。

### script/build_model_resolution_tasks.py

根据 `analysis_context_groups.json` 和 `needs_model_resolution.jsonl` 生成隔离 subagent 任务包：

```text
intermediate/model_resolution_tasks/
├── manifest.json
├── subagent_task_plan.md
├── subagent_task_plan.json
└── tasks/
    ├── TASK_01_SROC_302078562_MULTI_LINK_61889c68782d.json
    └── TASK_01_SROC_302078562_MULTI_LINK_61889c68782d.prompt.md
```

任务包包含：

```text
1. context_group
2. diagram_link_context
3. link_family_profiles
4. matched_rule_sections
5. link_family_summary / link_family_summaries
6. normalized_connections
7. candidate_mappings
8. source_device_pins
9. natural_language_rules
10. needs_model_resolution
11. required_output
```

`diagram_link_context` 是从输入框图表/link_info/链路信息 sheet 和逐行连接事实整理出的链路上下文，包含：

```text
group_link_family_ids
group_link_instance_ids
group_user_link_infos
group_device_role_infos
group_link_contexts
line_link_contexts
```

subagent 必须先读它，用来判断链路归属、器件角色、实例编号和特殊连接方式。

`link_family_profiles` 是同一 link_family 跨 source_device subagent 共享的链路级上下文，包含：

```text
link_family_id
context_group_ids
source_device_signatures
target_device_signatures
mapping_families
link_instance_ids
member_sheets
user_link_infos
device_role_infos
line_examples
shared_semantic_hints
```

它解决“链路逻辑如何给其他链路/其他器件 subagent 借鉴”的问题：同一 link_family 下的 subagent 可以共享链路拓扑、方向、实例索引、差分/总线展开规律和用户说明。它不是规则裁决结果，不能直接复制其他 line_id 或其他源端器件的 selected_pin。

`matched_rule_sections` 是从 `rules/natural_language_mapping_rules_template.md` 的 `### RULE:` 块中召回的候选规则文本。召回只基于源端器件、链路族、信号族、目标上下文、端口关键词等做相关性筛选，不做 pin 裁决。

启动 subagent 前应先读 `subagent_task_plan.md`，确认每个 context group 的源端器件、组内链路族、目标上下文和 line 数量。不要再按链路族/信号族/目标上下文把同一个源端器件任务拆开。

任务 JSON/prompt 使用可读文件名，而不是裸 `CTX_xxx`：

```text
TASK_序号_器件类型_源端器件编码_链路范围_contextHash.json
```

例如：

```text
TASK_01_91FBSW_47140609-001_FEEDBACK_CHAIN_d15a7250e9f7.json
TASK_02_SROC_302078562_MULTI_LINK_61889c68782d.json
TASK_03_TXVGA_47151290_RF_TX_CHAIN_98e63e8c1e3a.json
```

### script/merge_decisions.py

合并多来源裁决：

```text
1. pre_resolved_decisions.jsonl
2. model_resolved_decisions.jsonl
3. manual_override_decisions.jsonl
```

后出现的文件可覆盖前面的同 line_id 结果。

### script/validate_mapping.py

校验合并后的 `mapping_decisions.jsonl`。

核心校验：

```text
1. 每个 normalized_connection 都有 decision。
2. 不存在多余 line_id。
3. line_id 不重复。
4. selected_pin / selected_pins 必须存在于源端 pin 列表。
5. selected_pin / selected_pins 必须属于当前 line_id 的源端器件编码对应的 pin 列表，而不是仅仅存在于任意器件 pin 列表。
6. confidence 合法。
7. 有 pin 时应有 net_name 或可生成网络名。
8. 无 pin 时不得 High。
```

### script/render_template_sheets.py

正式 Excel 渲染脚本。

职责：

```text
1. 复制输入 workbook 的 sheet 结构和顺序。
2. block_info 原样保留。
3. link_info / 链路信息 原样保留。
4. 连接 sheet 清空后重建为标准 13 列。
5. 根据 selected_pins 展开多物理 pin 行。
6. 展开时只有连线ID和后 4 列可变化，前 8 列保持输入事实不变。
```

多物理 pin 展开规则：

```text
输入 line_id: 1868
selected_pins: ["PIN_P", "PIN_N"]
输出连线ID: 1868#1, 1868#2
```

### script/render_outputs.py

调试用平铺输出。正式信号接口列表应使用 `render_template_sheets.py`。

### script/generate_net_name.py

网络命名生成器。渲染阶段用于补齐或规范化网络命名。

### script/run_pipeline.py

统一阶段调度入口。

## 5. prompts 目录

### prompts/semantic_mapping_resolver.md

真实语义分析 prompt。subagent 必须按此规则分析：

```text
1. 先看 link_family_id、link_family_source、analysis_strategy。
2. 显式链路族优先理解全局链路。
3. 无链路级数据时，按器件上下文和 mapping_family 兜底。
4. 再用器件级规则和通用信号规则。
5. 最后才参考 pin 名称相似度。
6. 信息不足输出 unresolved。
```

### prompts/context_group_subagent_instruction.md

说明性 prompt，描述 `TASK_xxx.prompt.md` 的结构和 subagent 任务输入输出。真实任务以自动生成的 prompt 为准。

## 6. rules 目录

### rules/natural_language_mapping_rules_template.md

用户维护自然语言规则的主要入口。分四层：

```text
0. 链路族规则
1. 链路级规则
2. 器件级规则
3. 通用信号规则
```

该文件直接进入 subagent 上下文，不编译成固定 JSON 模板。

### rules/rule_layers.md

说明整体规则优先级。

### rules/context_isolation_rules.md

说明 context group 隔离原则，避免不同器件/链路语义互相污染。

### rules/template_gate_rules.md

现为“预裁决 Gate 规则”。定义脚本预裁决边界和必须进入模型分析的情况。

### rules/global_mapping_rules.md

通用硬件映射原则。

### rules/validation_rules.md

校验阶段原则。

### rules/net_naming_rules.md

网络命名原则。

## 7. schemas 目录

### schemas/normalized_connection.schema.json

标准化连接行结构。它是后续所有阶段的事实源。

关键字段：

```text
line_id
base_line_id
source_sheet_name
output_sheet_name
source_part_id
target_part_id
source_block_id/source_block_name/source_port
target_block_id/target_block_name/target_port
connection_id/base_connection_id/connection_name/direction
link_family_id/link_instance_id/link_contexts
```

### schemas/candidate_mapping.schema.json

候选 pin 结构，包含 `available_pins` 和 `candidates`。

### schemas/analysis_context_group.schema.json

模型上下文分组结构，包含 `link_family_source`、器件签名、映射族、line_ids 和推荐 subagent。

### schemas/mapping_decision.schema.json

模型/脚本/人工裁决结构。

支持：

```text
selected_pin: 单 pin
selected_pins: 多物理 pin
net_name: 单网络名
net_names: 多网络名
analyses/confidences: 多物理 pin 的逐项说明
```

### schemas/final_mapping_row.schema.json

最终 13 列输出行结构。

## 8. workflows 目录

### workflows/main_pipeline.md

主流程的阶段职责说明。

### workflows/context_isolation_workflow.md

subagent 上下文隔离规则说明。

### workflows/mapping_unit_workflow.md

单条连接在 context group 内如何被语义分析。

## 9. 中间产物

典型任务目录：

```text
task_dir/
├── intermediate/
│   ├── normalized_connections.jsonl
│   ├── analysis_context_groups.json
│   ├── candidate_mappings.jsonl
│   ├── pre_resolved_decisions.jsonl
│   ├── needs_model_resolution.jsonl
│   ├── model_resolved_decisions.jsonl
│   ├── manual_override_decisions.jsonl
│   ├── mapping_decisions.jsonl
│   ├── validation_report.json
│   └── model_resolution_tasks/
│       ├── manifest.json
│       ├── subagent_task_plan.md
│       ├── subagent_task_plan.json
│       └── tasks/
│           ├── TASK_xxx.json
│           └── TASK_xxx.prompt.md
└── output/
    └── signal_interface.xlsx
```

## 10. 扩展方式

### 增加器件/链路规则

优先编辑：

```text
rules/natural_language_mapping_rules_template.md
```

不要把器件特殊语义写入 Python 脚本。

### 增加新的链路信息

在输入 Excel 增加 `link_info` 或 `链路信息` sheet。最小推荐字段：

```text
链路类型
链路编号
器件Sheet
用户标识的链路信息
器件角色说明
```

`相关连线ID` 可选。只有当一个 sheet 同时参与多条链路且端口/角色无法区分时，再用它做精确约束。

### 增加通用信号规则

写入：

```text
rules/natural_language_mapping_rules_template.md
```

例如 SPI 拆分、差分 P/N、多 bit 总线、电源域匹配等。

### 增加脚本能力

脚本只应增强：

```text
1. 输入解析。
2. 数据结构补齐。
3. 候选生成。
4. context group 隔离。
5. 合并、校验、渲染。
```

不要把灵活硬件语义固化到脚本里。

## 11. 已清理的旧结构

当前主流程已经不再使用：

```text
runtime template
candidate_resolver prompt
hard_case_resolver prompt
apply_templates.py
group_units.py
render_paged_outputs.py
run_prepare.py / run_model_tasks.py / run_finish.py
```

对应能力已经收敛到：

```text
script/run_pipeline.py
script/pre_resolve_candidates.py
script/build_model_resolution_tasks.py
prompts/semantic_mapping_resolver.md
script/render_template_sheets.py
```
