---
name: pipeline-schematic-generate
description: |
  板级原理图编排器。根据框图自动生成信号接口列表，再生成原理图并应用到天枢平台。
  当用户要求“从框图到原理图”“一站式原理图生成”“生成信号接口列表”“应用天枢”，
  或需要端到端完成框图→信号接口→原理图→应用天枢时触发。
  任何绕过本编排器直接组装调用原子 skill 的行为均违规。
---

##Goal

从框图到信号接口到原理图到应用天枢的端到端板级原理图生成编排器，按6Phase流程编排15个原子Skill，支持意图解析、场景选择、依赖解析、门控确认和管线总结。

##CoreConcepts

###PipelineSteps

| StepID | Phase  | Sub-Skill                              | Deliverable                     | ExecutionMode                                                |
| ------ | ------ | -------------------------------------- | ------------------------------- | ------------------------------------------------------------ |
| A1     | PhaseA | diagram-data-fetcher                   | 框图数据Excel                   | 主Agent,Skilltool,serial                                     |
| A2     | PhaseA | diagram-object-aggregator              | 框图聚合表格(BLOCK_INFO)        | 主Agent,Skilltool,serial,dependsonA1                         |
| A3     | PhaseA | symbol-pin-fetcher                     | 器件信息pin_info.json           | 主Agent,Skilltool,serial                                     |
| A4     | PhaseA | diagram-logical-connection-mapping     | 信号接口Excel(13列)             | 多阶段:prepare/model_tasks主Agent串行+语义subagent1:1perblock,max2parallel |
| A5     | PhaseA | diagram-signal-net-consistency-checker | 修正信号接口                    | 主Agent,Skilltool,serial                                     |
| C1     | PhaseC | signal-interface-fetcher               | BLOCK_INFOJSON                  | 主Agent,Skilltool,serial                                     |
| C2     | PhaseC | schematic-corpus-api-fetcher           | 语料JSONperblock                | 主Agent,Skilltool,serial                                     |
| C3     | PhaseC | schematic-single-gen                   | {block}_tianshu.jsonperblock    | Subagent1:1perblock,max2parallel                             |
| D1     | PhaseD | schematic-topblock-summary             | topblock_summary_net.json       | 主Agent,Skilltool,serial                                     |
| D2     | PhaseD | tianshu-batch-apply                    | 应用天枢URL+projectId           | 主Agent,Skilltool,serial                                     |
| D3     | PhaseD | task-compliance-checker                | 合规报告(PASS/PARTIAL/FAIL)     | 主Agent,Skilltool,serial                                     |
| D4     | PhaseD | tianshu-drc-review                     | DRC结果(drc_rate,drc_info_list) | 主Agent,Skilltool,serial                                     |

###DependencyGraph

```
PhaseA(信号接口生成):
A1→A2→A3→A4[prepare|model_tasks|subagents|finish]→A5→gate:signal_confirm

PhaseC(原理图生成):
C1→C2→C3[subagentperblock]→gate:schematic_confirm

PhaseD(应用天枢):
D1→D2→D3→D4
```

| Step | HardDependencies          | SoftDependencies                          | ExecutionOrder |
| ---- | ------------------------- | ----------------------------------------- | -------------- |
| A2   | A1(框图数据)              | —                                         | AfterA1        |
| A4   | A3(pin_info),A2(连接数据) | diagram-signal-net-naming(withinsubagent) | AfterA3        |
| A5   | A4(信号接口)              | —                                         | AfterA4        |
| C2   | C1(BLOCK_INFO)            | —                                         | AfterC1        |
| C3   | C2(语料),C1(BLOCK_INFO)   | —                                         | AfterC2        |
| D2   | D1(topblock_summary)      | D3(合规,post-deploy)                      | AfterD1        |

###PresetScenarios

| ScenarioID       | Name       | Phases | Description                          |
| ---------------- | ---------- | ------ | ------------------------------------ |
| `FULL`           | 全流程     | A→C→D  | 框图→信号接口→原理图→应用天枢        |
| `SIGNAL_ONLY`    | 仅信号接口 | A      | 从框图生成信号接口列表，不生成原理图 |
| `SCHEMATIC_ONLY` | 仅原理图   | C→D    | 从已有signal_interface*.xlsx开始     |
| `TIANSHU_ONLY`   | 仅应用天枢 | D      | 从已有schematicJSON开始              |

**场景跳过条件（仅当用户在上下文中明确提供了文件路径时才可跳过）：**

