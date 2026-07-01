### RULE: SIGNAL_SPI 通用 SPI 总线拆分规范

适用条件：
映射族：SPI_CTRL
典型端口：SPI, CLK, CS, DI, DIO, MOSI, MISO, SCLK

#### 总线拆分

SPI 是总线信号，通常可拆成 CLK、CS、DI、DIO，或 CLK、CS、MOSI、MISO。

- 如果框图只写 SPI -> SPI，但没有总线编号、片选号、数据方向，且用户没有另外指定，则按当前物理器件实例中尚未使用的合法 SPI pin 顺序分配。
- 如果用户明确指定 SPI0，则优先匹配 HAC_SPI0_* 或 SPI0_*。
- 如果用户明确指定 CS0/CS1，则匹配对应 CS0/CS1。
