# 自然语言映射规则模板

这个文件用于让用户用自然语言描述映射规则。

本文档直接作为模型语义分析上下文使用。模型会结合框图连接、源端/目的端器件、pin 列表和这里的规则，判断信号在链路中的作用，并选择源端器件中承担同样作用的 pin。

规则分四层：

```text
0. 链路族规则：描述重复链路族、代表链路、链路方向、器件角色、索引和 P/N 传播。
1. 链路级规则：描述一类业务链路的拓扑、索引、器件间连接关系。
2. 器件级规则：描述某个器件 code/料号下，各 pin 或端口的功能。
3. 通用信号规则：描述 SPI、差分、电源、时钟等通用协议/信号族。
```

模型判断时优先级：

```text
用户当前明确说明
  > 链路族/链路级语义
  > 当前器件上下游
  > 器件级局部规则
  > 通用信号规则
  > pin 名称相似度
```

---

## 规则块索引

规则块用于脚本做轻量召回。格式保持自然语言，但标题必须使用：

```text
### RULE: <规则ID> <简短名称>
```

规则块中的“适用条件”只用于召回候选规则，不表示脚本可以直接裁决。最终是否使用该规则，仍由 subagent 结合框图连接、链路上下文、源端 pin 列表逐条判断。

### RULE: FBSW_FEEDBACK_SWITCH 反馈九选一开关映射

适用条件：
源端器件：反馈九选一开关 / 47140609-001 / 91fbsw
链路类型：FEEDBACK_CHAIN
典型端口：FB00, FB01, FB02, FB03, FB04, FB05, FB06, FB07, CH0, SW_V1, SW_V2, SW_V3, VCC

规则摘要：
FB00~FB07 是九选一开关分路 RF 输入端，按顺序映射 RF1~RF8。
CHx 是公共通道/合路端，优先映射 RFC，不得按 CH 数字映射到 RFx。
SW_V1/SW_V2/SW_V3 是控制端口，映射同名 pin。
VCC/VDD_5V0 等供电端口映射到 VCC。

### RULE: SROC_FEEDBACK_CONTROL SROC 反馈链路控制

适用条件：
源端器件：SROC / SROC城堡板 / 0302078562 / 302078562
链路类型：FEEDBACK_CHAIN
典型端口：SP9T0_FBV0, SP9T0_FBV1, SP9T0_FBV2, ADC_FB00
典型目标：反馈九选一开关, balun, 功放模组

规则摘要：
SP9T0_FBV0/1/2 连接反馈九选一开关 SW_V1/SW_V2/SW_V3 时，分别映射 FB_SW0/FB_SW1/FB_SW2。
ADC_FB00 连接反馈九选一开关 CH0 时，映射 RX_BYPASS0。
ADC_FB00 或 ADC32 连接 balun out 时若缺少 AFE 组号，需要 unresolved。

### RULE: SROC_PA_CONTROL SROC 功放/前端控制

适用条件：
源端器件：SROC / SROC城堡板 / 0302078562 / 302078562
链路类型：PA_CONTROL_CHAIN
典型端口：PA_SW0, FEM_TDDSW00, FEM_RXPD00, FEM_RXBY00, FEM_RXBY01, FEM_RXBY02, FEM_RXBY03
典型目标：功放模组, PA_SW_AB, SW_CTRL_CHAB, SWN_PD_RXAB

规则摘要：
PA_SW0 连接功放模组 PA_SW_AB 时，映射 PA_PD_SW0。
FEM_TDDSW00 连接 SW_CTRL_CHAB 时，映射 TRX_TDD_SW0。
FEM_RXPD00 连接 SWN_PD_RXAB 时，需要按连接顺序或目标实例区分 LNA_PD_SW0/LNA_PD_SW1。
FEM_RXBY00~FEM_RXBY03 分别映射 RX_BYPASS0~RX_BYPASS3。

### RULE: SROC_TXVGA_CONTROL_AND_AFE SROC 到 TXVGA 控制与 AFE

适用条件：
源端器件：SROC / SROC城堡板 / 0302078562 / 302078562
链路类型：RF_TX_CHAIN
典型端口：TX_SW0, TX_SW1, DAC00, DAC01, DAC02, DAC03, DAC04, DAC05, DAC06, DAC07
典型目标：TXVGA, TX VGA, RFIN, EN_CHA, EN_CHB