| 用户明确提供的输入 | 起始Phase    | 说明                             |
| ------------------ | ------------ | -------------------------------- |
| 框图工程ID         | PhaseAStepA1 | 从头开始                         |
| 框图聚合表格路径   | PhaseAStepA3 | 用户明确给出路径，跳过A1-A2      |
| 信号接口列表路径   | PhaseC       | 用户明确给出路径，跳过整个PhaseA |
| 原理图JSON路径     | PhaseD       | 用户明确给出路径，跳过PhaseA+C   |

##Rules

-**MUST**调用AskUserQuestion工具停等用户提供必要输入（框图来源URL/ID、天枢工程URL、工号），不得自动继续
-**MUST**生成DESIGN.md并等待用户确认（门控），不得跳过
-**MUST**使用uuid工作目录`data/{uuid}/`，不得复用旧任务目录
-**MUST**每个block独立拉起subagent，严禁合并作业
-**MUST**每批最多2个subagent并行，等待当前批次完成后再启动下一批
-**MUST**subagent超时1200秒（20分钟）
-**MUST**为每个subagent指定描述性label
-**MUST**发射`---ORCHESTRATORCONTEXT---`结构化上下文块后再调用子skill（见参数传递机制）
-**MUST**单个subagent失败不影响其他subagent继续执行
-**MUST**用TASK_PLAN.md/TASK_SCHEMATIC_PLAN.md跟踪批次进度，不得跳过状态追踪
-**MUST**信号接口确认后才能进入原理图生成，原理图确认后才能进入应用天枢
-**NEVER**绕过本编排器直接调用原子skill
-**NEVER**跳过任何门控（设计确认、信号接口确认、原理图确认）
-**NEVER**使用`cd&&python`链式命令，所有脚本调用必须用绝对路径
-**NEVER**在编排器中修改子skill内部逻辑，只通过skill-contracts接口交互
-**NEVER**用Tasktool调用需要`question`交互的子skill（如schematic-single-gen），这类skill必须通过Skilltool在主Agent中调用或通过subagent调用（subagent可以使用question）
-**NEVER**主动搜索磁盘或历史项目寻找中间件来跳步骤——只有用户在上下文中明确提供了文件路径才可跳过对应Phase，否则必须重新生成

##StateIntegrityAnchors

在以下关键节点执行状态完整性锚点。锚点是阻塞式门禁，不是提示语：

1. 到达节点时，先以`anchor`声明不可漂移的目标，再以`observe`检查当前事实。
2. 只依据列出的`evidence`判定，不得以聊天中的完成声明代替文件证据。
3. 将`anchor_id`、证据绝对路径、检查结果和失败原因追加到`TASK_PLAN.md`。
4. 仅当全部检查项为PASS时继续；任一项FAIL立即HALT，修复后重新执行同一锚点。
5. 必须调用`scripts/sip_gate.py`执行SIP `anchor`/`observe`与确定性检查；禁止仅在聊天或`TASK_PLAN.md`中手写PASS。
6. Python环境必须安装`requirements-sip.txt`中的固定版本依赖；SIP不可导入、脚本异常或退出码非0均视为FAIL。
7. 所有路径使用绝对路径；每次调用都用`--result-json`保存机器可读结果，并检查进程退出码。

锚点结果格式：

```text
[STATE_INTEGRITY_ANCHOR]
anchor_id:{anchor_id}
status:PASS|FAIL
evidence:
-{absolute_path}:{check_result}
failure_codes:[...]
next_step:{next_step_or_HALT}
```

环境验证：

```powershell
{python_executable} -c "from sip import StateIntegrityProtocol; import openpyxl; print('SIP_READY')"
```

若失败，使用同一个Python解释器安装依赖后重试：

```powershell
{python_executable} -m pip install -r "{pipeline_schematic_skill_dir}\requirements-sip.txt"
```

##Phase0:IntentParsing

*Precondition:Userhasjusttriggeredthisskill.*

1.**解析用户意图**—从用户请求中检测关键词：

| KeywordPattern                   | HitScenario           | LiteralExample             |
| -------------------------------- | --------------------- | -------------------------- |
| 从框图到原理图/全流程/一站式     | `FULL`                | "从框图到原理图全流程"     |
| 信号接口/信号列表/端口映射       | `SIGNAL_ONLY`         | "生成信号接口列表"         |
| 生成原理图/从信号列表生成原理图  | `SCHEMATIC_ONLY`      | "从信号接口列表生成原理图" |
| 应用天枢/应用到天枢/部署         | `TIANSHU_ONLY`        | "部署到天枢"               |
| 仅含"原理图"或"框图"无法确定范围 | parse_failure→askuser | "帮我画原理图"             |

