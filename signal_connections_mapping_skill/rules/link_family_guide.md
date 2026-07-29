# 链路族概念说明

链路族规则描述"重复出现的一类完整业务链路"。它不是最终输出分组，也不改变 Excel sheet；它只帮助模型先理解全局语义，再判断局部 pin。

## 什么时候使用链路族

- 如果多个连接实例具有相同或高度相似的器件序列、端口序列、方向和拓扑，应优先按链路族分析。
- 如果不存在明显重复链路，则按器件类型 / 映射族隔离分析。
- 如果是控制、时钟、电源、SPI 等信号，优先按映射族分析。
- 如果是 RF_TX_CHAIN、RF_RX_CHAIN、JESD_CHAIN 等主业务链路，优先按完整链路族分析。

## 输入表中的链路信息 sheet

用户可以在输入 Excel 中新增一个 `link_info` 或 `链路信息` sheet，用自然语言和少量字段标注链路族。

这个 sheet 是可选增强信息，不是必填输入。没有链路级数据、没有 `link_family` 时，模型仍必须根据 block_info 器件信息、源/目的 Block、端口名、连线名和 mapping_family 做器件级分析。

推荐表头：

```text
链路类型 | 链路编号 | 器件Sheet | 用户标识的链路信息 | 器件角色说明 | 相关连线ID
```

字段含义：

- 链路类型：同一类重复链路使用同一个值，例如 RF_TX_CHAIN、FEEDBACK_CHAIN、PA_CONTROL_CHAIN。
- 链路编号：一条具体链路实例，例如 RF_TX_CHAIN_00、RF_TX_CHAIN_01。
- 器件Sheet：这条链路涉及哪些器件 sheet，多个 sheet 用逗号、分号或顿号分隔。
- 用户标识的链路信息：用户对该链路的自然语言说明，例如方向、功能、通道、特殊连接方式。
- 器件角色说明：描述每个 sheet 在这条链路中的角色，例如 hbf0=TX输出合路; hbf0=RX输入入口。
- 相关连线ID：可选。需要精确约束时填写这条链路包含的连线ID，多个 ID 用逗号、分号或顿号分隔；也可以写成 sheet:连线ID。

示例：

```text
RF_TX_CHAIN | RF_TX_CHAIN_00 | txvga0,pa0,rf_filter0,hbf0 | TXVGA0 -> 功放模组00 -> RF Filter0 -> HBF0，通道0发射链路 | txvga0=发射增益级; pa0=功放级; rf_filter0=发射滤波; hbf0=TX合路输出 | 可空
RF_RX_CHAIN | RF_RX_CHAIN_00 | hbf0,rx_filter0,lna0,sroc | HBF0 -> RX Filter0 -> LNA0 -> SROC ADC0，通道0接收链路 | hbf0=RX输入入口; rx_filter0=接收滤波; lna0=低噪放; sroc=接收ADC | 可空
```

`链路类型` 会成为模型任务中的 `link_family_id`；`链路编号` 会成为 `link_instance_id`；`用户标识的链路信息` 和 `器件角色说明` 会进入 subagent 上下文。

同一个器件 sheet 可以出现在多条链路中。例如 HBF 既可以在 TX 链路中作为 TX 合路输出，也可以在 RX 链路中作为 RX 输入入口。此时不要把整个 HBF sheet 固定归属到某一条链路，subagent 必须结合链路编号、器件角色说明和当前连接端口判断当前连接属于哪条链路。

## 链路族分析职责

- 链路级分析负责理解整体功能和上下游语义：功能、信号流向、主信号方向、主信号/控制信号区分、bit 位传播、差分 P/N 一致性。
- 器件类型级分析负责复用局部端口映射规则：同类器件的输入/输出 pin 映射、同类型不同实例 index 对应、局部 pin 规则受链路族语义约束。

## 链路族约束

1. 对重复链路，不得简单按器件类型孤立分析。
2. 不得把整条链路所有器件 pin 混在一个单行裁决中。
3. 代表链路用于理解链路语义，最终仍逐 line_id 输出 mapping decision。
4. 器件类型模板只能在链路级模板约束下使用。
5. 与链路族模式不一致的连接进入 hard case 或 unresolved。
6. link_family_id 只影响分析上下文，不影响最终输出分页。