规则摘要：
TX_SW0 控制 TXVGA00/TXVGA01 的 EN_CHA/EN_CHB，映射 TX_PD_SW0。
TX_SW1 控制 TXVGA02/TXVGA03 的 EN_CHA/EN_CHB，映射 TX_PD_SW1。
DAC00~DAC07 到 TXVGA RFIN/default 输入时，是 TX AFE 差分输出，映射对应 TX_AFE0_xx_P/N。

### RULE: SROC_SPI_AMC7964 SROC 到 AMC7964 SPI

适用条件：
源端器件：SROC / SROC城堡板 / 0302078562 / 302078562
链路类型：SPI_CONTROL_CHAIN
映射族：SPI_CTRL
典型端口：SPI
典型目标：AMC7964

规则摘要：
SROC 源Port SPI 连接 AMC7964_00-04/05/06/07 的 SPI 时，使用 HAC_SPI1 总线。
AMC7964_00-04 对应 HAC_SPI1_CS0。
AMC7964_00-05 对应 HAC_SPI1_CLK。
AMC7964_00-06 对应 HAC_SPI1_DIO。
AMC7964_00-07 对应 HAC_SPI1_DI。
AMC7964_00-03 当前待确认，不能硬套。

### RULE: SROC_DRIVER_CONTROL SROC 到集成驱动控制

适用条件：
源端器件：SROC / SROC城堡板 / 0302078562 / 302078562
链路类型：SROC_DRIVER_CONTROL_CHAIN
典型端口：SW, GPIO, SIO
典型目标：集成驱动0, 集成驱动1, PWRSAVE, ALERT, IN_A-D

规则摘要：
SROC SW 连接集成驱动0/1 PWRSAVE 时，分别映射 HBF_PWR_SW0/HBF_PWR_SW1。
GPIO 连接集成驱动0/1 ALERT 时，分别映射 COM_PA_OFF1/COM_PA_OFF2。
SIO 连接集成驱动0/1 IN_A-D 时，分别映射 HBF_IO_1/HBF_IO_2。

### RULE: SROC_CAL_SWITCH SROC 校准开关

适用条件：
源端器件：SROC / SROC城堡板 / 0302078562 / 302078562
链路类型：CAL_SWITCH_CHAIN
典型端口：SW
典型目标：TXCAL_1, RXCAL_1, SW-SROC

规则摘要：
SROC SW 连接 TXCAL_1 的 SW-SROC 时，映射 CAL_SW_11 和 CAL_SW_12。
SROC SW 连接 RXCAL_1 的 SW-SROC 时，映射 CAL_SW_15 和 CAL_SW_16。
一条逻辑控制连接对应两个物理 pin，应使用 selected_pins。

### RULE: SROC_POWER_NET SROC 电源网络

适用条件：
源端器件：SROC / SROC城堡板 / 0302078562 / 302078562
链路类型：POWER_CHAIN
映射族：POWER_ENABLE
典型端口：VDD_0V65_PMU_SROC0_AVS_40A, VDD_1V8_TRX_DVDD

规则摘要：
SROC 电源网络在既有表中不映射到 SROC 器件 pin，原理图Pin脚留空，置信度 Low，网络命名按电源网络名处理。

### RULE: TXVGA_RF_POWER_ENABLE TXVGA 射频/供电/使能

适用条件：
源端器件：TXVGA / TX VGA / 47151290
链路类型：RF_TX_CHAIN, POWER_CHAIN
典型端口：RFIN0, RFIN1, RFOUT0, RFOUT1, EN_CHA, EN_CHB, VDD_2V5, VDD_3V3
典型目标：SROC, 功放模组, 比邻星, 天狼星, PMU, VOUT

规则摘要：
RFIN0/RFIN1 是通道 0/1 射频差分输入，映射对应 CH0/CH1 RF_IN P/N。
RFOUT0/RFOUT1 是通道 0/1 射频输出，映射对应 CH0/CH1 RF_OUT。
EN_CHA/EN_CHB 分别映射 EN_CH0/EN_CHA、EN_CH1/EN_CHB。
VDD_2V5 对应 VCC1 类 pin，VDD_3V3 对应 VCC2 类 pin；目标端为 PMU/比邻星/天狼星/VOUT 时表示给 TXVGA 供电。