2.**提取用户提供的输入**—仅从用户上下文中提取明确提供的文件路径或参数，**不得主动搜索磁盘或历史项目寻找中间件**：
-用户明确提供了signal_interface.xlsx路径→可从PhaseC开始
-用户明确提供了schematicJSON路径→可从PhaseD开始
-上下文中无明确路径→必须从头生成，不得跳步

3.**获取缺失参数**—通过AskUserQuestion询问：
-框图来源（URL或hscope工程ID）——PhaseA需要
-天枢工程信息（URL或projectId）——PhaseD需要
-工号——PhaseD需要

4.**确认场景选择**—向用户展示解析结果，确认或调整：
```
question({
multiple:false,
question:"已解析到以下场景，请确认或调整：\n场景:{scenario}\n输入:{detected_inputs}",
options:[
{label:"确认，继续执行",description:"按解析场景执行"},
{label:"选择其他场景",description:"手动选择场景"}
]
})
```

**Successcriteria:**`scenario_id`确定；必要输入参数已获取；用户已确认。

##Phase1:EnvironmentCheck&DesignConfirmation

*Precondition:Phase0hasproduced`scenario_id`andrequiredinputs.*

###1.0EnvironmentCheck

检查所需子skill和API服务可用性：

| Phase  |                                           RequiredSub-Skills | RequiredAPI                |
| ------ | -----------------------------------------------------------: | -------------------------- |
| PhaseA | diagram-data-fetcher,diagram-object-aggregator,symbol-pin-fetcher,diagram-logical-connection-mapping,diagram-signal-net-consistency-checker | hscope,annotation_platform |
| PhaseC | signal-interface-fetcher,schematic-corpus-api-fetcher,schematic-single-gen | annotation_platform        |
| PhaseD | schematic-topblock-summary,tianshu-batch-apply,task-compliance-checker,tianshu-drc-review | tianshuAPI                 |

**Detectionmethod:**检查`<available_skills>`中对应skillname是否存在；尝试API接口连通性。

**Ifanyrequireddependencyismissing:**列出缺失项→HALT→告知用户补充配置后重新触发。

###1.1CreateWorkingDirectory

1.生成uuid
2.创建`data/{uuid}/`目录结构：
```
data/{uuid}/
├──design/#框图数据、信号接口
├──corpus/#语料JSON
├──schematic/#原理图JSON
│└──{block_marker}/#subagent工作空间
├──tianshu/#应用天枢
├──DESIGN.md#设计确认文档
├──TASK_PLAN.md#统一任务计划
└──drc_result.json#DRC结果
```

###1.2DesignConfirmationGate

1.读取DESIGN_TEMPLATE.md（若存在）
2.填写`data/{uuid}/DESIGN.md`（框图链接、场景ID、分页策略、Block定义等）
3.展示DESIGN.md核心内容
4.**停等用户确认**—AskUserQuestion，不得自动继续

**Successcriteria:**DESIGN.md已创建；用户已确认；uuid工作目录已创建。

##Phase2:SignalInterfaceGeneration(PhaseA)

*Precondition:`scenario_id`includesPhaseA;Phase1completed.*

###StepA1:FetchBlockDiagramData

```
---ORCHESTRATORCONTEXT---
scenario_id:{scenario_id}
current_phase:PhaseA
task_uuid:{uuid}
working_directory:data/{uuid}
input_files:
-{框图工程ID}:hscope框图工程ID
deliverable:框图数据Excelatdesign/框图数据_{timestamp}.xlsx
---ENDORCHESTRATORCONTEXT---
```

1.调用`diagram-data-fetcher`Skilltool
2.输出归档到`design/`目录

**Successcriteria:**`design/框图数据_*.xlsx`存在且非空。

###StepA2:AggregateBlockDiagramData

```
---ORCHESTRATORCONTEXT---
current_phase:PhaseA
task_uuid:{uuid}
working_directory:data/{uuid}
input_files:
-{框图数据Excelpath}:A1输出
deliverable:框图聚合表格atdesign/block_info_{timestamp}.xlsx
---ENDORCHESTRATORCONTEXT---
```

1.调用`diagram-object-aggregator`Skilltool
2.输出包含BLOCK_INFOsheet+每器件独立sheet

**Successcriteria:**`design/block_info_*.xlsx`存在；BLOCK_INFOsheet含≥1器件条目。

###StepA3:FetchPinInfo

