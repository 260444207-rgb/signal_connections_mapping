### RULE: 47151290 TXVGA / TX VGA / 47151290 射频/供电/使能映射

适用条件：
源端器件：TXVGA / TX VGA / 47151290

#### 输入管脚规则

- RFIN0 是通道 0 射频输入，是差分信号：
  - P 端对应 CH0_RF_IN_P 或 CHA_RF_IN_P
  - N 端对应 CH0_RF_IN_N 或 CHA_RF_IN_N
- RFIN1 是通道 1 射频输入，是差分信号：
  - P 端对应 CH1_RF_IN_P 或 CHB_RF_IN_P
  - N 端对应 CH1_RF_IN_N 或 CHB_RF_IN_N

#### 输出管脚规则

- RFOUT0 是通道 0 射频输出，映射到 CH0_RF_OUT 或 CHA_RF_OUT。
- RFOUT1 是通道 1 射频输出，映射到 CH1_RF_OUT 或 CHB_RF_OUT。

#### 电源管脚规则

- VDD_2V5 是 2.5V 电源输入，对应 VCC1 类 pin。
- 如果电路描述显示目标端是 PMU、比邻星、天狼星、VOUT、VOUT1、VOUT2，说明 PMU 在给 TXVGA 供电。
- VDD_2V5 对应 CH0_VCC1/CHA_VCC1、CH1_VCC1/CHB_VCC1。
- VDD_3V3 是 3.3V 电源输入，对应 VCC2 类 pin。
- VDD_3V3 对应 CH0_VCC2/CHA_VCC2、CH1_VCC2/CHB_VCC2。

#### 控制管脚规则

- EN_CHA 是通道 A/CH0 使能，映射到 EN_CH0 或 EN_CHA。
- EN_CHB 是通道 B/CH1 使能，映射到 EN_CH1 或 EN_CHB。