### RULE: GENERAL_SPI 通用 SPI

适用条件：
映射族：SPI_CTRL
典型端口：SPI, CLK, CS, DI, DIO, MOSI, MISO, SCLK

规则摘要：
SPI 通常可拆成 CLK、CS、DI、DIO 或 CLK、CS、MOSI、MISO。
如果只有 SPI -> SPI 且没有总线编号、片选号、数据方向，则不能唯一映射到具体 pin。

### RULE: GENERAL_DIFFERENTIAL 通用差分

适用条件：
典型端口：_P, _N, DP, DN, RFIN, DAC, ADC, AFE

规则摘要：
带 P/N、_P/_N、DP/DN 或 AFE 差分语义的信号需要成对判断。
如果一个逻辑端口对应 P/N 两个物理 pin，应使用 selected_pins，不要新增 line_id。

### RULE: GENERAL_POWER 通用电源

适用条件：
映射族：POWER_ENABLE
典型端口：VDD, VCC, AVS, DVDD, VOUT, PWR
典型目标：PMU, 比邻星, 天狼星

规则摘要：
端口名或网络名包含 VDD、VCC、AVS、DVDD 时通常是电源信号。
目标器件名称包含 PMU、比邻星、天狼星且目标端口是 VOUT/VOUT1/VOUT2 时，通常表示 PMU 给源器件供电。
电源 pin 映射必须优先匹配电压值和功能域。

---

## 0. 链路族规则

链路族规则描述“重复出现的一类完整业务链路”。它不是最终输出分组，也不改变 Excel sheet；它只帮助模型先理解全局语义，再判断局部 pin。

### 什么时候使用链路族

```text
如果多个连接实例具有相同或高度相似的器件序列、端口序列、方向和拓扑，应优先按链路族分析。
如果不存在明显重复链路，则按器件类型 / 映射族隔离分析。
如果是控制、时钟、电源、SPI 等信号，优先按映射族分析。
如果是 RF_TX_CHAIN、RF_RX_CHAIN、JESD_CHAIN 等主业务链路，优先按完整链路族分析。
```

### 输入表中的链路信息 sheet

用户可以在输入 Excel 中新增一个 `link_info` 或 `链路信息` sheet，用自然语言和少量字段标注链路族。

这个 sheet 是可选增强信息，不是必填输入。没有链路级数据、没有 `link_family` 时，模型仍必须根据 block_info 器件信息、源/目的 Block、端口名、连线名和 mapping_family 做器件级分析。

推荐表头：

```text
链路类型 | 链路编号 | 器件Sheet | 用户标识的链路信息 | 器件角色说明 | 相关连线ID
```

字段含义：

```text
链路类型：同一类重复链路使用同一个值，例如 RF_TX_CHAIN、FEEDBACK_CHAIN、PA_CONTROL_CHAIN。
链路编号：一条具体链路实例，例如 RF_TX_CHAIN_00、RF_TX_CHAIN_01。
器件Sheet：这条链路涉及哪些器件 sheet，多个 sheet 用逗号、分号或顿号分隔。
用户标识的链路信息：用户对该链路的自然语言说明，例如方向、功能、通道、特殊连接方式。
器件角色说明：描述每个 sheet 在这条链路中的角色，例如 hbf0=TX输出合路; hbf0=RX输入入口。
相关连线ID：可选。需要精确约束时填写这条链路包含的连线ID，多个 ID 用逗号、分号或顿号分隔；也可以写成 sheet:连线ID。
```

示例：

```text
RF_TX_CHAIN | RF_TX_CHAIN_00 | txvga0,pa0,rf_filter0,hbf0 | TXVGA0 -> 功放模组00 -> RF Filter0 -> HBF0，通道0发射链路 | txvga0=发射增益级; pa0=功放级; rf_filter0=发射滤波; hbf0=TX合路输出 | 可空
RF_RX_CHAIN | RF_RX_CHAIN_00 | hbf0,rx_filter0,lna0,sroc | HBF0 -> RX Filter0 -> LNA0 -> SROC ADC0，通道0接收链路 | hbf0=RX输入入口; rx_filter0=接收滤波; lna0=低噪放; sroc=接收ADC | 可空
```