```
---ORCHESTRATORCONTEXT---
current_phase:PhaseA
task_uuid:{uuid}
working_directory:data/{uuid}
input_files:
-{block_infoExcelpath}:A2输出，从中提取器件编码列表
deliverable:pin_info.jsonatdesign/pin_info.json
---ENDORCHESTRATORCONTEXT---
```

1.从BLOCK_INFO提取去重器件编码列表
2.调用`symbol-pin-fetcher`Skilltool
3.保存pin_info.json

**Successcriteria:**pin_info.json存在；每个器件编码有对应pin列表。

###StepA4:LogicalConnectionMapping

####AnchorA4Entry:A4输入完整性

在执行任何A4命令前声明：

```text
anchor_id:A4_INPUT_READY
anchor:A4只能使用已完成聚合的框图连接数据和与其器件编码完整对应的pin_info.json。
observe:检查A2框图聚合表格与A3 pin_info.json的存在性、可解析性、内容完整性和器件编码覆盖关系。
evidence:block_info_*.xlsx,pin_info.json
```

必须全部PASS：
-`block_info_*.xlsx`存在、非空且可读取，包含`BLOCK_INFO`sheet及至少一个连接sheet
-`BLOCK_INFO`至少含1条器件记录，并可提取非空的去重器件编码集合
-`pin_info.json`存在、非空、是合法JSON；每个器件编码对应非空pin列表
-从`BLOCK_INFO`提取的每个器件编码均在`pin_info.json`中有对应项，不允许缺失、空列表或以其他器件pin代替

任一项FAIL：写入`A4_INPUT_MISSING`或`A4_PIN_COVERAGE_INCOMPLETE`并HALT，不得启动`prepare`、`model_tasks`或subagent。

执行：

```powershell
{python_executable} "{pipeline_schematic_skill_dir}\scripts\sip_gate.py" --anchor-id A4_INPUT_READY --observation "A4 input block diagram aggregation and pin catalog are complete readable and cover every device part before semantic mapping" --block-info "{block_infoExcelpath}" --pin-info "{pin_info.jsonpath}" --task-plan-md "{working_directory}\TASK_PLAN.md" --result-json "{working_directory}\design\anchor_A4_INPUT_READY.json"
```

**多阶段执行流程：**

先把`{diagram_mapping_skill_dir}`解析为`diagram-logical-connection-mapping`Skill根目录的绝对路径。A4所有阶段必须调用`{python_executable} "{diagram_mapping_skill_dir}\scripts\run_pipeline.py" ...`，不得因当前目录位于`{working_directory}`而改用`.\scripts\run_pipeline.py`。禁止把该Skill的`scripts`复制到TASK_ROOT、`signal_interface`或`intermediate`；遇到`ModuleNotFoundError`时重新确认Skill绝对路径和Python解释器后重试原命令。

**A4-1:Prepare+ModelTasks（主Agent串行）**

```
---ORCHESTRATORCONTEXT---
current_phase:PhaseA
task_uuid:{uuid}
working_directory:data/{uuid}
input_files:
-{block_infoExcelpath}:连接数据
-{pin_info.jsonpath}:器件pin信息
deliverable:normalized_connections.jsonl+model_resolved_decisions.jsonl+subagent_task_plan
---ENDORCHESTRATORCONTEXT---
```

1.调用`diagram-logical-connection-mapping`Skilltool，使用绝对脚本路径执行`prepare`阶段
2.使用同一绝对脚本路径执行`model_tasks`阶段
3.读取生成的subagent_task_plan

**A4-2:SemanticSubagents（按映射族隔离，每批2个并行）**

####AnchorA4SemanticExecution:真实Subagent语义分析

所有语义subagent任务完成后、执行`finish`前声明：

```text
anchor_id:A4_REAL_SUBAGENT_ANALYSIS
anchor:A4语义裁决必须由隔离subagent分析完成；脚本只允许准备任务、校验、合并和渲染，不得生成脚本代替subagent作出语义裁决。
observe:检查任务计划、实际subagent启动方式、逐TASK输出及执行记录。
evidence:subagent_session_plan.json,subagent_task_plan.json,TASK_PLAN.md,subagent_outputs/*.jsonl
```

必须全部PASS：
-已读取`global_link_plan`、`subagent_session_plan`和`subagent_task_plan`
-按`subagent_session_plan`为每个source_device session实际启动独立subagent；同一session内的小TASK由同一subagent顺序分析
-`TASK_PLAN.md`逐session记录`execution_mode=subagent`、subagent label、TASK列表和完成状态
-不得使用`stage=all`充当正式语义分析，不得新建或运行脚本来替代subagent读取任务、选择pin或生成mapping decision
-每个TASK的结果由对应subagent写入其`output_contract.output_file`；仅有脚本生成结果或聊天文本视为FAIL

