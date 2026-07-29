# 单条连接语义分析流程

本文件说明 subagent 在一个 `context_group` 内如何分析单条连接。它不是独立脚本入口；真实执行入口是 `script/build_model_resolution_tasks.py` 导出的 `TASK_器件类型_器件编码_链路范围_hash.json` 任务包。

## 输入范围

单条连接分析需要同时读取：

```text
1. 当前 normalized_connection
2. source_device_pins 中该 source_part_id 的当前 pin 视图
3. pin_catalog_context；超过 100 个 pin 时可回退读取其他 groups 或 all_pins
4. context_group 的 link_family_id / link_family_source / analysis_strategy
5. session_context_file 中 sheet/物理实例和 pin 复用约束
6. diagram_link_context 中当前组级链路上下文
7. session_context_file 中 link_family_profiles 的共享语义
8. matched_rule_refs 指向 rule_library 的自然语言规则
```

## 判断顺序

先执行 pin_info 门禁：

```text
如果 source_device_pins 中没有当前 source_part_id，或列表为空：
  不进入链路/端口/规则分析
  不使用 source_port / target_port / connection_name 生成 pin
  直接输出 unresolved / Low / needs_human_review=true，selected_pin 和 net_name 为空
```

```text
确认源端器件类型和可用 pin（必须来自 source_device_pins）
  ↓
确认目的端器件/电路描述
  ↓
确认当前 source_sheet_name 对应的物理器件实例和同实例内其他连接
  ↓
判断是否有显式链路族或多个 link_contexts
  ↓
阅读同一 link_family 的共享 profile，借鉴拓扑/方向/实例规律
  ↓
理解当前连接在链路/器件上下文中的作用
  ↓
处理差分、总线、多物理 pin、片选、方向、索引
  ↓
在源端 pin 列表中选择承担同样作用的 pin
  ↓
输出 mapping_decision 或 unresolved
```

## 判断优先级

```text
用户当前明确说明
  > 链路族/链路级语义
  > 当前器件上下游
  > 器件级局部规则
  > 通用信号规则
  > pin 名称相似度
```

`link_family_profiles` 只提供共享语义，不提供最终 pin 结论。subagent 可以借鉴同一 link_family 下其他器件或实例的分析方式，但必须回到当前 source_device_pins 和当前 line_id 独立选择 pin。

selected_pin / selected_pins 必须逐字来自当前 source_part_id 对应的 source_device_pins。没有该 source_part_id 的 pin 列表或列表为空时，不分析该器件 pin，直接 unresolved；不得把框图端口名、连线名、规则里的信号名或器件常识写成 selected_pin。

同一个 physical_device_instance_id 内，同一个 selected_pin 默认只能给一个不同语义 line_id。只有同一网络、同一 base_connection、多端口别名或用户规则明确说明一个器件引脚给多个端口时，才允许复用。

## 输出

普通连接输出一个 decision。多物理 pin 优先输出多行 `parent_line_id#数字`；下面仅为旧数组兼容格式：

```json
{
  "line_id": "sheet:1:1868",
  "selected_pin": "",
  "selected_pins": ["PIN_P", "PIN_N"],
  "decision_type": "model_resolved",
  "confidence": "High",
  "analysis": "该逻辑连接对应差分 P/N 两个物理 pin。",
  "net_name": "",
  "net_names": [],
  "needs_human_review": false
}
```

模型不分析网络名，`net_name` / `net_names` 固定为空；渲染阶段统一生成。旧数组模式会由渲染阶段展开，并保证原始连接事实不变。

信息不足时：

```json
{
  "line_id": "sheet:1:1868",
  "selected_pin": "",
  "selected_pins": [],
  "decision_type": "unresolved",
  "confidence": "Low",
  "analysis": "缺少链路实例、总线编号或 pin 功能规则，无法唯一选择 pin。",
  "net_name": "",
  "net_names": [],
  "needs_human_review": true
}
```
