### RULE: LINK_FEEDBACK 反馈检测链路拓扑

适用条件：
链路类型：FEEDBACK_CHAIN
典型器件：SROC, 反馈九选一开关, 功放模组, balun, Filter

#### 链路语义

FEEDBACK_CHAIN 是反馈检测链路，信号从功放输出/滤波器耦合端反馈回到 SROC ADC 做监测。

#### 反馈九选一开关

反馈九选一开关处于反馈链路中，作为多路 FB 输入信号的选通器件。CHx 是公共通道/合路端，输出到后级或直接到 SROC ADC_FBxx。

#### 处理策略

先判断这是反馈检测链路。反馈九选一开关的 FB00~FB07 按顺序映射 RF1~RF8，CHx 映射 RFC。SROC 侧 SP9T0_FBVx 是开关控制信号。