任一项FAIL：写入`A4_SUBAGENT_NOT_USED`或`A4_SCRIPT_SUBSTITUTED_ANALYSIS`并HALT；必须用真实subagent重新执行受影响session。

遍历`subagent_session_plan`中的每个source_device session，每个session启动独立subagent；同一session内的多个小TASK由该subagent按计划顺序处理并共享pin分配状态：
-每批最多2个并行
-`runTimeoutSeconds=1200`
-Subagentprompt必须包含完整工作上下文（规范化连接数据、pininfo、规则文件路径、output_file路径）
-Subagent必须将结果JSONL写入指定output_file

全部subagent完成后执行：

```powershell
{python_executable} "{pipeline_schematic_skill_dir}\scripts\sip_gate.py" --anchor-id A4_REAL_SUBAGENT_ANALYSIS --observation "A4 semantic mapping decisions are produced by isolated real subagents and never substituted by stage all or analysis scripts" --session-plan "{subagent_session_plan.jsonpath}" --task-plan-json "{subagent_task_plan.jsonpath}" --task-plan-md "{working_directory}\TASK_PLAN.md" --result-json "{working_directory}\design\anchor_A4_REAL_SUBAGENT_ANALYSIS.json"
```

**A4-3:Finish（主Agent串行）**

1.直接执行`signal_interface\intermediate\finish_command.txt`中生成的绝对路径命令，完成`finish`并渲染最终信号接口Excel；不得重组为TASK_ROOT下的相对脚本命令
2.输出`signal_interface_{timestamp}.xlsx`（标准13列）

####AnchorA4Finish:A4输出结构完整性

`finish`完成后、进入A5前声明：

```text
anchor_id:A4_OUTPUT_CONTRACT
anchor:最终信号接口表必须继承输入框图的分页和sheet顺序，保留信息页，并将每个连接sheet渲染为标准13列。
observe:对比输入聚合表格与signal_interface_*.xlsx的workbook结构、分页、列数和连接数据。
evidence:block_info_*.xlsx,signal_interface_*.xlsx,validation_report.json,subagent_output_check.json
```

必须全部PASS：
-输出Excel存在、非空且可读取；`validation_report.json`无ERROR
-输出sheet名称、顺序和分页结构与输入workbook一致，不得按model、group或context_group新增分页
-`BLOCK_INFO`原样保留；输入存在`link_info`/`链路信息`时也原样保留
-每个连接sheet恰好为标准13列且至少含1条连接；前9列连接事实除合法`line_id#数字`展开外不得改写
-`subagent_output_check.json`通过；所有TASK的line_id无缺失、重复或额外输出

任一项FAIL：写入`A4_OUTPUT_PAGINATION_INVALID`、`A4_OUTPUT_COLUMN_COUNT_INVALID`或相应失败码并HALT，不得进入A5。

执行：

```powershell
{python_executable} "{pipeline_schematic_skill_dir}\scripts\sip_gate.py" --anchor-id A4_OUTPUT_CONTRACT --observation "A4 final signal interface preserves workbook pagination sheet order information sheets and renders every connection sheet with 13 columns" --block-info "{block_infoExcelpath}" --signal-interface "{signal_interfaceExcelpath}" --validation-report "{validation_report.jsonpath}" --subagent-check "{subagent_output_check.jsonpath}" --task-plan-md "{working_directory}\TASK_PLAN.md" --result-json "{working_directory}\design\anchor_A4_OUTPUT_CONTRACT.json"
```

**Successcriteria:**锚点`A4_OUTPUT_CONTRACT=PASS`。

###StepA5:NetConsistencyCheck&Fix

```
---ORCHESTRATORCONTEXT---
current_phase:PhaseA
task_uuid:{uuid}
working_directory:data/{uuid}
input_files:
-{signal_interfaceExcelpath}:A4输出
deliverable:修正后的signal_interface_net_checked.xlsx+net_consistency_report.json
---ENDORCHESTRATORCONTEXT---
```

1.调用`diagram-signal-net-consistency-checker`Skilltool
2.先check-only，读取报告
3.若proposed_change_count>0→--fix→recheck
4.保存修正后的Excel和报告

**Successcriteria:**修正后的Excel存在；recheck报告中proposed_change_count=0或无ERROR。

###AnchorPhaseAExit:A5完成性