`链路类型` 会成为模型任务中的 `link_family_id`；`链路编号` 会成为 `link_instance_id`；`用户标识的链路信息` 和 `器件角色说明` 会进入 subagent 上下文。

同一个器件 sheet 可以出现在多条链路中。例如 HBF 既可以在 TX 链路中作为 TX 合路输出，也可以在 RX 链路中作为 RX 输入入口。此时不要把整个 HBF sheet 固定归属到某一条链路，subagent 必须结合链路编号、器件角色说明和当前连接端口判断当前连接属于哪条链路。

### 链路族分析职责

```text
链路级分析负责理解整体功能和上下游语义：
- 这条链路整体是什么功能
- 信号从哪里来，到哪里去
- 主信号方向是什么
- 哪些端口是主信号，哪些是控制信号
- bit 位如何沿链路传播
- 差分 P/N 如何沿链路保持一致

器件类型级分析负责复用局部端口映射规则：
- 同类器件的输入/输出 pin 如何映射
- 同类型不同实例是否按 index 对应
- 局部 pin 规则必须受链路族语义约束
```

### 链路族示例

```text
RF_TX_CHAIN:
SROC -> TXVGA -> Filter/Frontend -> PA

处理策略：
先判断这是 RF 发射主链路，主信号方向从 SROC 到 PA。
再判断 TXVGA 在当前链路中处于 SROC 和后级前端/功放之间。
最后复用 TXVGA 的 RFIN/RFOUT、EN、VDD 等局部 pin 映射规则。
```

### 链路族约束

```text
1. 对重复链路，不得简单按器件类型孤立分析。
2. 不得把整条链路所有器件 pin 混在一个单行裁决中。
3. 代表链路用于理解链路语义，最终仍逐 line_id 输出 mapping decision。
4. 器件类型模板只能在链路级模板约束下使用。
5. 与链路族模式不一致的连接进入 hard case 或 unresolved。
6. link_family_id 只影响分析上下文，不影响最终输出分页。
```

## 1. 链路级规则

链路级规则描述“一类电路链路应该怎样连”，重点是拓扑、方向、通道编号、器件实例之间的对应关系。

链路级规则不一定绑定单个器件 code，它可以跨多个器件。

### 链路名称

示例：

```text
TX 控制链路
TX RF 链路
反馈检测链路
SROC 到集成驱动控制链路
SPI 控制链路
```

### 适用电路描述

写这个链路在框图中通常出现的器件名、sheet 名、端口名、网络名关键词。

示例：

```text
适用于 SROC 控制 TXVGA 的使能/开关控制连接。
框图中通常出现：SROC、TXVGA、TX_SW、EN_CHA、EN_CHB。
```

### 链路拓扑

描述源端、目的端、方向、索引关系。

示例：

```text
TX 控制链路中，控制源通常是 SROC，控制目标是 TXVGA。
SROC 的 TX_SW0 控制 TXVGA0/TXVGA1 的使能。
SROC 的 TX_SW1 控制 TXVGA2/TXVGA3 的使能。
TXVGA 的 EN_CHA 对应 A/CH0 通道使能。
TXVGA 的 EN_CHB 对应 B/CH1 通道使能。
```

### 链路级映射规则

写“这条链路中的某个逻辑信号应优先找哪个器件上的什么作用 pin”。

示例：

