# Prompt：疑难映射分析器

适用情况：无候选 Pin、用户规则和自动模板冲突、Pin 功能文本缺失、方向与命名冲突、总线/差分关系不清楚、校验失败后需要重新分析。

输出：
```json
{
  "line_id": "",
  "selected_pin": "",
  "decision_type": "hard_case_resolved|unresolved",
  "confidence": "Medium|Low",
  "analysis": "",
  "net_name": "",
  "needs_human_review": true
}
```