生成信号接口列表后、展示SignalInterfaceConfirmationGate前声明：

```text
anchor_id:PHASE_A_A5_COMPLETED
anchor:PhaseA只有在A5信号一致性检查完成并消除可修正问题后才算完成。
observe:检查A5调用记录、修正后Excel、首次报告和recheck报告。
evidence:signal_interface_net_checked.xlsx,net_consistency_report.json,TASK_PLAN.md
```

必须全部PASS：
-`TASK_PLAN.md`中A5状态为`completed`，且记录已调用`diagram-signal-net-consistency-checker`
-`signal_interface_net_checked.xlsx`存在、非空且可读取
-若首次check报告`proposed_change_count>0`，存在`--fix`及recheck证据
-最终recheck报告`proposed_change_count=0`且无ERROR

任一项FAIL：写入`PHASE_A_A5_NOT_RUN`或`PHASE_A_A5_INCOMPLETE`并HALT；不得宣称PhaseA完成，不得进入信号接口确认门控或PhaseC。

执行：

```powershell
{python_executable} "{pipeline_schematic_skill_dir}\scripts\sip_gate.py" --anchor-id PHASE_A_A5_COMPLETED --observation "Phase A completes only after A5 net consistency check fix and recheck produce a readable checked workbook with zero proposed changes and errors" --a5-excel "{signal_interface_net_checked.xlsxpath}" --a5-report "{net_consistency_recheck_report.jsonpath}" --task-plan-md "{working_directory}\TASK_PLAN.md" --result-json "{working_directory}\design\anchor_PHASE_A_A5_COMPLETED.json"
```

###SignalInterfaceConfirmationGate

展示信号接口列表摘要（block数量、连接数量、修正报告）→AskUserQuestion停等用户确认。

**若scenario_id=`SIGNAL_ONLY`：**管线到此结束，输出交付件并进入Phase5总结。

##Phase3:SchematicGeneration(PhaseC)

*Precondition:`scenario_id`includesPhaseC;Phase2completed(oruserprovidedsignal_interface*.xlsx).*

###StepC1:ReadSignalInterface

```
---ORCHESTRATORCONTEXT---
current_phase:PhaseC
task_uuid:{uuid}
working_directory:data/{uuid}
input_files:
-{signal_interfaceExcelpath}:信号接口列表
deliverable:BLOCK_INFOJSON+框图标志列表
---ENDORCHESTRATORCONTEXT---
```

1.调用`signal-interface-fetcher`Skilltool（block-info模式）
2.从BLOCK_INFO提取框图标志+器件编码映射

###StepC2:FetchCorpus

```
---ORCHESTRATORCONTEXT---
current_phase:PhaseC
task_uuid:{uuid}
working_directory:data/{uuid}
input_files:
-{器件编码列表}:从BLOCK_INFO去重提取
deliverable:corpus/{框图标志}_corpus.jsonperblock
---ENDORCHESTRATORCONTEXT---
```

1.调用`schematic-corpus-api-fetcher`Skilltool（detail模式）
2.输出归档到`corpus/`目录，每个框图标志独立JSON
3.生成`TASK_CORPUS_PLAN.md`跟踪语料获取状态

**执行检查：**corpus下JSON文件数量=BLOCK_INFO器件编码去重数量。获取失败的block不进入C3。

###StepC3:GenerateSchematics(SubagentperBlock)

遍历有语料的框图标志列表，生成`TASK_SCHEMATIC_PLAN.md`。

**Subagent并发控制规范：**
-分批启动，每批2个subagent并行
-等待当前批次全部完成后再启动下一批
-`runTimeoutSeconds=1200`

每个subagent启动时传递：

```
---ORCHESTRATORCONTEXT---
scenario_id:{scenario_id}
current_phase:PhaseC
task_uuid:{uuid}
working_directory:data/{uuid}
input_files:
-{corpus_json_path}:corpus/{框图标志}_corpus.json
-{signal_excel_path}:design/signal_interface_*.xlsx
deliverable:schematic/{框图标志}/{框图标志}_tianshu.json
---ENDORCHESTRATORCONTEXT---
```

**Subagent启动指令模板：**

```
你是原理图生成subagent，负责为框图【{框图标志}】生成单个原理图。

严格遵循schematic-single-genskill的完整工作流（Step0~7）执行。

输入：
-语料JSON：{corpus_json_path}
-信号接口Excel：{signal_excel_path}
-输出目录：{output_dir}
-框图标志：{框图标志}

输出格式：[SUBAGENT_RESULT]
{
"status":"completed/failed",
"output_file":"{框图标志}_tianshu.json的绝对路径",
"has_diagram":true/false,
"error":"错误信息（仅failed时）"
}
```

