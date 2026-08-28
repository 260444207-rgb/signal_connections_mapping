### RULE: SIGNAL_POWER 通用电源信号规范

适用条件：
映射族：POWER_ENABLE
典型端口：VDD, VCC, AVS, DVDD, VOUT, PWR
典型目标：PMU, 比邻星, 天狼星

#### 电源信号识别

端口名或连线名称包含 VDD、VCC、AVS、DVDD 时通常是电源信号。

目标器件名称包含 PMU、比邻星、天狼星且目标端口是 VOUT/VOUT1/VOUT2 时，通常表示 PMU 给源器件供电。

#### 电源 pin 映射

电源 pin 映射必须优先匹配电压值和功能域，例如 0V65、1V8、2V5、3V3、DVDD、AVS。
