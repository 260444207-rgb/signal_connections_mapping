### RULE: LINK_POWER 电源链路拓扑

适用条件：
链路类型：POWER_CHAIN
映射族：POWER_ENABLE
典型器件：SROC, PMU, 比邻星, 天狼星, VOUT

#### 链路语义

电源链路中 PMU/比邻星/天狼星 作为供电方，VOUT/VOUT1/VOUT2 输出到被供电器件。端口名或网络名包含 VDD、VCC、AVS、DVDD 时通常是电源信号。

#### 电源 pin 映射

电源 pin 映射必须优先匹配电压值和功能域，例如 0V65、1V8、2V5、3V3、DVDD、AVS。

#### 特殊处理

SROC 电源网络 VDD_0V65_PMU_SROC0_AVS_40A 和 VDD_1V8_TRX_DVDD 既有表中不映射到 SROC 器件 pin，原理图Pin脚留空，置信度 Low，网络命名按电源网络名处理。
