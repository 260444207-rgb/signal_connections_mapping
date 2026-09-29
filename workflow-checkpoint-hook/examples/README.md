# 三阶段卡点完整示例

本示例展示 research → draft → review 的本地需求报告流程，用于验证“当前阶段结束后归档、重置原会话，再继续下一阶段”。三个阶段不是 Hook 写死的；它们来自 config.json.workflows 与本 Skill 的明确约定。

此目录中的产物是静态文档样本，不是已经在你的 Gateway 中执行得到的结果。

## 文件

| 文件 | 用途 |
| --- | --- |
| config.example.json | 可复制的配置结构，路径必须替换；默认复用注册 Agent 模型 |
| SKILL.md | 可复制的完整 Skill，含三个阶段、验收标准、卡点命令与停止规则 |
| input/requirements.md | 虚构小组周报需求，只需读取本地文件 |
| artifacts/research.json | 第一阶段信息提取样本 |
| artifacts/draft.md | 第二阶段草稿样本 |
| artifacts/report.md | 最终报告样本 |
| artifacts/review.json | 最终逐项验收样本 |

## 准备

1. 依照 [详细使用说明](../docs/usage-guide.md) 安装并启用 Hook、确认注册 Agent 的模型与认证可用，然后重启 Gateway。
2. 将本示例的 SKILL.md 保存到实际可加载的 Skill 目录，并记下它的绝对路径。下面以 C:/work/checkpoint-demo-skill/SKILL.md 举例。
3. 将 config.example.json 中的 research-report 阶段列表和 workflowSkills 映射合并到安装目录的 config.json。保留你的其他工作流配置。
4. 把 workflowSkills.research-report 填成实际 SKILL.md 绝对路径。不要填写样本中不存在的 C:/work 路径。
5. 为本次任务准备一个新的产物目录，例如 C:/work/checkpoint-demo-run-01。要求它可被 Gateway、Agent 和后台脚本读写。
6. 需求输入使用本目录 input/requirements.md 的实际绝对路径。不要先把 artifacts 中的样本复制为本次输出；让 Agent 依据输入真实生成。

示例不要求单独的摘要接口。摘要会调用绑定 Agent 的模型，后台进程须能读取同一份 OpenClaw 配置及认证。

## 初始任务文本

替换下面三个绝对路径为本机实际值，然后在一个专用演练会话中发送：

> 使用 research-report Skill，Skill 文件位于 C:/work/checkpoint-demo-skill/SKILL.md。
> 需求文件位于 C:/work/checkpoint-demo-skill/input/requirements.md，本次输出目录是 C:/work/checkpoint-demo-run-01。
> 按 research、draft、review 顺序写一份周报交接决策报告。只根据本地需求，不联网调研。
> 每阶段通过 workflow-checkpoint Hook 的本轮注入脚本提交卡点；收到 accepted=true 后立即结束本轮，由后台重置同一会话并继续下一阶段。最后交付 report.md 与 review.json。

上述需求文件示例路径要求你把 input 目录也放在对应位置；若只复制了 SKILL.md，请改成输入文件真正所在的路径。

会话的首轮应只完成 research。不要在 Agent 提交卡点后继续向该会话追加消息，等待后台交接。界面若仍显示旧消息，不代表模型上下文没有清空；应核查回执中的 source_session_id 与 next_session_id。

## 预期过程

| 轮次 | 进入依据 | 本轮产物 | request 参数 | 后台动作 |
| --- | --- | --- | --- | --- |
| 1 | 原始用户任务 | research.json | --stage research --next draft | 归档、摘要、保存 prompt、reset、提交 draft |
| 2 | continuation.next_stage=draft | draft.md | --stage draft --next review | 归档、摘要、保存 prompt、reset、提交 review |
| 3 | continuation.next_stage=review | report.md、review.json | --stage review，不传 --next | 终点归档，停止 |

每轮的脚本绝对路径和 token 由本轮 Hook bootstrap 注入。Skill 中的尖括号写法只是参数位置说明，不是固定命令；不得手工生成或复用上一轮 token。Skill 恢复信息中的 continuation.skill 指向归档 Skill 副本；它的相对资源仍按源文件目录解析。

accepted=true 仅表示请求已入队，不表示上述后台动作已经完成。源轮次不得查询 status 或做后续工具调用；观察工作由另一个终端进行：

    node "<实际 Hook 安装目录>/checkpoint.mjs" status --job "<本次 request 返回的 job_id>"

## 产物样本怎么用

可在本次执行完成后，对照 artifacts/ 下的静态样本检查结构和覆盖范围。样本中 research.json 的 source_path 是相对于其样本目录的路径，实际执行应记录本次输入文件的绝对路径；样本中的 example_only 标记说明它不是运行证明。

不要求 Agent 逐字复刻样本。真正要求是满足原始需求、记录可靠依据、产生可读持久文件、遵守卡点停止规则，并且不重复已完成阶段。

## 暂停与失败示例

如果 draft 阶段发现 research.json 缺失，不能猜测原阶段结果。先在对话中说明阻塞和准确路径，再用本轮注入值提交：

    node "<本轮注入的 checkpoint.mjs 绝对路径>" request --token "<本轮 token>" --workflow research-report --stage draft --status paused

此请求不传 --next；accepted=true 后结束本轮。后台只归档，不 reset，不提交 review。修复文件或补充用户输入后，操作者应按 [恢复说明](../docs/usage-guide.md) 核查已有状态，不直接把 held 改为 queued，也不循环重试不确定的 reset。

## worker 中断后的恢复示例

只在后台 worker 已退出、checkpoint 已完整持久化且尚未进入 dispatch/reset 的情况下，可从外部终端尝试：

    node "<实际 Hook 安装目录>/checkpoint.mjs" recover --job "<本次实际 job_id>"

命令会核查旧 worker PID 是否确实不存在、源 run 是否正常结束、是否有更新 run，以及 delivery 状态是否允许恢复。accepted=true/recovered=true 表示已重新排队，仍需外部 status 查看处理结果。若返回 RECOVERY_DELIVERY_AMBIGUOUS 等拒绝代码，应停止自动重试并核查回执，不能强行重放 reset。详细条件见 [恢复说明](../docs/usage-guide.md)。

这不是恢复业务暂停的命令，也不能凭部分归档重建未落盘 checkpoint。

## 演练通过的证据

保留本次三轮的实际 job_id、checkpoint_id、产物、归档和回执。核查两个非终点阶段确实改变了原会话的上下文代次、使用保存的 prompt 进入下一阶段；终点没有触发第四轮。最终报告覆盖需求中的验收项，未决的维护人问题仍明确标注。

运行 npm test 是本地模拟验证，以上演练是部署验证。没有真实 Gateway 记录时，不将静态样本或模拟结果写成“真实联调已通过”。