**主会话收集每个subagent结果：**
-更新`TASK_SCHEMATIC_PLAN.md`对应框图标志状态
-检查生成的`*_tianshu.json`是否包含`"diagram"`字段
-**某个subagent失败不影响其他继续执行**

**执行检查：**schematic中子任务数量及tianshu.json数量与BLOCK_INFO框图标志数量及名称一致。

###SchematicConfirmationGate

展示原理图生成结果摘要（成功/失败block数、文件列表）→AskUserQuestion停等用户确认。

##Phase4:TianShuDeployment(PhaseD)

*Precondition:`scenario_id`includesPhaseD;Phase3completed(oruserprovidedschematicJSONs).*

###StepD1:TopblockSummary

1.清空`tianshu/`目录
2.从`schematic/`目录拷贝所有`*_tianshu.json`到`tianshu/`，去除`_tianshu`后缀保留`.json`
3.调用`schematic-topblock-summary`Skilltool生成`topblock_summary_net.json`

```
---ORCHESTRATORCONTEXT---
current_phase:PhaseD
task_uuid:{uuid}
working_directory:data/{uuid}
input_files:
-{tianshudirpath}:包含所有tianshu.json的目录
-{signal_interfaceExcelpath}:含BLOCK_INFO的信号接口Excel（可选）
deliverable:topblock_summary_net.jsonattianshu/
---ENDORCHESTRATORCONTEXT---
```

**执行检查：**索引文件page里的block能完全对应block字段；component数量和tianshu目录JSON文件数量一致。

**Successcriteria:**`tianshu/topblock_summary_net.json`存在且结构完整。

###StepD2:BatchApplytoTianShu

```
---ORCHESTRATORCONTEXT---
current_phase:PhaseD
task_uuid:{uuid}
working_directory:data/{uuid}
input_files:
-{tianshudirpath}:包含tianshu.json+topblock_summary_net.json
deliverable:应用天枢URL+projectId
---ENDORCHESTRATORCONTEXT---
```

1.调用`tianshu-batch-apply`Skilltool
2.记录返回的projectId和URL

**Successcriteria:**返回status=success；projectId非空。

**执行检查：**查询天枢工程具备和索引文件一致的图页。

###StepD3:ComplianceCheck

```
---ORCHESTRATORCONTEXT---
current_phase:PhaseD
task_uuid:{uuid}
working_directory:data/{uuid}
input_files:
-{task_dir}:data/{uuid}
deliverable:compliance_report(PASS/PARTIAL/FAIL)
---ENDORCHESTRATORCONTEXT---
```

1.调用`task-compliance-checker`Skilltool
2.若有**ERROR**→定位问题→修复→重新检查
3.若仅有**WARNING/PASS**→继续

**Successcriteria:**overall_status≠FAIL（PASS或PARTIAL可继续）。

###StepD4:DRCReview

```
---ORCHESTRATORCONTEXT---
current_phase:PhaseD
task_uuid:{uuid}
working_directory:data/{uuid}
input_files:
-{projectId}:D2返回的天枢工程ID
-{user_name}:用户工号
deliverable:drc_result.jsonatdata/{uuid}/drc_result.json
---ENDORCHESTRATORCONTEXT---
```

1.调用`tianshu-drc-review`Skilltool
2.保存drc_result.json

**Successcriteria:**drc_result.json存在；包含`code`,`drc_rate`,`drc_info_list`字段。

##Phase5:PipelineSummary

输出结构化报告：

```
===原理图编排完成===
场景:{scenario_id}
工作目录:data/{uuid}/

执行结果:
-PhaseA(信号接口):{completed/skipped/failed}
-Block数量:{total_blocks}
-成功:{completed_blocks},失败:{failed_blocks},跳过:{skipped_blocks}
-PhaseC(原理图生成):{completed/skipped/failed}
-生成原理图:{schematic_count}
-成功:{completed_blocks},失败:{failed_blocks}
-PhaseD(应用天枢):{completed/skipped/failed}
-天枢工程URL:{tianshu_url}
-DRC通过率:{drc_rate}
-合规状态:{compliance_status}

交付件:
-DESIGN.md:{path}
-signal_interface*.xlsx:{path}
-schematic/*.json:{count}files
-topblock_summary_net.json:{path}
-drc_result.json:{path}
-合规报告:{path}

错误分析:
{error_summary}
```

