---
name: signal-interface-net-naming
description: 汇总已有信号接口列表；合法连线名称直接采用并检查冲突，其余命名组由模型先根据连线两端器件 pin 判断 DIGITAL、RF、POWER 或 GROUND，再按类型规则命名并安全回填。用于 pin 分析完成后的独立网络命名；不推导、修改或补全器件 pin。
---

# signal-interface-net-naming

输入必须是已包含标准 13 列的信号接口列表 Excel。此 skill 不分析或修改“原理图Pin脚”、映射置信度及前 9 列连接事实。

## 1. 生成命名任务

```powershell
python '<skill_root>\scripts\prepare_naming.py' --input '<signal_interface.xlsx>' --task-dir '<task_dir>'
```

脚本先按完整连线 ID 汇总两端记录，再执行跨 ID 分组：仅当方向为 `OUTPUT`、Block 与实际 pin 相同、且连线 ID 的 `_数字` 后缀相同时才合为一个命名组。`#` 是总线展开标记，不是分组后缀；各 `#` 成员分别命名但联合分析。

## 2. 第 5 部分：脚本直接采用合法连线名称

脚本汇总命名组内所有方向的“连线名称”，不区分 `INPUT` 和 `OUTPUT`：

- 合法名称匹配 `^[A-Za-z][A-Za-z0-9_]{0,30}$`，且不是 `LINE` 或 `LINE_*` 占位名。
- 只有一个不同的合法名称时，逐字写入 `automatic_decisions.jsonl`，不做清洗，也不再交给模型。
- 多个不同合法名称必须返回冲突，不能按方向选择。
- 空值、`LINE_xxx`、空格、连字符、中文或其他非法字符不触发直用，只作为模型上下文保留。

如果 prepare 返回 `ERROR`，先解决冲突，不得继续回填。

## 3. 第 6 部分：模型先分类，再命名

其余命名组写入 `<task_dir>/naming_groups.jsonl`。每行是一个联合分析族；每组的 `connection_details` 按连线 ID 给出两端器件、port、实际 pin、原连线名称和分析说明。

模型必须按以下顺序处理每个 `groups[].id`：

1. 比较同一 `connection_details` 内两端器件的 pin、port、Block，并结合 `analysis_notes`。
2. 将该组判为 `DIGITAL`、`RF`、`POWER` 或 `GROUND`。
3. 读取任务中的 `type_naming_rules[signal_type]`，按对应拼接规则生成网络名。
4. 每组输出一行到 `<task_dir>/naming_decisions.jsonl`：

```json
{"id":"G0001","signal_type":"DIGITAL","net_name":"SRC_DST_EN","basis":"两端 pin 分别为 CTRL 与 EN，判断为数字使能信号。"}
```

`signal_type`、`net_name`、`basis` 都是必填项。模型网络名必须为最长 31 字符的 SCREAMING_SNAKE_CASE。如果 `model_group_count=0`，不需要创建模型 decision 文件。

不得用旧确定性生成器替代模型分析，也不得逐 Excel 行分别命名。同一命名组只输出一个结果，并回填到组内所有器件端口行。

## 4. 唯一规则维护入口

所有规则只在 [rules/net_naming_rules.md](rules/net_naming_rules.md) 维护。脚本自动抽取以下标记区写入任务：

- `MODEL_TASK_RULES_START/END`：通用格式。
- `SIGNAL_CLASSIFICATION_RULES_START/END`：四类信号判断依据。
- `DIGITAL_NAMING_RULES_START/END`：数字信号拼接规则。
- `RF_NAMING_RULES_START/END`：射频信号拼接规则。
- `POWER_NAMING_RULES_START/END`：电源网络拼接规则。
- `GROUND_NAMING_RULES_START/END`：地网络拼接规则。

四个类型拼接区已经预留；后续只在对应标记之间添加以 `- ` 开头的规则，不改脚本。

## 5. 统一回填

```powershell
python '<skill_root>\scripts\apply_naming.py' --input '<signal_interface.xlsx>' --task-dir '<task_dir>' --output '<named.xlsx>'
```

脚本合并自动 decision 与模型 decision，检查任务索引属于当前输入、每组恰好一个 decision、模型结果包含合法 `signal_type`，并确认各回填行连线 ID 未变化。通过后将同一结果写到命名组全部行的第 13 列“网络命名”，同时在原“分析说明”后追加或刷新“网络命名依据”。

回写只定点替换目标单元格 XML，不重序列化 worksheet，并在发布前校验 ZIP 与回读值。旧“网络命名”不能覆盖本次 decision。
