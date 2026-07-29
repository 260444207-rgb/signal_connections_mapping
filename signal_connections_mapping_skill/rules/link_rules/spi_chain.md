### RULE: LINK_SPI SPI 控制链路拓扑

适用条件：
链路类型：SPI_CONTROL_CHAIN
映射族：SPI_CTRL
典型器件：SROC, AMC7964

#### 链路语义

SPI_CONTROL_CHAIN 是数字控制链路，SROC 作为 SPI 主设备，下发配置到从设备。

#### 总线分配

SROC 源Port SPI 是 HAC_SPI 总线信号，连接到 AMC7964 等器件时需要拆分成 CS、CLK、DIO、DI 四条。其中 SPI× 的总线编号 × 按顺序分配。

#### 待确认

AMC7964_00-03 的 SPI 需要确认使用 HAC_SPI 几号总线和片选号。
