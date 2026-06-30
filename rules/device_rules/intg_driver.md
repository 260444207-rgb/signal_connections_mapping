### RULE: INTG_DRIVER 集成驱动0 / 集成驱动1 规则

适用条件：
源端器件：集成驱动0 / 集成驱动1

#### 超时保护/PWRSAVE

- SROC SW 连接到集成驱动0 PWRSAVE 时，映射到 HBF_PWR_SW0。
- SROC SW 连接到集成驱动1 PWRSAVE 时，映射到 HBF_PWR_SW1。

#### 异常告警/ALERT

- GPIO 连接到集成驱动0 ALERT 时，映射到 COM_PA_OFF1。
- GPIO 连接到集成驱动1 ALERT 时，映射到 COM_PA_OFF2。

#### 串行接口 IN_A-D

- SIO 连接到集成驱动0 IN_A-D 时，映射到 HBF_IO1/HBF_IO_1；如果 pin_info 中使用带下划线命名，则选择 HBF_IO_1。
- SIO 连接到集成驱动1 IN_A-D 时，映射到 HBF_IO2/HBF_IO_2；如果 pin_info 中使用带下划线命名，则选择 HBF_IO_2。
