### RULE: 0302078562 SROC / 0302078562 / 302078562 完整 pin 映射规则

适用条件：
源端器件：SROC / SROC城堡板 / 0302078562 / 302078562

以下规则来自既有信号接口列表的 sroc 页，适用于源端器件为 SROC / SROC城堡板 / 0302078562 / 302078562 的连接。

最高优先级：如果单 pin 连接的 `source_port` 已逐字存在于当前 SROC 的 pin_info，直接令 `selected_pin=source_port`，不得套用下列旧逻辑端口映射再翻译一次。下列规则只用于 `source_port` 未精确命中 pin_info，或具体小节明确要求多个 pin 的情况；只有 pin_info 中存在规则目标 pin 时才可输出。

#### 反馈九选一开关控制

- 源Port SP9T0_FBV0 连接到反馈九选一开关 SW_V1 时，映射到 FB_SW0。
- 源Port SP9T0_FBV1 连接到反馈九选一开关 SW_V2 时，映射到 FB_SW1。
- 源Port SP9T0_FBV2 连接到反馈九选一开关 SW_V3 时，映射到 FB_SW2。

#### 功放/前端开关控制

- 源Port PA_SW0 连接到功放模组 PA_SW_AB 时，映射到 PA_PD_SW0。
- 源Port FEM_TDDSW00 连接到功放模组 SW_CTRL_CHAB 时，映射到 TRX_TDD_SW0。
- 源Port FEM_RXPD00 连接到功放模组 SWN_PD_RXAB 时，如果是第一路映射到 LNA_PD_SW0，如果是第二路映射到 LNA_PD_SW1；同名多路连接要按连接顺序或目标实例区分。
- 源Port FEM_RXBY00 映射到 RX_BYPASS0。
- 源Port FEM_RXBY01 映射到 RX_BYPASS1。
- 源Port FEM_RXBY02 映射到 RX_BYPASS2。
- 源Port FEM_RXBY03 映射到 RX_BYPASS3。

#### TXVGA 使能控制

- 源Port TX_SW0 连接到 TXVGA00/TXVGA01 的 EN_CHA 或 EN_CHB 时，映射到 TX_PD_SW0。
- 源Port TX_SW1 连接到 TXVGA02/TXVGA03 的 EN_CHA 或 EN_CHB 时，映射到 TX_PD_SW1。
- TX_SW[num] 系列管脚，一个管脚能控制两个 TXVGA 器件（例如 TXVGA00/TXVGA01 的 EN_CHA/EN_CHB），这两个器件的连线映射的是同一个管脚 TX_PD_SW[num]。

#### TX DAC / TX AFE 差分输出

- 源Port DAC00~DAC07 连接到 TXVGA RFIN/default 输入时，是 SROC 到 TXVGA 的 TX AFE 差分输出。
- DAC00 映射到 TX_AFE0_00_P 和 TX_AFE0_00_N。
- DAC01 映射到 TX_AFE0_01_P 和 TX_AFE0_01_N。
- DAC02 映射到 TX_AFE0_02_P 和 TX_AFE0_02_N。
- DAC03 映射到 TX_AFE0_03_P 和 TX_AFE0_03_N。
- DAC04 映射到 TX_AFE0_04_P 和 TX_AFE0_04_N。
- DAC05 映射到 TX_AFE0_05_P 和 TX_AFE0_05_N。
- DAC06 映射到 TX_AFE0_06_P 和 TX_AFE0_06_N。
- DAC07 映射到 TX_AFE0_07_P 和 TX_AFE0_07_N。
- 如果框图只给一条 DACxx 逻辑连接，且需要输出完整物理 pin，应使用 selected_pins 数组同时输出 P/N 两个 pin，不要只选 P 端。

#### RX ADC / RX AFE 差分输入

- 源Port ADC00~ADC07 连接到功放模组 RX/default 输出时，是 SROC 接收功放反馈/RX 信号的 RX AFE 差分输入。
- ADC00 映射到 RX_AFE0_00_P 和 RX_AFE0_00_N。
- ADC01 映射到 RX_AFE0_01_P 和 RX_AFE0_01_N。
- ADC02 映射到 RX_AFE0_02_P 和 RX_AFE0_02_N。
- ADC03 映射到 RX_AFE0_03_P 和 RX_AFE0_03_N。
- ADC04 映射到 RX_AFE0_04_P 和 RX_AFE0_04_N。
- ADC05 映射到 RX_AFE0_05_P 和 RX_AFE0_05_N。
- ADC06 映射到 RX_AFE0_06_P 和 RX_AFE0_06_N。
- ADC07 映射到 RX_AFE0_07_P 和 RX_AFE0_07_N。
- ADC32 连接到 Filter2_Ch32 OUT 时，映射到 RX_AFE1_00_P 和 RX_AFE1_00_N。
- 如果框图只给一条 ADCxx 逻辑连接，且需要输出完整物理 pin，应使用 selected_pins 数组同时输出 P/N 两个 pin。

#### 反馈 ADC

- 源Port ADC_FB00 连接到反馈九选一开关 CH0 时，映射到 RX_BYPASS0。

#### SPI 到 AMC7964

- SROC 源Port SPI 连接到 AMC7964_00-04/05/06/07 的 SPI 时，使用 HAC_SPI1 总线。
- AMC7964_00-04 对应 HAC_SPI1_CS0。
- AMC7964_00-05 对应 HAC_SPI1_CLK。
- AMC7964_00-06 对应 HAC_SPI1_DIO。
- AMC7964_00-07 对应 HAC_SPI1_DI。
- SROC 源Port SPI 信号是 HAC_SPI 总线信号，都需要拆分成 4 条: HAC_SPI×_CS0，HAC_SPI×_CLK，HAC_SPI×_DIO，HAC_SPI×_DI。其中 × 标识数字，用户没有要求的情况下按照顺序去分配。
- 如果目标实例不是 00-04/05/06/07，或者缺少实例编号，则不能套用以上片选/时钟/数据规则，应输出 unresolved。

#### TX/RX 校准开关控制

- SROC SW 连接到 TXCAL_1 的 SW-SROC 时，映射到 CAL_SW_11 和 CAL_SW_12。
- SROC SW 连接到 RXCAL_1 的 SW-SROC 时，映射到 CAL_SW_15 和 CAL_SW_16。
- 这类一条逻辑控制连接对应两个物理 pin，应使用 selected_pins 数组输出两个 CAL_SW pin。

#### SROC 到集成驱动控制

- SROC SW 连接到集成驱动0 PWRSAVE 时，映射到 HBF_PWR_SW0。
- SROC SW 连接到集成驱动1 PWRSAVE 时，映射到 HBF_PWR_SW1。
- GPIO 连接到集成驱动0 ALERT 时，映射到 COM_PA_OFF1。
- GPIO 连接到集成驱动1 ALERT 时，映射到 COM_PA_OFF2。
- SIO 连接到集成驱动0 IN_A-D 时，映射到 HBF_IO1/HBF_IO_1；如果 pin_info 中使用带下划线命名，则选择 HBF_IO_1。
- SIO 连接到集成驱动1 IN_A-D 时，映射到 HBF_IO2/HBF_IO_2；如果 pin_info 中使用带下划线命名，则选择 HBF_IO_2。

#### SROC 电源网络

- VDD_0V65_PMU_SROC0_AVS_40A 和 VDD_1V8_TRX_DVDD 是电源网络连接，既有表中不映射到 SROC 器件 pin，原理图Pin脚留空，置信度 Low，网络命名按电源网络名处理。
