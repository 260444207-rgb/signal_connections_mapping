---
name: diagram-signal-net-consistency-checker
description: 生成信号接口列表后，用脚本完成确定性网络名检查和修正；模型只处理总线/链路族等需要语义判断的部分。
---

# 网络名一致性检查 Skill

## 一句话原则

**确定性的活全部交给脚本；模型不要手工扫 Excel、不要手工重算重名/不匹配组。**

模型只做脚本无法确定的语义判断，主要是：

- 总线/展开连线是否表示同一物理子线两端。
- 不同连线 ID 但网络名相同，是否是同一源 pin 扇出。
- 缺少结构化字段时，根据链路族、端点、器件实例判断网络名是否应该一致。

## 绝对禁止

- 不要做 Pin 脚清洗、拆分、合法性校验。
- 不要直接编辑 Excel 单元格来“试着修”。
- 不要按肉眼手工统计不匹配组或重名组。
- 不要把 `LINE`、`line`、`LINE_数字`、`LINE_数字_P/N` 当作有效网络名。
- 不要只按完整连线 ID 判断总线。`6778` 和 `6778#1` 可能属于同一总线物理子线两端。
- 不要把不同 P/N、不同展开序号、不同对端器件实例强行统一成同一个网络名。

## 参考脚本

位置：`script/check_net_consistency.py`

脚本负责：

1. 读取 `signal_interface.xlsx`。
2. 读取 `intermediate/normalized_connections.jsonl`。
3. 读取 `intermediate/model_resolved_decisions.jsonl`。
4. 检查网络名格式。
5. 收集连线 ID 原始不匹配组。
6. 收集需统一的物理组。
7. 收集重名组。
8. 对确定性问题生成修正提案。
9. 在 `--fix` 时写出修正后的 Excel。

模型负责：

1. 运行脚本。
2. 读取脚本报告摘要。
3. 对脚本仍无法决定的总线/链路族问题做语义判断。
4. 把结论反馈给用户，或作为下一轮规则/脚本修改依据。

## 标准执行流程

### Step 1：只检查，不修改

优先运行 JSON 报告，方便模型读取。

```bash
python script/check_net_consistency.py \
  --input "generated_signal_interface/output/signal_interface.xlsx" \
  --intermediate-dir "generated_signal_interface/intermediate" \
  --report "generated_signal_interface/intermediate/net_consistency_report.json"
```

如果用户提供的是其他输出目录，把路径替换成用户目录：

```text
<run_dir>/output/signal_interface.xlsx
<run_dir>/intermediate/
```

脚本退出码为 `1` 不表示脚本失败，只表示发现了需要关注的问题。

### Step 2：读报告摘要

只看这些字段：

```json
{
  "summary": {
    "format_issue_count": 0,
    "raw_connection_mismatch_group_count": 0,
    "actionable_physical_mismatch_group_count": 0,
    "duplicate_group_count": 0,
    "proposed_change_count": 0
  }
}
```

字段含义：

| 字段 | 含义 | 谁处理 |
|------|------|--------|
| `format_issue_count` | 网络名格式问题或占位名 | 脚本报告；只有确定性修正才脚本改 |
| `raw_connection_mismatch_group_count` | 按完整连线 ID 汇总的原始不匹配组 | 脚本收集，模型不要重算 |
| `actionable_physical_mismatch_group_count` | 同一物理子线两端仍不一致 | 脚本优先修；修后仍有才模型判断 |
| `duplicate_group_count` | 同名但不确定是否允许复用 | 脚本优先修；修后仍有才模型判断 |
| `proposed_change_count` | 脚本拟自动修改的行数 | 大于 0 时可运行 `--fix` |

### Step 3：执行确定性修正

如果 `proposed_change_count > 0`，运行：

```bash
python script/check_net_consistency.py \
  --input "generated_signal_interface/output/signal_interface.xlsx" \
  --intermediate-dir "generated_signal_interface/intermediate" \
  --output "generated_signal_interface/output/signal_interface_net_checked.xlsx" \
  --report "generated_signal_interface/intermediate/net_consistency_report_fix.json" \
  --fix
```

不要覆盖原文件，除非用户明确要求。

### Step 4：复查修正后的文件

```bash
python script/check_net_consistency.py \
  --input "generated_signal_interface/output/signal_interface_net_checked.xlsx" \
  --intermediate-dir "generated_signal_interface/intermediate" \
  --report "generated_signal_interface/intermediate/net_consistency_report_after_fix.json"
```

复查判断：

- `actionable_physical_mismatch_group_count == 0`：物理两端一致性已解决。
- `duplicate_group_count == 0`：重名冲突已解决。
- 仍有 `format_issue_count`：说明存在脚本不敢自动改的格式问题，报告给用户或进入模型语义判断。
- 仍有 `raw_connection_mismatch_group_count` 但 `actionable_physical_mismatch_group_count == 0`：通常是同一完整连线 ID 被多个端点复用，不代表还需要统一。

## 网络名格式检查

脚本保留格式检查能力。

合法网络名：

- 只包含大写字母、数字、下划线。
- 可带总线后缀，例如 `DATA[7:0]`。

格式问题：

- 中文。
- 空格。
- `*`。
- `-`。
- `_TO_` 连接词。
- 小写字母。
- 其他非字母数字下划线字符。

占位网络名：

```text
LINE
line
LINE_1
LINE_175
LINE_1_P
LINE_1_N
```