```text
如果当前 sheet 是 txvga0，源端是 TXVGA，目的端是 SROC，源Port 是 EN_CHA：
这表示 TXVGA0 的 A 通道使能输入，应该在 TXVGA 的 pin 列表中找 EN_CH0/EN_CHA。

如果当前 sheet 是 sroc，源端是 SROC，目的端是 TXVGA，源Port 是 TX_SW0：
这表示 SROC 输出 TXVGA 使能控制，应在 SROC 的 pin 列表中找 TX_PD_SW0 或相关 TX 控制 pin。

SROC 到集成驱动控制链路：
如果源端是 SROC/sroc，源Port 是 SIO，目的端是 集成驱动0，目的Port 是 IN_A-D，
这表示 SROC 输出到集成驱动0的串行/控制接口，应在 SROC pin 列表中选择 HBF_IO_1。
如果源端是 SROC/sroc，源Port 是 SIO，目的端是 集成驱动1，目的Port 是 IN_A-D，
这表示 SROC 输出到集成驱动1的串行/控制接口，应在 SROC pin 列表中选择 HBF_IO_2。

TX/RX 校准开关链路：
如果源端是 SROC，源Port 是 SW，目的端是 TXCAL_1，目的Port 是 SW-SROC，
这表示 TXCAL_1 校准开关控制，需要映射到 SROC 的 CAL_SW_11 和 CAL_SW_12 两个物理 pin。
如果源端是 SROC，源Port 是 SW，目的端是 RXCAL_1，目的Port 是 SW-SROC，
这表示 RXCAL_1 校准开关控制，需要映射到 SROC 的 CAL_SW_15 和 CAL_SW_16 两个物理 pin。
```

### 链路级待确认项

示例：

```text
AMC7964_00-03 的 SPI 需要确认使用 HAC_SPI 几号总线和片选号。
```

---

## 2. 器件级规则

器件级规则描述“某个器件自己的 pin/端口分别是什么功能”。

### 器件名称

示例：

```text
TXVGA
SROC
反馈九选一开关
```

### 器件 code / 料号

示例：

```text
47151290
0302078562
47140609-001
```

### 电路描述关键词

示例：

```text
TXVGA, TX VGA, 发射可变增益放大器
```

### 输入管脚规则

示例：

```text
TXVGA:
RFIN0 是通道 0 射频输入，是差分信号：
- P 端对应 CH0_RF_IN_P 或 CHA_RF_IN_P
- N 端对应 CH0_RF_IN_N 或 CHA_RF_IN_N

RFIN1 是通道 1 射频输入，是差分信号：
- P 端对应 CH1_RF_IN_P 或 CHB_RF_IN_P
- N 端对应 CH1_RF_IN_N 或 CHB_RF_IN_N
```

### 输出管脚规则

示例：

```text
TXVGA:
RFOUT0 是通道 0 射频输出，映射到 CH0_RF_OUT 或 CHA_RF_OUT。
RFOUT1 是通道 1 射频输出，映射到 CH1_RF_OUT 或 CHB_RF_OUT。
```

### 电源管脚规则

示例：

```text
TXVGA:
VDD_2V5 是 2.5V 电源输入，对应 VCC1 类 pin。
如果电路描述显示目标端是 PMU、比邻星、天狼星、VOUT、VOUT1、VOUT2，说明 PMU 在给 TXVGA 供电。
VDD_2V5 对应 CH0_VCC1/CHA_VCC1、CH1_VCC1/CHB_VCC1。

VDD_3V3 是 3.3V 电源输入，对应 VCC2 类 pin。
VDD_3V3 对应 CH0_VCC2/CHA_VCC2、CH1_VCC2/CHB_VCC2。
```

### 控制管脚规则

示例：

