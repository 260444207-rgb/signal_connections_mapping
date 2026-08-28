---
name: signal-interface-net-naming
description: 汇总已有信号接口列表，优先逐字采用非空“连线名称”，仅将缺少连线名称的命名组交给模型结合端点、实际 pin、分析说明和命名规则分析，再安全回填“网络命名”。用于 pin 分析完成后的独立网络命名；不推导、修改或补全器件 pin。
---

# signal-interface-net-naming

输入必须是已包含标准 13 列的信号接口列表 Excel。此 skill 不分析或修改“原理图Pin脚”、映射置信度及前 9 列连接事实。

先生成精简命名任务：

```powershell
python '<skill_root>\scripts\prepare_naming.py' --input '<signal_interface.xlsx>' --task-dir '<task_dir>'
```

脚本先执行最高优先级规则：优先查找命名组 OUTPUT 记录的非空“连线名称”，找到唯一值后逐字作为该组网络名写入 `<task_dir>/automatic_decisions.jsonl`，不再交给模型分析；OUTPUT 名称为空时才查找其他端。若同一优先级出现多个不同的非空连线名称，prepare 返回 ERROR，不能擅自选择。

只有没有连线名称的组才写入 `<task_dir>/naming_groups.jsonl`。模型必须读取其中每组的 `analysis_notes`、全部端点、实际 pin，以及任务内嵌的精简 `rules`；必要时再读取完整规范 [rules/net_naming_rules.md](rules/net_naming_rules.md)。精简 `rules` 也由该文件的 `MODEL_TASK_RULES_START/END` 标记区自动抽取，脚本中没有第二份规则。每行是一个联合分析族，模型为每个 `groups[].id` 输出一行到 `<task_dir>/naming_decisions.jsonl`：

```json
{"id":"G0001","net_name":"SROC_TXVGA_DAC0_P","basis":"OUTPUT 连线的 Block+pin 相同，且连线ID下划线后缀同为1；与同族总线成员保持前缀一致。"}
```

如果 `model_group_count=0`，不需要创建 `naming_decisions.jsonl`。不得用脚本或旧确定性生成器替代模型分析空名称组，也不得逐 Excel 行或仅按完整连线 ID 命名。分组规则由脚本完成：

- `#` 表示总线展开成员；`BUS#1`、`BUS#2` 分别命名，但必须放在同一分析族中，网络名前缀一致，末尾使用不同关键字或数字。
- `_数字` 才是连线 ID 的命名分组后缀。只有方向为 `OUTPUT`，且 Block + 实际 pin 相同，才比较该后缀；即使 ID 前缀不同，只要数字后缀相同，就属于同一命名组、只输出一个网络名。
- 相同 `OUTPUT` Block + 实际 pin 下的不同 `_数字` 后缀是不同命名组，但放在同一分析族中比较全部后缀后再命名。
- `INPUT` 或方向为空的记录不能触发跨连线 ID 的后缀合组；同一完整连线 ID 的两端记录仍自然归入同一命名组。
- 没有 `_数字` 后缀时不跨不同连线 ID 自动合并；同一完整连线 ID 的两端记录仍归入同一命名组。

最后统一回填：

```powershell
python '<skill_root>\scripts\apply_naming.py' --input '<signal_interface.xlsx>' --task-dir '<task_dir>' --output '<named.xlsx>'
```

脚本合并自动 decision 与模型 decision，校验任务索引属于当前输入 Excel、每个命名组恰好有一个 decision，并确认组内所有回填行的连线 ID 未变化；通过后把同一结果写到该命名组全部器件端口行的第 13 列“网络命名”，同时在原“分析说明”后追加或刷新带前缀的“网络命名依据”。回写只定点替换目标单元格 XML，不重序列化整张 worksheet，并在发布输出前校验 ZIP 与回读值。

命名规则唯一维护入口是 [rules/net_naming_rules.md](rules/net_naming_rules.md)。需要调整模型任务内嵌规则时，只修改该文件的“模型任务精简规则”标记区；分组、覆盖检查和回填完全由脚本完成，模型只负责对精简组结构命名。

边界：

- `#` 只表示总线联合分析关系，不是命名组分隔规则。
- `_数字` 后缀必须结合 `OUTPUT` 方向及相同 Block + 实际 pin 判断命名组，不能只比较 ID 前缀。
- 同一命名组即使包含多个不同连线 ID，也必须使用同一个网络名。
- 非空“连线名称”是最高优先级，逐字采用，不做格式清洗或模型改写。
- 只有“连线名称”为空的组才允许模型分析；模型必须使用表格中的“分析说明”作为辅助上下文。
- 不使用旧网络名覆盖本次组级 decision。
- 不调用 pin 分析 skill，也不修改 pin 分析结论。