**若所有步骤均被跳过（全使用已有文件）：**输出"所有交付件已存在，无需重新生成"并退出。

##ErrorHandling

| FailedStep                    | Impact            | Handling                          |
| ----------------------------- | ----------------- | --------------------------------- |
| A1(diagram-data-fetcher)      | PhaseA阻塞        | HALT→请用户提供正确框图ID         |
| A2(diagram-object-aggregator) | PhaseA阻塞        | 重试同输入；仍失败则HALT          |
| A3(symbol-pin-fetcher)        | A4缺pin_info      | 通知用户→HALT                     |
| A4subagent(单个block映射)     | 该block映射失败   | 标记failed，其他block继续         |
| A5(net-consistency-checker)   | 信号接口未修正    | --fix重试；仍失败→通知用户决定    |
| C2(corpus-fetcher)            | 部分block无语料   | 无语料block不进入C3，记录原因     |
| C3subagent(单个block原理图)   | 该block原理图缺失 | 标记failed，排除出PhaseD          |
| D1(topblock-summary)          | PhaseD阻塞        | HALT→检查tianshu目录完整性        |
| D2(tianshu-batch-apply)       | 部署阻塞          | 重试；仍失败→检查索引文件         |
| D3合规ERROR                   | 规范违规          | 定位问题→修复→重新检查            |
| D4(drc-review)                | DRC结果不可用     | 报告用户；管线完成，DRC为补充信息 |
| Subagent超时(1200s)           | 单个block超时     | 标记failed，继续其他              |
| API服务不可用                 | 步骤阻塞          | HALT→通知用户检查服务             |

##SubagentBatchControl

| 属性     | 值                                           |
| -------- | -------------------------------------------- |
| 批次大小 | 每批最多2个并行                              |
| 超时     | 1200秒（20分钟）                             |
| 处理单元 | 1subagent=1block                             |
| 隔离机制 | 每个subagent独立上下文，避免分析结果互相污染 |
| label    | 必须指定描述性label                          |

**状态追踪文件：**
-`TASK_CORPUS_PLAN.md`—语料获取计划（pending→completed/failed）
-`TASK_SCHEMATIC_PLAN.md`—原理图生成计划（pending→in_progress→completed/failed）
-`TASK_PLAN.md`—统一任务计划（合并上述状态）

**主会话职责：**
1.启动批次→等待全部完成→收集结果→更新计划文件→启动下一批次
2.检查subagent输出是否满足交付件要求（tianshu.json含`"diagram"`字段）
3.失败subagent的block不影响后续批次

##MandatoryGates

| Gate         | Trigger    | RequiredAction                                    |
| ------------ | ---------- | ------------------------------------------------- |
| 设计确认     | Phase1     | 生成DESIGN.md→AskUserQuestion停等用户确认         |
| 信号接口确认 | Phase2结束 | 展示signal_interface.xlsx摘要→AskUserQuestion停等 |
| 原理图确认   | Phase3结束 | 展示原理图生成结果→AskUserQuestion停等            |

**confirm_mode：**
-`manual`（默认）—每个门控停等用户
-`auto`—仅当用户明确要求时自动继续

##DirectoryStructure

```
data/{uuid}/
├──design/#框图数据、信号接口、修正报告
│├──框图数据_{ts}.xlsx
│├──block_info_{ts}.xlsx
│├──signal_interface_{ts}.xlsx
│├──signal_interface_net_checked.xlsx
│├──net_consistency_report.json
│├──anchor_A4_INPUT_READY.json
│├──anchor_A4_REAL_SUBAGENT_ANALYSIS.json
│├──anchor_A4_OUTPUT_CONTRACT.json
│├──anchor_PHASE_A_A5_COMPLETED.json
│└──intermediate/
├──corpus/#语料（每个框图独立JSON）
│└──{框图标志}_corpus.json
├──schematic/#生成的原理图JSON
│└──{框图标志}/#subagent工作空间
│├──input/
│├──scripts/
│├──{框图标志}_tianshu.json
│└──generate_result.json
├──tianshu/#应用天枢工作空间
│├──{框图标志}.json#去除_tianshu后缀
│└──topblock_summary_net.json
├──DESIGN.md#设计确认文档
├──TASK_PLAN.md#统一任务计划
├──TASK_CORPUS_PLAN.md#语料获取计划
├──TASK_SCHEMATIC_PLAN.md#原理图生成计划
└──drc_result.json#DRC结果
```

##Sub-SkillInterfaceContracts

完整接口定义（输入参数、输出格式、交付件流转）见[skill-contracts.md](references/skill-contracts.md)。
