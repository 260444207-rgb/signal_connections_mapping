# 规则分层

## 主规则层级

```text
L0 用户当前明确说明
L1 rules/natural_language_mapping_rules_template.md 中的项目/器件语义规则
L2 通用硬件语义规则 rules/global_mapping_rules.md
L3 pin_info.json 中的源端器件 pin 列表
```

优先级：`用户当前明确说明 > 自然语言项目规则 > 通用硬件语义 > pin 列表约束`。

## 关键原则

1. 自然语言规则优先作为模型语义分析上下文，不强制编译为机器 JSON。
2. 脚本只能做事实整理、pin_info 门禁、模型任务隔离、校验和渲染。
3. 复杂硬件语义由隔离 subagent 根据源端/目的端器件、pin 列表、连接方向和自然语言规则判断。
4. 信息不足时必须输出 `unresolved`，不得为了填满表格硬猜。
