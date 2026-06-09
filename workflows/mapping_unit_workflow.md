# 单条映射语义分析流程

映射单元可以是一条连接、一个显式总线展开位、或同一 context group 中需要共同判断的一小组连接。

## 输入

```json
{
  "normalized_connection": {},
  "candidate_mapping": {
    "available_pins": [],
    "candidates": []
  },
  "natural_language_rules": "",
  "related_context": []
}
```

## 判断顺序

```text
理解源端器件
  ↓
理解目的端器件/电路描述
  ↓
判断信号作用
  ↓
在源端 pin 列表中找承担同样作用的 pin
  ↓
检查方向、差分/总线、通道编号
  ↓
输出 mapping_decision 或 unresolved
```

## 判断优先级

```text
用户当前明确说明
  > 自然语言项目/器件规则
  > 通用硬件语义规则
  > 源端 pin 列表约束
  > 候选相似度
```

## 输出

只输出 JSON：

```json
{
  "line_id": "L001",
  "selected_pin": "PIN_NAME",
  "decision_type": "model_resolved",
  "confidence": "High|Medium|Low",
  "analysis": "说明为什么该 pin 与信号作用一致。",
  "net_name": "NET_NAME",
  "needs_human_review": false
}
```

信息不足时：

```json
{
  "line_id": "L001",
  "selected_pin": "",
  "decision_type": "unresolved",
  "confidence": "Low",
  "analysis": "说明缺少哪些规则或上下文。",
  "net_name": "",
  "needs_human_review": true
}
```
