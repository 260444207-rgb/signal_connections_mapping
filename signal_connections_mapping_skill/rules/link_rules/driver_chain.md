### RULE: LINK_DRIVER SROC 到集成驱动控制链路

适用条件：
链路类型：SROC_DRIVER_CONTROL_CHAIN
典型器件：SROC, 集成驱动0, 集成驱动1

#### 链路语义

SROC 通过 SW/GPIO/SIO 端口发出控制信号到集成驱动器件，集成驱动负责 PA 电源保护等功能。

#### 控制映射

- SROC SW -> 集成驱动0/1 PWRSAVE -> HBF_PWR_SW0/HBF_PWR_SW1
- GPIO -> 集成驱动0/1 ALERT -> COM_PA_OFF1/COM_PA_OFF2
- SIO -> 集成驱动0/1 IN_A-D -> HBF_IO_1/HBF_IO_2

示例：

如果源端是 SROC/sroc，源Port 是 SIO，目的端是 集成驱动0，目的Port 是 IN_A-D：这表示 SROC 输出到集成驱动0的串行/控制接口，应在 SROC pin 列表中选择 HBF_IO_1。

如果源端是 SROC/sroc，源Port 是 SIO，目的端是 集成驱动1，目的Port 是 IN_A-D：这表示 SROC 输出到集成驱动1的串行/控制接口，应在 SROC pin 列表中选择 HBF_IO_2。