占位网络名即使格式看起来合法，也不能作为最终网络名。

## 不匹配组判断

脚本先收集“连线ID原始不匹配组”。

规则：

1. 按完整 `连线ID` 跨 sheet 汇总。
2. 如果同一个完整 `连线ID` 下出现多个网络名，加入原始不匹配组。
3. 组内保留端点子组。
4. 端点子组按无方向端点判断：

```text
(源Block标识, 源Port) + (目的Block标识, 目的Port)
```

如果 A 页是：

```text
SROC TX_SW0 -> TXVGA1 EN_CHA
```

B 页是：

```text
TXVGA1 EN_CHA -> SROC TX_SW0
```

两者是同一端点子组，网络名必须一致。

如果同一个完整连线 ID 下同时出现：

```text
SROC <-> TXVGA0
SROC <-> TXVGA1
```

这是不同端点子组，不能直接统一成同一个网络名。

## 总线/展开连线判断

总线分析需要模型参与，但脚本先给出结构化事实。

优先使用这些字段：

```text
normalized_connections.jsonl:
  connection_id
  base_connection_id
  expansion_index
  expansion_count
  source_sheet_name
  source_block_id
  source_port
  target_block_id
  target_port
  direction
  link_family_id
  link_instance_id

model_resolved_decisions.jsonl:
  selected_pin
  net_name
  selected_pins
  net_names
```

模型判断总线时按下面顺序：

1. 如果两个记录的 `base_connection_id` 不同，默认不是同一条总线子线。
2. 如果 `base_connection_id` 相同，再看展开序号。
3. `6778` 和 `6778#1` 这类 ID：
   - `6778` 是 base ID。
   - `#1` 是展开子线序号。
   - 如果两端源/末端互为反向，并且展开序号对应，则应使用同一网络名。
4. P/N 差分：
   - P 只和 P 统一。
   - N 只和 N 统一。
   - P 和 N 不能统一成同一个网络名。
5. 多个对端器件实例：
   - 对端是 `txvga0` 的网络名必须包含 `TXVGA0`。
   - 对端是 `txvga1` 的网络名必须包含 `TXVGA1`。
   - 不同对端实例不能生成同一个网络名。

模型不要凭网络名长得像来判断总线。必须结合：

- base ID。
- 展开序号。
- 端点反向关系。
- 对端器件实例。
- P/N 或 bit 序号。

## 重名组判断

脚本按网络名收集不同连线 ID 或不同物理子线。

允许重名的唯一确定性场景：

```text
所有 OUTPUT 行的 sheet + 源Block标识 + 原理图Pin脚 完全相同
```

含义：同一源 pin 扇出到多个目的端。

其他重名都按冲突处理，需要改成不同网络名。

弱模型判断时只回答一个问题：

```text
这些重名行是不是同一个 OUTPUT 源 pin 的扇出？
```

如果不是，不能保留重名。

## 自动修正规则

脚本只做确定性修正。

| 场景 | 脚本动作 |
|------|----------|
| 同一物理子线两端网络名不同 | 统一为 canonical 网络名 |
| 一侧是 `LINE` 占位名，另一侧有有效名 | 使用有效名 |
| 没有有效名但可生成稳定名称 | 按模板生成 |
| 重名但不是同源 pin 扇出 | 按物理子线生成不同网络名 |
| 仅格式不合规且没有确定性依据 | 只报告，不强改 |

canonical 网络名优先级：

1. 非 `LINE` 占位且格式合法的连线名称。
2. 组内唯一有效网络名。
3. `model_resolved_decisions.jsonl` 中唯一有效网络名。
4. 按模板生成新网络名。

## 命名模板

普通模板：

```text
源器件别名_源PIN或源PORT_对端器件别名_对端PORT
```

总线/展开模板：

```text
源器件别名_源PIN或源PORT_对端器件实例名_对端PORT
```

对端器件实例名优先级：

1. 如果对端 Block 能映射到 sheet，使用 sheet 名：
   - `txvga0` -> `TXVGA0`
   - `txvga1` -> `TXVGA1`
2. 否则从对端 Block 名提取器件名和序号。
3. 仍无法得到时使用 `BLK_<BlockID>`。

示例：

```text
SROC_TX_PD_SW0_TXVGA0_EN_CHA
SROC_TX_PD_SW0_TXVGA1_EN_CHA
SROC_TX_AFE0_02_P_TXVGA1_RFIN0
```

如果生成名仍重名，追加连线 ID 或展开序号。

## 弱模型输出格式

完成检查后，只输出这几类信息：

```text
已运行脚本：
- 检查命令
- 如有修正，修正命令
- 复查命令

结果：
- 格式问题数量
- 连线ID原始不匹配组数量
- 需统一物理组数量
- 重名组数量
- 已写出的修正文件

模型判断：
- 是否存在需要模型判断的总线/链路族问题
- 若存在，逐组说明判断依据
```

不要把完整 Excel 内容贴给用户。
不要长篇复述所有行。

## 脚本退出码

- `0`：没有格式问题、没有需统一物理组、没有重名组。
- `1`：发现需要关注的问题。退出码 `1` 不等于脚本执行失败。

## 最小安全策略

如果模型不确定某个总线/链路族判断：

1. 不要自动修改。
2. 报告对应 sheet、行号、连线 ID、端点、当前网络名。
3. 说明缺少哪个判断依据。
4. 等用户确认或补充规则。
