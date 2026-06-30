### RULE: TXCAL_RXCAL TXCAL_1 / RXCAL_1 校准开关控制

适用条件：
源端器件：SROC / SROC城堡板 / 0302078562 / 302078562
目标器件：TXCAL_1 / RXCAL_1

#### 校准开关映射

- SROC SW 连接到 TXCAL_1 的 SW-SROC 时，映射到 CAL_SW_11 和 CAL_SW_12。
- SROC SW 连接到 RXCAL_1 的 SW-SROC 时，映射到 CAL_SW_15 和 CAL_SW_16。

这类一条逻辑控制连接对应两个物理 pin，应使用 selected_pins 数组输出两个 CAL_SW pin。
