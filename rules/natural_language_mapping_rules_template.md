# 自然语言映射规则模板

这个文件用于让用户用自然语言描述映射规则。

本文档直接作为模型语义分析上下文使用。模型会结合框图连接、源端/目的端器件、pin 列表和这里的规则，判断信号在链路中的作用，并选择源端器件中承担同样作用的 pin。

规则分三层：

```text
1. 链路级规则：描述一类业务链路的拓扑、索引、器件间连接关系。
2. 器件级规则：描述某个器件 code/料号下，各 pin 或端口的功能。
3. 通用信号规则：描述 SPI、差分、电源、时钟等通用协议/信号族。
```

模型判断时优先级：

```text
用户当前明确说明
  > 链路级规则
  > 器件级规则
  > 通用信号规则
  > pin 名称相似度
```

---

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
```

### 链路级待确认项

示例：

```text
TXCAL_1/RXCAL_1 的 SW-SROC 需要确认对应 CAL_SW 编号。
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
TXCAL_1/RXCAL_1 的 SW-SROC 需要确认对应 CAL_SW 编号。
集成驱动0/1 的 SIO -> IN_A-D 需要确认对应 SROC 哪一组 HBF_IO 或其他 GPIO。
AMC7964_00-03 的 SPI 需要确认使用 HAC_SPI 几号总线和片选号。
```