```text
TXVGA:
EN_CHA 是通道 A/CH0 使能，映射到 EN_CH0 或 EN_CHA。
EN_CHB 是通道 B/CH1 使能，映射到 EN_CH1 或 EN_CHB。

SROC / 0302078562:
以下规则来自既有信号接口列表的 sroc 页，适用于源端器件为 SROC / SROC城堡板 / 0302078562 的连接。模型必须优先使用这些器件级 pin 规则；只有当前 pin_info 中存在对应 pin 时才可输出该 pin。

反馈九选一开关控制：
- 源Port SP9T0_FBV0 连接到反馈九选一开关 SW_V1 时，映射到 FB_SW0。
- 源Port SP9T0_FBV1 连接到反馈九选一开关 SW_V2 时，映射到 FB_SW1。
- 源Port SP9T0_FBV2 连接到反馈九选一开关 SW_V3 时，映射到 FB_SW2。

功放/前端开关控制：
- 源Port PA_SW0 连接到功放模组 PA_SW_AB 时，映射到 PA_PD_SW0。
- 源Port FEM_TDDSW00 连接到功放模组 SW_CTRL_CHAB 时，映射到 TRX_TDD_SW0。
- 源Port FEM_RXPD00 连接到功放模组 SWN_PD_RXAB 时，如果是第一路映射到 LNA_PD_SW0，如果是第二路映射到 LNA_PD_SW1；同名多路连接要按连接顺序或目标实例区分。
- 源Port FEM_RXBY00/FEM_RXBY01/FEM_RXBY02/FEM_RXBY03 分别映射到 RX_BYPASS0/RX_BYPASS1/RX_BYPASS2/RX_BYPASS3。

TXVGA 使能控制：
- 源Port TX_SW0 连接到 TXVGA00/TXVGA01 的 EN_CHA 或 EN_CHB 时，映射到 TX_PD_SW0。
- 源Port TX_SW1 连接到 TXVGA02/TXVGA03 的 EN_CHA 或 EN_CHB 时，映射到 TX_PD_SW1。

TX DAC / TX AFE 差分输出：
- 源Port DAC00~DAC07 连接到 TXVGA RFIN/default 输入时，是 SROC 到 TXVGA 的 TX AFE 差分输出。
- DAC00 映射到 TX_AFE0_00_P 和 TX_AFE0_00_N。
- DAC01 映射到 TX_AFE0_01_P 和 TX_AFE0_01_N。
- DAC02 映射到 TX_AFE0_02_P 和 TX_AFE0_02_N。
- DAC03 映射到 TX_AFE0_03_P 和 TX_AFE0_03_N。
- DAC04 映射到 TX_AFE0_04_P 和 TX_AFE0_04_N。
- DAC05 映射到 TX_AFE0_05_P 和 TX_AFE0_05_N。
- DAC06 映射到 TX_AFE0_06_P 和 TX_AFE0_06_N。
- DAC07 映射到 TX_AFE0_07_P 和 TX_AFE0_07_N。
- 如果框图只给一条 DACxx 逻辑连接，且需要输出完整物理 pin，应使用 selected_pins 数组同时输出 P/N 两个 pin，不要只选 P 端。

RX ADC / RX AFE 差分输入：
- 源Port ADC00~ADC07 连接到功放模组 RX/default 输出时，是 SROC 接收功放反馈/RX 信号的 RX AFE 差分输入。
- ADC00 映射到 RX_AFE0_00_P 和 RX_AFE0_00_N。
- ADC01 映射到 RX_AFE0_01_P 和 RX_AFE0_01_N。
- ADC02 映射到 RX_AFE0_02_P 和 RX_AFE0_02_N。
- ADC03 映射到 RX_AFE0_03_P 和 RX_AFE0_03_N。
- ADC04 映射到 RX_AFE0_04_P 和 RX_AFE0_04_N。
- ADC05 映射到 RX_AFE0_05_P 和 RX_AFE0_05_N。
- ADC06 映射到 RX_AFE0_06_P 和 RX_AFE0_06_N。
- ADC07 映射到 RX_AFE0_07_P 和 RX_AFE0_07_N。
- ADC32 连接到 Filter2_Ch32 OUT 时，映射到 RX_AFE1_00_P 和 RX_AFE1_00_N。
- 如果框图只给一条 ADCxx 逻辑连接，且需要输出完整物理 pin，应使用 selected_pins 数组同时输出 P/N 两个 pin。

反馈 ADC：
- 源Port ADC_FB00 连接到反馈九选一开关 CH0 时，映射到 RX_BYPASS0。

SPI 到 AMC7964：
- SROC 源Port SPI 连接到 AMC7964_00-04/05/06/07 的 SPI 时，使用 HAC_SPI1 总线。
- AMC7964_00-04 对应 HAC_SPI1_CS0。
- AMC7964_00-05 对应 HAC_SPI1_CLK。
- AMC7964_00-06 对应 HAC_SPI1_DIO。
- AMC7964_00-07 对应 HAC_SPI1_DI。
- 如果目标实例不是 00-04/05/06/07，或者缺少实例编号，则不能套用以上片选/时钟/数据规则，应输出 unresolved。

TX/RX 校准开关控制：
- SROC SW / SROC  SW 连接到 TXCAL_1 的 SW-SROC 时，映射到 CAL_SW_11 和 CAL_SW_12。
- SROC SW / SROC  SW 连接到 RXCAL_1 的 SW-SROC 时，映射到 CAL_SW_15 和 CAL_SW_16。
- 这类一条逻辑控制连接对应两个物理 pin，应使用 selected_pins 数组输出两个 CAL_SW pin。

SROC 到集成驱动控制：
- SROC  SW 连接到集成驱动0 PWRSAVE 时，映射到 HBF_PWR_SW0。
- SROC  SW 连接到集成驱动1 PWRSAVE 时，映射到 HBF_PWR_SW1。
- GPIO 连接到集成驱动0 ALERT 时，映射到 COM_PA_OFF1。
- GPIO 连接到集成驱动1 ALERT 时，映射到 COM_PA_OFF2。
- SIO 连接到集成驱动0 IN_A-D 时，映射到 HBF_IO1/HBF_IO_1；如果 pin_info 中使用带下划线命名，则选择 HBF_IO_1。
- SIO 连接到集成驱动1 IN_A-D 时，映射到 HBF_IO2/HBF_IO_2；如果 pin_info 中使用带下划线命名，则选择 HBF_IO_2。

SROC 电源网络：
- VDD_0V65_PMU_SROC0_AVS_40A 和 VDD_1V8_TRX_DVDD 是电源网络连接，既有表中不映射到 SROC 器件 pin，原理图Pin脚留空，置信度 Low，网络命名按电源网络名处理。
反馈九选一开关 / 47140609-001:
FB00~FB07 是九选一开关的分路 RF 输入端，按顺序映射到 RF1~RF8：
- FB00 对应 RF1
- FB01 对应 RF2
- FB02 对应 RF3
- FB03 对应 RF4
- FB04 对应 RF5
- FB05 对应 RF6
- FB06 对应 RF7
- FB07 对应 RF8

CH0、CH1 等 CHx 端口表示开关公共通道/合路端，不属于 FBxx 分路输入端，不能按 CH 数字映射到 RFx。
当 pin 列表中存在 RFC 时，CHx 应映射到 RFC，避免与 FB00~FB07 的 RF1~RF8 分路 pin 重复。

SW_V1、SW_V2、SW_V3 是控制端口，应分别映射到同名 pin SW_V1、SW_V2、SW_V3。
VCC/VDD_5V0 等供电端口映射到 VCC。
```

