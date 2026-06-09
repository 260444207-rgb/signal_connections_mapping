# 器件类型上下文隔离规则

## 1. 强约束

1. 不同器件种类不得放入同一个模型分析上下文。
2. 不同映射族不得放入同一个候选裁决上下文。
3. 同类器件可以共享一个 subagent，用于生成运行时模板。
4. 疑难连接必须进入 hard_case subagent 单独分析。
5. subagent 的隔离只影响模型分析上下文，不影响最终输出分页。
6. 最终输出分页仍然严格按照输入 Excel 原始 sheet。

## 2. 隔离优先级

```text
hard_case
  > mapping_family
  > device_category
  > structural_group
```

如果一个 line_id 被标记为 hard_case，应从普通 context_group 中剥离，进入 hard-case-subagent。

## 3. 推荐 subagent

| 类型 | 说明 |
|---|---|
| runtime-template-subagent | 为同一器件种类 / 映射族生成运行时模板 |
| candidate-resolver-subagent | 在同一隔离上下文内做候选裁决 |
| hard-case-subagent | 处理无候选、冲突、校验失败等疑难项 |

## 4. 禁止行为

1. 禁止将 PA / ADC / CLOCK / GPIO 等不同器件种类混在同一个模型上下文中。
2. 禁止将 RF_CHAIN / CLOCK_TREE / SPI_CTRL / POWER_ENABLE 等不同映射族混在同一个候选裁决上下文中。
3. 禁止使用 context_group_id 作为输出 sheet 名。
4. 禁止让 subagent 修改 output_sheet_name。
5. 禁止让 subagent 输出不属于当前 context_group 的 line_id。
