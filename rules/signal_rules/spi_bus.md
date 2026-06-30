### RULE: SIGNAL_SPI 通用 SPI 总线拆分规范

适用条件：
映射族：SPI_CTRL
典型端口：SPI, CLK, CS, DI, DIO, MOSI, MISO, SCLK

#### 总线拆分

SPI 是总线信号，通常可拆成 CLK、CS、DI、DIO，或 CLK、CS、MOSI、MISO。

- 如果框图只写 SPI -> SPI，但没有总线编号、片选号、数据方向，则不能唯一映射到具体 pin，需要人工确认。
- 如果用户明确指定 SPI0，则优先匹配 HAC_SPI0_* 或 SPI0_*。
- 如果用户明确指定 CS0/CS1，则匹配对应 CS0/CS1。
- 如果只有 SPI -> SPI 且没有总线编号、片选号、数据方向，则按照顺序选择未使用的 pin。
