# 器件类型上下文隔离规则

## 1. 强约束

1. 不同源端器件类型签名不得放入同一个模型分析上下文。
2. 不同对端器件信息或对端上下文签名不得放入同一个模型分析上下文。
3. 不同映射族不得放入同一个语义分析上下文。
4. 主业务重复链路必须标记 link_family_id，subagent 先按链路族理解全局语义，再复用器件类型局部规则。
5. 同类型不同实例可以共享一个 subagent，用于语义映射分析。
6. 疑难连接必须进入 semantic-hard-case-subagent 单独分析。
7. subagent 的隔离只影响模型分析上下文，不影响最终输出分页。
8. 最终输出分页仍然严格按照输入 Excel 原始 sheet。

## 2. 隔离优先级

```text
hard_case
  > link_family_id
  > mapping_family
  > source_device_signature + target_device_signature
  > device_category 兜底
```

如果一个 line_id 被标记为 hard_case，应从普通 context_group 中剥离，进入 semantic-hard-case-subagent。

器件类型签名直接使用 block_info 中的器件信息，不再根据框图标识、sheet 名或 block 名称推断器件类型。例如：

```text
txvga0 / txvga1 在 block_info 中都对应 47151290 -> DEVICE_INFO:47151290
91fbsw0 / 91fbsw1 在 block_info 中都对应 47140609-001 -> DEVICE_INFO:47140609-001
源端 block_info 缺失时 -> UNKNOWN_SOURCE_DEVICE_INFO
目的端 block_info 缺失时 -> TARGET_CONTEXT:<目的Block名称/标识>
```

源Block名称、目的Block名称、源Port、目的Port 只用于模型语义分析。目的端不在 block_info 中时，目的Block名称/标识只作为上下文隔离签名，不作为器件类型或 pin catalog key。

链路族优先规则：

```text
1. 当多个连接实例具有相同或高度相似的器件序列、端口序列、方向和拓扑时，必须构建 link_family_id。
2. 对重复链路，不得简单按器件类型孤立分析。
3. 重复链路应先由 semantic-mapping-subagent 理解代表链路的整体功能、方向、索引和 P/N 传播。
4. 器件类型局部规则只能在链路族语义约束下使用。
5. 若某条连接与链路族模式不一致，应从普通语义分析中标记为 hard case 或 unresolved。
6. link_family_id 只影响分析上下文，不影响最终输出分页。
```

## 3. 推荐 subagent

| 类型 | 说明 |
|---|---|
| semantic-mapping-subagent | 在同一隔离上下文内做语义映射分析 |
| semantic-hard-case-subagent | 处理无候选、冲突、校验失败等疑难项 |

## 4. 禁止行为

1. 禁止将不同源端器件类型签名混在同一个模型上下文中。
2. 禁止将不同对端器件信息或对端上下文签名混在同一个模型上下文中。
3. 禁止将 RF_CHAIN / CLOCK_TREE / SPI_CTRL / POWER_ENABLE 等不同映射族混在同一个语义分析上下文中。
4. 禁止使用 context_group_id 作为输出 sheet 名。
5. 禁止让 subagent 修改 output_sheet_name。
6. 禁止让 subagent 输出不属于当前 context_group 的 line_id。
