# 预裁决 Gate 规则

本文件定义脚本预裁决的边界。当前 skill 不再使用运行时模板；复杂硬件语义统一交给 `prompts/semantic_mapping_resolver.md` 对应的隔离 subagent。

## 可以脚本预裁决的情况

```text
1. source_part_id 能在 pin_info.json 中找到 pin 列表。
2. 候选 pin 分数足够高。
3. 第一候选与第二候选差距足够大。
4. 该裁决不依赖链路族、器件特殊规则、差分/总线展开语义或用户自然语言规则。
```

当前实现位于 `script/pre_resolve_candidates.py`：

```text
top_score >= 0.92
top_score - second_score >= 0.20
```

满足条件时输出 `project_rule_applied`，置信度为 `Medium`，并建议模型抽查。

## 必须进入模型分析的情况

```text
1. 没有候选 pin。
2. 多个候选分数接近。
3. 需要理解链路级规则、器件级规则或通用信号规则。
4. 需要判断差分 P/N、多物理 pin、总线位、片选、方向或上下游功能。
5. 当前连接含有多个 link_contexts，归属链路需要语义判断。
6. 校验阶段发现 selected_pin 不在 pin_info 中、置信度非法或输出不完整。
```

这些情况写入 `needs_model_resolution.jsonl`，由 `build_model_resolution_tasks.py` 切分为隔离 subagent 任务。

## 禁止行为

```text
1. 禁止在脚本预裁决中固化器件特殊语义。
2. 禁止把自然语言规则编译成硬编码模板。
3. 禁止脚本改写 normalized_connection 的前 9 列连接事实。
4. 禁止脚本自行新增 line_id；多物理 pin 应由模型输出 selected_pins，渲染阶段再展开。
```
