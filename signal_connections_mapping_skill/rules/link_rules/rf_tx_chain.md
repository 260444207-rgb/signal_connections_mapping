### RULE: LINK_RF_TX 射频 TX 链路拓扑

适用条件：
链路类型：RF_TX_CHAIN
链路拓扑：SROC -> TXVGA -> Filter/Frontend -> PA
典型器件：SROC, TXVGA, TX VGA, RF Filter, 功放模组, PA

#### 链路语义

RF_TX_CHAIN 是 RF 发射主链路，主信号方向从 SROC 到 PA。TXVGA 在当前链路中处于 SROC 和后级前端/功放之间。

#### 通道编号传播

bit 位沿链路传播：TXVGA CHA/CHB 的通道号对应后级 Filter 和 PA 的通道号。

#### 处理策略

先判断这是 RF 发射主链路。再判断 TXVGA 在当前链路中处于 SROC 和后级前端/功放之间。最后复用 TXVGA 的 RFIN/RFOUT、EN、VDD 等局部 pin 映射规则。

#### TX 控制链路

TX 控制链路中，控制源通常是 SROC，控制目标是 TXVGA：

- SROC 的 TX_SW0 控制 TXVGA0/TXVGA1 的使能。
- SROC 的 TX_SW1 控制 TXVGA2/TXVGA3 的使能。
- TXVGA 的 EN_CHA 对应 A/CH0 通道使能。
- TXVGA 的 EN_CHB 对应 B/CH1 通道使能。

示例：

如果当前 sheet 是 txvga0，源端是 TXVGA，目的端是 SROC，源Port 是 EN_CHA：这表示 TXVGA0 的 A 通道使能输入，应该在 TXVGA 的 pin 列表中找 EN_CH0/EN_CHA。

如果当前 sheet 是 sroc，源端是 SROC，目的端是 TXVGA，源Port 是 TX_SW0：这表示 SROC 输出 TXVGA 使能控制，应在 SROC 的 pin 列表中找 TX_PD_SW0 或相关 TX 控制 pin。