### 特殊连接方式

示例：

```text
如果一个框图逻辑信号对应多个物理 pin，模型需要说明应展开为几条。
已展开的 line_id 使用主连线 ID 加 #数字，例如 1868#1、1868#2。
展开后的前 9 列除了连线ID以外不能变化。
```

---

## 3. 通用信号规则

### SPI

示例：

```text
SPI 是总线信号，通常可拆成 CLK、CS、DI、DIO，或 CLK、CS、MOSI、MISO。
如果框图只写 SPI -> SPI，但没有总线编号、片选号、数据方向，则不能唯一映射到具体 pin，需要人工确认。
如果用户明确指定 SPI0，则优先匹配 HAC_SPI0_* 或 SPI0_*。
如果用户明确指定 CS0/CS1，则匹配对应 CS0/CS1。
```

### 差分信号

示例：

```text
带 P/N、_P/_N、DP/DN 的信号是差分信号。
如果框图只有一个逻辑端口，但器件 pin 有 P/N 两个物理端口，需要模型说明是否应展开。
#1 通常映射 P，#2 通常映射 N，除非用户规则另有说明。
```

### 电源信号

示例：

```text
端口名或网络名包含 VDD、VCC、AVS、DVDD 时，通常是电源信号。
目标器件名称包含 PMU、比邻星、天狼星，且目标端口是 VOUT/VOUT1/VOUT2 时，通常表示 PMU 给源器件供电。
电源 pin 映射必须优先匹配电压值和功能域，例如 0V65、1V8、2V5、3V3、DVDD、AVS。
```

---

## 4. 当前待确认规则

```text
AMC7964_00-03 的 SPI 需要确认使用 HAC_SPI 几号总线和片选号。
ADC32 从 balun04 输入到 SROC 时，需要确认对应哪组 AFE/ADC 物理 pin。
```



