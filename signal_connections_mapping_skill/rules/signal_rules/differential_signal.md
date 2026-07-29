### RULE: SIGNAL_DIFF 通用差分信号 P/N 规范

适用条件：
典型端口：_P, _N, DP, DN, RFIN, DAC, ADC, AFE

#### 差分信号识别

带 P/N、_P/_N、DP/DN 或 AFE 差分语义的信号需要成对判断。

#### 差分展开

- 如果框图只有一个逻辑端口，但器件 pin 有 P/N 两个物理端口，需要模型说明是否应展开。
- #1 通常映射 P，#2 通常映射 N，除非用户规则另有说明。
- 如果一个逻辑端口对应 P/N 两个物理 pin，应优先输出 parent_line_id=原line_id 且 line_id=原line_id#数字 的多行 decision；兼容旧任务时才使用 selected_pins。

#### 差分一致性

差分 P/N 沿链路传播时必须保持一致的极性关联。
