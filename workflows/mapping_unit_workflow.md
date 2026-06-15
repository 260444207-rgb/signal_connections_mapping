# 单条连接语义分析流程

本文件说明 subagent 在一个 `context_group` 内如何分析单条连接。它不是独立脚本入口；真实执行入口是 `script/build_model_resolution_tasks.py` 导出的 `CTX_xxx.json` 任务包。

## 输入范围

单条连接分析需要同时读取：

```text
1. 当前 normalized_connection
2. 当前 line_id 对应 candidate_mapping
3. source_device_pins 中该 source_part_id 的 pin 列表
4. context_group 的 link_family_id / link_family_source / analysis_strategy
5. link_family_summary 中同类链路的全局摘要
6. natural_language_mapping_rules_template.md 中的自然语言规则
```

## 判断顺序

```text
确认源端器件类型和可用 pin
  ↓
确认目的端器件/电路描述
  ↓
判断是否有显式链路族或多个 link_contexts
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

## 输出

单条逻辑连接输出一个 decision。多物理 pin 不新增 line_id，而是在同一个 decision 中输出数组：

```json
{
  "line_id": "sheet:1:1868",
  "selected_pin": "",
  "selected_pins": ["PIN_P", "PIN_N"],
  "decision_type": "model_resolved",
  "confidence": "High",
  "analysis": "该逻辑连接对应差分 P/N 两个物理 pin。",
  "net_name": "",
  "net_names": ["NET_P", "NET_N"],
  "needs_human_review": false
}
```

渲染阶段会把 `selected_pins` 展开为 `主连线ID#数字`，并保证除连线ID和后 4 列外，前 9 列连接事实不变。

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
