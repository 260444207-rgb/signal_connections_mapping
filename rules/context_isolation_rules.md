# 源端器件上下文隔离规则

## 1. 核心定义

```text
context_group = 同一个源端器件 pin 体系下的一组待分析连接
```

最终 `selected_pin` 是从源端器件 pin 列表里选择的，所以 context_group 的硬边界必须围绕源端器件，而不是围绕链路族、目标器件或信号族。

## 2. 硬分组维度

只使用以下字段做硬分组：

```text
source_device_signature
isolation_level
```

规则：

```text
1. source_part_id 存在时，source_device_signature = DEVICE_INFO:<source_part_id>。
2. 同一料号的不同实例必须放在同一个普通 context_group 中，例如 txvga0/txvga1/txvga2。
3. source_part_id 缺失时，使用 UNKNOWN_SOURCE:<sheet/block> 隔离未知源端，避免所有未知器件混在一起。
4. hard_case 必须单独隔离，不与普通连接混组。
```

## 3. 组内上下文

以下信息只作为组内上下文，不参与硬切分：

```text
link_family_ids
link_family_sources
mapping_families
target_device_signatures
link_contexts
link_instance_ids
user_link_infos
device_role_infos
source_device_instances
target_device_instances
```

含义：

```text
1. link_family_ids 告诉 subagent 当前源端器件参与了哪些链路族。
2. mapping_families 告诉 subagent 当前源端器件下有哪些信号族。
3. target_device_signatures 告诉 subagent 当前源端器件连接到了哪些目标上下文。
4. link_contexts / user_link_infos / device_role_infos 提供用户标注的链路语义。
```

这些字段帮助 subagent 逐条判断连接作用，但不能导致重新起一个 subagent。

## 4. 分析原则

```text
1. subagent 先理解当前 source_device_signature 的 pin 列表和器件级 pin 功能。
2. 再阅读组内 link_family_ids、mapping_families、target_device_signatures 和 link_contexts。
3. 对每条 line_id，结合当前连接的源/目的端口、方向、网络名、链路上下文独立判断。
4. 同类型不同实例可以共享 pin 功能理解，但不能共享实例编号、网络名或链路归属结论。
5. 信息不足时输出 unresolved，不得硬猜。
```

## 5. 禁止行为

```text
1. 禁止将不同 source_device_signature 的普通连接放入同一个 context_group。
2. 禁止因为 link_family_id 不同而把同一个源端器件拆成多个普通 subagent。
3. 禁止因为 target_device_signature 不同而把同一个源端器件拆成多个普通 subagent。
4. 禁止因为 mapping_family 不同而把同一个源端器件拆成多个普通 subagent。
5. 禁止使用 context_group_id、link_family_id、mapping_family 生成输出 sheet。
6. 禁止让 subagent 修改 output_sheet_name/source_sheet_name 或前 9 列连接事实。
7. 禁止让 subagent 输出不属于当前 context_group 的 line_id。
```

## 6. 推荐 subagent

| 类型 | 说明 |
|---|---|
| semantic-mapping-subagent | 分析同一源端器件 pin 体系下的普通连接 |
| semantic-hard-case-subagent | 处理无候选、冲突、校验失败等疑难项 |
