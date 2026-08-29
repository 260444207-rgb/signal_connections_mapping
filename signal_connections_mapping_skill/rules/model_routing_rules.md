# 模型路由 Gate 规则

本文件定义语义模型任务的 pin_info 门禁。脚本不生成候选 pin。唯一允许的确定性预裁决是：单 pin `source_port` 与当前器件 pin_info 逐字相同时直接同名连接；其余映射交给 `prompts/semantic_mapping_resolver.md` 对应的隔离 subagent。

## 进入模型分析

当前连接的 `source_part_id` 能在入参 `pin_info.json` 中找到非空 pin 列表时：

```text
1. pre_resolved_decisions.jsonl 写入 unresolved 占位结果。
2. needs_model_resolution.jsonl 写入该 line_id。
3. build_model_resolution_tasks.py 为该连接生成语义 TASK。
```

链路族、器件规则、差分/总线、片选、方向、上下游功能和 pin 分配均由语义模型结合完整 pin 列表判断。

如果单 pin `source_port` 已逐字存在于当前器件 pin_info，则直接写入 `pre_resolved_decisions.jsonl`，设置 `selected_pin=source_port`、`confidence=High`，且不写入 `needs_model_resolution.jsonl`。这属于身份映射事实，不属于脚本语义猜测。

## 跳过模型分析

如果 `pin_info.json` 中没有当前源端器件编码对应的 pin 列表或列表为空：

```text
1. 输出 unresolved / Low / needs_human_review=true。
2. selected_pin、selected_pins 保持为空；不输出网络命名字段。
3. 不写入 needs_model_resolution.jsonl。
4. 不创建 subagent/TASK，等待用户补充 pin 信息。
```

框图 port、连线名、规则文本和器件常识都不能替代 `pin_info.json`。

## 禁止行为

```text
1. 禁止脚本按名称相似度生成或排序候选 pin。
2. 除 `source_port` 与单 pin 逐字一致的身份映射外，禁止脚本自动预裁决 selected_pin。
3. 禁止脚本改写 normalized_connection 的前 10 列连接事实。
4. 禁止脚本或模型改写 pin_info.json 中的 pin 字符串。
5. 禁止在缺少源端器件 pin 列表时生成 selected_pin 或语义 TASK。
```
