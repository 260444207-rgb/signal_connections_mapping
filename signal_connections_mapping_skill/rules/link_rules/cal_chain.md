### RULE: LINK_CAL 校准开关链路拓扑

适用条件：
链路类型：CAL_SWITCH_CHAIN
典型器件：SROC, TXCAL_1, RXCAL_1

#### 链路语义

校准链路中 SROC SW 端口输出控制信号到 TXCAL_1 或 RXCAL_1 的 SW-SROC 端口，控制校准通路切换。

#### 控制映射

- 如果源端是 SROC，源Port 是 SW，目的端是 TXCAL_1，目的Port 是 SW-SROC：这表示 TXCAL_1 校准开关控制，需要映射到 SROC 的 CAL_SW_11 和 CAL_SW_12 两个物理 pin。
- 如果源端是 SROC，源Port 是 SW，目的端是 RXCAL_1，目的Port 是 SW-SROC：这表示 RXCAL_1 校准开关控制，需要映射到 SROC 的 CAL_SW_15 和 CAL_SW_16 两个物理 pin。
