# 通用映射规则

### RULE: GLOBAL_MAPPING 通用硬件语义规则

1. 功能优先：优先根据功能、方向、上下游拓扑判断映射，名称相似度只作为辅助。
2. 总线语法：`XXX[N:0]`、`XXX*M` 只提供声明宽度；实际展开数必须由严格匹配的器件规则所列成员与当前器件 `pin_info` 的交集确定。
3. 差分信号：识别 `_P/_N`、`DP/DN`，差分信号必须成对校验。
4. 一驱多：同一个 source port 连接多个 target 时，每条连接独立生成 normalized connection。
5. 不生成额外连接：只处理输入连接关系中存在的信号。
6. 方向只允许 INPUT / OUTPUT。
7. 置信度：High/Medium/Low。
