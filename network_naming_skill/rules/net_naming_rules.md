# 网络命名规则

本文件是网络命名规则的唯一维护入口。脚本从标记区自动抽取规则写入模型任务，不要在脚本中复制规则正文。

## 分组规则

1. 同一完整连线 ID 的所有记录先归入同一个命名组；组内最终只回填一个网络名。
2. `#` 表示总线展开，不是命名组后缀。不同 `#` 成员分别命名，但放在同一分析族中统一分析前缀与位号。
3. `_数字` 是跨连线 ID 的命名分组后缀。只有 `OUTPUT` 方向、Block 相同、实际原理图 pin 相同且 `_数字` 后缀相同，才能跨连线 ID 合成同一命名组。
4. 相同 `OUTPUT` Block + 实际 pin 下，不同 `_数字` 后缀是不同命名组，但放在同一分析族中联合分析。
5. `INPUT` 或方向为空不能触发跨连线 ID 合组；没有 `_数字` 后缀时也不跨不同连线 ID 自动合并。

## 第 5 部分：合法连线名称直接采用

该部分完全由 `prepare_naming.py` 执行，不交给模型判断。

1. 汇总命名组所有记录的“连线名称”，不区分 `INPUT`、`OUTPUT` 或其他方向。
2. 合法名称必须匹配 `^[A-Za-z][A-Za-z0-9_]{0,30}$`，并且不能是 `LINE` 或以 `LINE_` 开头的占位名（忽略大小写）。
3. 组内只有一个不同的合法名称时，必须逐字作为网络名，不做大小写转换或其他清洗，也不再进入模型分析。
4. 同一个合法名称重复出现不算冲突；出现两个或更多不同的合法名称时，prepare 必须返回冲突，不能按方向选一个。
5. 空值、`LINE_xxx`、包含空格、连字符、中文或其他非法字符的“连线名称”不触发直用。它们保留在模型任务上下文中，但不能覆盖模型结果。

## 第 6 部分：模型先分类，再命名

只有没有唯一合法连线名称、且不存在合法名称冲突的命名组才进入模型分析。

模型必须先逐条查看 `connection_details` 中同一连线的两端器件、port 和实际 pin，并结合 `analysis_notes` 判断信号类型；随后只使用该类型对应的拼接规则生成网络名。模型 decision 必须同时输出 `signal_type`、`net_name` 和 `basis`。

### 通用模型规则

<!-- MODEL_TASK_RULES_START -->
- 综合命名组全部 connection_details、两端器件、实际 pin 和分析说明，不按单行视角命名。
- 先输出 signal_type，再读取 type_naming_rules 中对应类型的拼接规则生成 net_name。
- net_name 使用 SCREAMING_SNAKE_CASE，字母开头且不超过 31 字符。
- 差分保留 P/N；总线成员保持共同前缀，并保留各自位号或关键字。
<!-- MODEL_TASK_RULES_END -->

### 信号类型判断规则

<!-- SIGNAL_CLASSIFICATION_RULES_START -->
- signal_type 只能是 DIGITAL、RF、POWER、GROUND 之一。
- 必须优先比较同一 connection_detail 内两个 endpoint 的 pin、port 和 Block，再用 analysis_notes 补充判断。
- 数字控制、时钟、复位、使能及普通数字数据归为 DIGITAL；射频收发及高频模拟通道归为 RF；供电、电压轨及电源输出归为 POWER；接地、回流及地参考归为 GROUND。
- 无法仅凭单端字段判断时，要综合另一端 pin 和同一分析族的相关连接；basis 简述分类依据。
<!-- SIGNAL_CLASSIFICATION_RULES_END -->

### DIGITAL：数字信号拼接规则

在下面两个标记之间维护数字信号的拼接要求；每条规则使用 `- ` 开头。

<!-- DIGITAL_NAMING_RULES_START -->
<!-- 在此维护 DIGITAL 拼接规则。 -->
<!-- DIGITAL_NAMING_RULES_END -->

### RF：射频信号拼接规则

在下面两个标记之间维护射频信号的拼接要求；每条规则使用 `- ` 开头。

<!-- RF_NAMING_RULES_START -->
<!-- 在此维护 RF 拼接规则。 -->
<!-- RF_NAMING_RULES_END -->

### POWER：电源网络拼接规则

在下面两个标记之间维护电源网络的拼接要求；每条规则使用 `- ` 开头。

<!-- POWER_NAMING_RULES_START -->
<!-- 在此维护 POWER 拼接规则。 -->
<!-- POWER_NAMING_RULES_END -->

### GROUND：地网络拼接规则

在下面两个标记之间维护地网络的拼接要求；每条规则使用 `- ` 开头。

<!-- GROUND_NAMING_RULES_START -->
<!-- 在此维护 GROUND 拼接规则。 -->
<!-- GROUND_NAMING_RULES_END -->

## 回填约束

输入 Excel 中已有的旧“网络命名”不能覆盖本次结果。`automatic_decisions.jsonl` 与 `naming_decisions.jsonl` 共同构成本次回填的权威 decision。

模型分析必须读取 `analysis_notes`。回填时保留原分析说明，并追加或刷新“网络命名依据”。同一命名组的结果必须写回该组全部器件端口行。
