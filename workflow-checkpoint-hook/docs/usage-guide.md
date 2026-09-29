# Workflow checkpoint Hook 详细使用说明

本文对应本目录中的独立文件 Hook 与配套脚本，面向 OpenClaw 2026.7.1、Node >=24.15 且 <25。安装入口是 HOOK.md 和 handler.js，业务卡点入口是 checkpoint.mjs request。它不需要旧 workflow_checkpoint 插件工具。

本文描述实际实现和部署演练方法。自动测试与本地模拟不能证明你的真实 Gateway、摘要服务、环境变量和 Skill 已正确接通；真实部署结果以你运行后的归档、回执和会话行为为准。

## 1. 这套 Hook 做什么

用户所说的 A、C 是“当前完成的阶段”和“下一阶段”，不是代码写死的名称。config.json 声明工作流的有序阶段，Skill 在对应卡点显式提交请求。

例如：

    research-report: research → draft → review

完整交接顺序是：

1. Skill 完成 research 的验收，先保存中间产物并把准确路径记入对话。
2. Skill 执行本轮注入的 request 命令。脚本核查阶段、运行绑定和配置，把请求写入本地队列，启动后台 worker。
3. 脚本返回 accepted=true；Skill 立即结束当前轮，后台才能确认源 run 已结束。
4. worker 将公共 transcript API 可读取的消息和事件写入 context.json。配置了 workflowSkills 时，同时保存本次 Skill 副本。
5. worker 调用已配置的摘要接口，从可见消息中提取任务目标、事实、决策、限制、未决问题和产物引用。原始用户输入另行保留，完成阶段由受校验的工作流状态决定。
6. 保存 checkpoint.json、restart-prompt.md，并提交本地状态。
7. 对非终点的 completed 卡点，重新确认源 run 结束、会话代次未变、没有新增用户输入或其他活动 run，并保存 context-final.json。
8. 调用 sessions.reset 清空原会话的模型上下文；确认 sessionKey 不变且 sessionId 已更新，将进度迁移到新 sessionId。
9. 将已经保存的 restart-prompt.md 作为下一轮输入提交回同一会话，执行 draft。

draft 完成后同样交接到 review；review 是终点，只归档，不 reset，也不提交下一轮。paused 和 failed 也只归档。

“压缩”发生在第 5 步：摘要服务根据完整可见消息分块重建结构化任务状态。旧上下文原件保存在本地，送回会话的是用户原始输入、结构化状态、Skill 引用、产物路径和下一阶段说明，而不是把旧上下文全文重新加载一遍。

## 2. 组件分工与约束

| 组件 | 负责什么 | 不能代替什么 |
| --- | --- | --- |
| Skill | 执行业务、验收产物、在明确卡点提交请求、停止当前轮 | 不负责归档整个会话，不自行 reset |
| handler.js | 在 Gateway 中观察公开 Agent 生命周期，把当前运行的可信绑定注入 bootstrap 上下文 | 独立 Hook 不注册模型工具，也无法硬拦截模型后续工具调用 |
| checkpoint.mjs request | 校验请求并入队，启动后台进程 | accepted=true 不代表 reset 或续跑已完成 |
| 后台 worker | 等待 run 结束、归档、摘要、持久化、reset 和续跑 | 不猜测缺失的身份，不自动重放不确定任务 |
| 摘要接口 | 提取有依据的结构化任务状态 | 不控制跳转，不执行工具 |
| 本地归档和 SQLite | 保留原始证据、启动 prompt、状态和投递回执 | 产物路径引用不等于已经复制所有外部产物文件 |

这里使用公开 onAgentEvent 来观察真实 run，不把不存在的独立 Hook agent_end 事件写入配置。公开导出的包路径虽然名为 openclaw/plugin-sdk/...，使用这些运行时函数并不等于注册插件。

## 3. 安装与迁移

1. 将整个 Hook 目录复制到当前 OpenClaw 用户的 ~/.openclaw/hooks/workflow-checkpoint。Windows 例子为 C:/Users/你的用户名/.openclaw/hooks/workflow-checkpoint。
2. 确保目录中包含 HOOK.md、handler.js、checkpoint.mjs、config.json、src/。不能只复制 HOOK.md。
3. 使用普通持久会话；incognito 临时会话不支持，Hook 不会注入 token，后台也会拒绝对这类会话 reset。核对 Gateway 版本与 Node 版本。当前代码有 OpenClaw 2026.7.1 版本检查；不把其他版本当成已经验证兼容。
4. 按下一节填写 config.json，并让 Gateway、Agent 的执行工具、后台 Node 子进程能读到同一份配置、状态目录、Skill 文件和摘要密钥。
5. 如果装过旧 workflow-checkpoint 插件，先在现有 OpenClaw 配置中禁用旧插件，避免两套逻辑同时 reset。
6. 执行以下命令并重启 Gateway：

       openclaw hooks list
       openclaw hooks enable workflow-checkpoint

7. 为目标工作流配置并加载改造后的 Skill。开始演练前检查该 Skill 中的阶段名与配置一致。

重启很重要：Hook 需要在 Gateway 进程中订阅运行事件。把文件复制到目录或在外部终端单独运行脚本，不会凭空产生当前 run 的可信绑定。

升级时先让正在交接的任务结束，保留状态与归档，再替换代码并重启。不要把删库当成常规升级或修复步骤。

## 4. 配置逐项说明

可复制 [config.example.json](../examples/config.example.json) 为安装目录下的 config.json，再替换示例路径、服务地址和模型名。示例中的 .example 地址不会提供真实服务。

| 字段 | 含义与填写方式 |
| --- | --- |
| openclawPackageRoot | 正在运行的 OpenClaw 安装包根目录，目录内应有该包的 package.json。不是 JustDo 仓库根目录。Node 可以正常解析对应公开导出时可留空。 |
| stateDir | 本地状态和归档根目录。自定义时必须为绝对路径。留空时使用 OPENCLAW_STATE_DIR 或 ~/.openclaw 下的 workflow-checkpoint-hook 子目录。 |
| workflows | workflow_id 到有序阶段数组的映射。例如 research-report 对应 research、draft、review。当前只支持线性阶段，不支持条件分支、循环或并行。 |
| workflowSkills | 可选的 workflow_id 到 SKILL.md 绝对路径映射，建议填写。worker 会在卡点归档 Skill 副本，并将源路径、副本路径和哈希放入续跑 prompt，避免 reset 后找不到原 Skill。 |
| waitTimeoutMs | worker 等待源 run 结束的时限，默认 900000 毫秒，即 15 分钟。不是整条工作流的总时限。 |
| summarizer.baseUrl | 可选外部覆盖：OpenAI-compatible Chat Completions 基地址，如 https://你的服务/v1。脚本追加 /chat/completions，不要填完整的 /chat/completions URL。通常要求 HTTPS，只有回环地址允许 HTTP。 |
| summarizer.model | 该服务实际支持的模型 ID。必须能按要求返回 JSON 文本。 |
| summarizer.apiKeyEnv | 保存接口密钥的环境变量名，默认 WORKFLOW_CHECKPOINT_API_KEY。这里填写变量名，不填密钥值。 |

workflow_id 和 stage_id 区分大小写，由字母、数字、点、下划线和短横线组成，以字母或数字开头，最长 128 字符。每个工作流的阶段列表非空且不可重复。

summarizer 可以省略或设为 {}；旧配置中 baseUrl/model 都为空也采用默认模式。默认通过公开 prepareSimpleCompletionModelForAgent / completeWithPreparedSimpleCompletionModel 复用绑定 Agent 的主模型和认证，不创建额外 Agent 会话，也不提供工具。读取的是后台进程可见的 OpenClaw 文件配置，不继承当前会话临时模型覆盖或 Gateway 仅在内存中的配置变更；useUtilityModel=false。原始事件留在本地，当前分支消息分块发送给所选模型。

若需要覆盖默认模型，可在 config.json 中加入下面的字段片段：

```json
"summarizer": {
  "baseUrl": "https://your-service.example/v1",
  "model": "your-model",
  "apiKeyEnv": "WORKFLOW_CHECKPOINT_API_KEY"
}
```

显式模式必须同时提供 baseUrl/model 和对应密钥环境变量；配置不完整或服务失败不会静默切回 Agent 模型。默认配置及示例已省略此字段。

若使用 Windows 服务启动 Gateway，在另一个 PowerShell 里临时设置环境变量并不会修改已启动服务的环境；应使用你的 Gateway 启动方式配置环境并重启。不要把实际密钥写入示例 JSON、Skill、产物或版本库。

workflowSkills 的处理规则：

- 映射必须指向实际可读的绝对路径。
- Skill 副本与 context.json 放在同一卡点归档目录，文件名为 SKILL.md。
- 续跑输入包含 continuation.skill.source_path、snapshot_path、sha256。
- 后续阶段先读取副本，Skill 中的相对资源引用仍以 source_path 所在目录为基准解析。
- Hook 复制的是 SKILL.md 本身；Skill 的 scripts/、references/、assets/ 等相对资源不会全部自动复制，源资源必须继续可用。
- 读取或保存 Skill 失败时不会继续 reset；reset 前也会校验副本未被修改。

## 5. Skill 卡点怎么写

每个阶段都明确六件事：阶段 ID、输入、工作内容、完成标准、持久产物、下一阶段 ID。仅在文章中出现“卡点”这个词不会触发 Hook；真正的触发是本轮执行 request 并通过校验。

中间阶段示意命令：

    node "<本轮注入的 checkpoint.mjs 绝对路径>" request --token "<本轮注入的 token>" --workflow research-report --stage research --next draft

终点示意命令：

    node "<本轮注入的 checkpoint.mjs 绝对路径>" request --token "<本轮注入的 token>" --workflow research-report --stage review

暂停示意命令：

    node "<本轮注入的 checkpoint.mjs 绝对路径>" request --token "<本轮注入的 token>" --workflow research-report --stage draft --status paused

尖括号内是说明性占位符，不能照字面执行。handler.js 在本轮 bootstrap 的 AGENTS.md 上下文中提供真实脚本绝对路径和随机 token；它不修改用户磁盘上的 AGENTS.md 文件。Skill 应使用本轮注入的值，不自己生成 token，也不向 CLI 传 sessionKey、sessionId 或 runId。

必须写入 Skill 的规则：

> 提交前先完成所有产物写入、验证和结果记录。只有当前阶段通过验收才能提交 completed。收到 accepted=true 后立即结束本轮，可以给一句简短交接说明，但不得再调用工具、轮询状态或执行下一阶段。accepted=false 时停在边界并报告 code，不自行 reset 或绕过失败进入下一阶段。

原因很具体：worker 在等待源 run 结束。如果模型在 request 后继续读取文件或调用工具，这些内容仍属于源 run；如果它不断轮询状态，交接就无法及时开始。

完整可复制样例见 [examples/SKILL.md](../examples/SKILL.md)，改造已有 Skill 的规则见 [skill-checkpoint-adaptation.md](skill-checkpoint-adaptation.md)。

## 6. 返回值与运行状态

request 成功响应示意：

    {
      "accepted": true,
      "job_id": "job_<64位哈希>",
      "duplicate": false,
      "status": "queued",
      "instruction": "End this run now. ..."
    }

该示意中的 job_id 不是真实任务 ID。后续检查使用你自己的实际返回值。CLI 输出中的 instruction 与停止规则一致；重复的同一卡点请求可能返回已有任务状态，并不会因此完成新的业务阶段。

| job 状态 | 实际含义 |
| --- | --- |
| queued | 请求已落盘，等待后台领取 |
| working | 后台已领取，可能仍在等待源 run，或正在归档、摘要、reset、提交 |
| done | 当前卡点处理结束。非终点只说明下一阶段已提交，不证明下一阶段业务已完成 |
| held | 需要核查失败或不确定状态，不能盲目重放 |

从另一个终端查看状态：

    node "<Hook安装目录>/checkpoint.mjs" status --job "<实际 job_id>"

status 命令只读取状态，不会推进业务。不要让源 Agent 在本轮执行这个轮询。work 是配套脚本的内部 worker 入口，不是建议操作者手动重试任务的命令。

提供 recover --job 用于已经持久化、尚未开始 dispatch 且旧 worker 已确认退出的任务，详见第 9 节。它不是通用 resume 或强制 reset 命令。

## 7. 归档里面有什么

默认目录结构示意：

    stateDir/
      bindings.sqlite
      state.sqlite
      logs/
        job_<hash>.log
      archives/
        cp_<hash>/
          context.json
          checkpoint.json
          restart-prompt.md
          SKILL.md
          context-final.json
          restart-receipt.json

SQLite 使用 WAL，运行时出现 -wal、-shm 伴随文件是正常现象。SKILL.md 只在配置了对应 workflowSkills 时存在；context-final.json 和 restart-receipt.json 只在进入非终点交接流程时产生。失败可能发生在中途，因此不能要求失败卡点总拥有全部文件。

| 文件 | 内容及核查用途 |
| --- | --- |
| context.json | 本卡点的公开可见 messages 和 transcript events、会话身份、阶段与采集时间。摘要失败时它仍可作为本地原始证据。 |
| checkpoint.json | 原始用户输入、目标、完成/剩余阶段、状态、产物引用、下一阶段、归档路径及哈希。 |
| restart-prompt.md | 已保存、待原样发送的下一阶段输入，包含 checkpoint 标记及 workflow-continuation 结构。 |
| SKILL.md | 此卡点使用的 Skill 文本副本；与配置映射对应。 |
| context-final.json | reset 前再次采集的公开记录，用来保留最后状态。 |
| restart-receipt.json | reset 和续跑提交的进展记录；用于判断不确定故障发生在哪个阶段。 |

“完整上下文”限定为公共 transcript API 可读取的完整记录，不包含服务端隐藏推理、未写入 transcript 的内存状态或外部文件全文。中间产物通常保存路径和用途引用；应保留原文件，避免后续阶段只剩失效路径。

消息摘要有大小限制：当前消息 JSON 累计超过 4,000,000 字符会拒绝自动继续，不静默丢弃尾部。单条很长的消息会拆分处理；每次摘要请求最多等待 90 秒。压缩比例没有固定百分比，由任务状态所需信息决定。

## 8. 原会话 reset 的含义

会话身份与模型上下文是两件事。继续使用同一 sessionKey，2026.7.1 的 reset 会生成新的 sessionId。Hook 验证返回值，先在本地事务中将进度关联到新 sessionId，再把保存的启动 prompt 发入该会话。原始 checkpoint 和归档仍保留源 sessionId。只有 Hook 确认的 reset 才会迁移进度，手动重置不会自动继承。

是否在界面上仍能看到旧消息由宿主实现决定。本 Hook 不负责修改界面历史显示，也不引入新的 OpenClaw 核心补丁。看到界面旧消息并不等于模型仍加载了旧上下文；应核查 reset 的代次以及后续输入。

重置前会核查源 run、会话代次、用户输入和其他已观察到的活动 run。但公共 sessions.reset 接口没有 expectedRevision 原子条件，检查与 reset、发送之间仍有短暂竞态。2026.7.1 的 agent 参数没有 expectedExistingSessionId；本实现发送前再次核对当前 sessionId，再传入明确的 sessionId，这不是原子条件。部署演练时在提交卡点后不要并行向原会话追加消息。

内部 lifecycle_revision 字段优先记录 SDK 的 lifecycleRevision；缺失时使用 sessionId 作为边界标识。它不意味着 2026.7.1 的 reset 一定返回 lifecycleRevision。回执另存 source_session_id / next_session_id。

## 9. 故障定位与恢复原则

先确定任务停在入队前还是入队后。

- accepted=false：保存返回的 code。此响应不能证明整个后台链路完全未执行，特别是你重复提交已有任务时；结合 job 和归档检查。
- accepted=true 后迟迟不续跑：从外部终端查看 job，检查源 Agent 是否真的结束本轮，再看 logs/job_<hash>.log。
- held 或 worker 异常退出：保留当前文件和数据库，结合 checkpoint.json、restart-receipt.json、Gateway 会话记录定位。
- 不根据一行日志就执行第二次 reset，也不编辑数据库把 held 强行改回 queued。

常见代码：

| 代码 | 检查方向 |
| --- | --- |
| SUMMARIZER_CONFIG_INCOMPLETE / SUMMARIZER_API_KEY_MISSING | 显式外部摘要配置不完整或密钥环境变量缺失；删除 summarizer 可恢复 Agent 默认模式 |
| INVALID_INPUT / INVALID_ARGUMENTS / INVALID_TRANSITION | 参数、状态、阶段顺序是否与配置一致；终点是否误传 next |
| UNKNOWN_BINDING_TOKEN / RUN_BINDING_UNAVAILABLE | 是否真的加载本轮 Hook、是否使用本轮注入 token、运行事件是否可获得完整身份 |
| SOURCE_RUN_NOT_ACTIVE / BINDING_EXPIRED | 是否复用了历史 token；绑定最长有效期为 24 小时 |
| RUN_BOUNDARY_ALREADY_REQUESTED | 同一源 run 已提交一个卡点，不能在该 run 内继续提交另一个阶段 |
| SOURCE_RUN_END_TIMEOUT | 模型是否在 accepted=true 后继续工作或轮询；源 run 是否真正终止 |
| SOURCE_RUN_FAILED_OR_UNKNOWN | 源 run 失败、取消或 Gateway 重启后身份状态不确定 |
| SESSION_BOUNDARY_CHANGED / SESSION_CHANGED | 是否有人在等待或摘要期间重置/更换了会话 |
| INCOGNITO_SESSION_UNSUPPORTED | 这是临时会话；其 reset 语义不符合保留原会话的要求，请在普通持久会话运行 |
| ANOTHER_RUN_ACTIVE | 同一会话中观察到其他活动 run；不要强行 reset |
| INVALID_SUMMARY / CHECKPOINT_BUILD_FAILED | 摘要 JSON 是否符合要求，接口是否可用；部分内部模型/网络错误会统一折叠为构建失败 |
| CHECKPOINT_ARCHIVE_FAILED / CHECKPOINT_PERSIST_FAILED | 磁盘写入、权限、空间或 SQLite 提交是否失败 |
| SKILL_ARCHIVE_FAILED / SKILL_ARCHIVE_CHANGED | 配置的 Skill 是否可读，归档副本是否在提交后被修改 |
| CONTINUATION_REQUIRES_ATTENTION | 卡点已生成，但 reset 或后续提交需要核查；继续查看回执和对应日志 |

回执状态的解释：

| receipt.status | 可以得出的结论 | 不能直接假定 |
| --- | --- | --- |
| 无回执 | 尚无本地 reset 进度记录 | 不能仅凭缺失文件证明所有外部动作从未发生 |
| reset_requested | 代码已记录准备 reset，调用是否到达 Gateway 需继续查证 | 不等于 reset 已成功，也不等于未执行 |
| reset_confirmed | Gateway 返回了符合预期的新上下文代次 | 不证明下一阶段已提交 |
| submitted | 下一轮提交已返回 run_id | 不证明下一阶段业务已完成 |

崩溃后 working/held 不会自动重放，因为外部 reset 或提交可能已经成功。先保留文件，核对 job、回执和 Gateway 状态；状态长期不变或等待超时本身不能证明进程已经退出。

对于“卡点已落盘，但 worker 在开始 reset 前退出”的窄范围故障，可从外部终端执行：

    node "<Hook安装目录>/checkpoint.mjs" recover --job "<实际 job_id>"

recover 会逐项检查，只有全部满足才重新排队并启动后台 worker：

1. job 处于 queued、working 或 held，且保存了旧 worker PID。
2. 系统明确确认该 PID 不存在。PID 仍存在、被其他进程复用或无法确定时均拒绝。
3. 已观察到源 run 正常 ended，并且同一会话没有更新的 run 记录。
4. 对应 checkpoint 已完整提交到本地状态库。
5. delivery 仍为 pending，说明尚未开始 dispatch；或是非续跑卡点已经归档为 completed，仅需收尾状态。

成功响应中的 accepted=true、recovered=true 只说明恢复已入队。新 worker 仍会核查会话代次；进入交接时还会核查归档哈希、Skill 副本、用户输入和活动 run。之后从外部用 status 检查实际结果。

| 恢复代码 | 含义 |
| --- | --- |
| RECOVERY_JOB_NOT_ELIGIBLE | job 不处于可恢复状态，例如已经 done |
| RECOVERY_WORKER_ID_UNAVAILABLE | 没有可核查的旧 worker PID |
| RECOVERY_WORKER_STILL_PRESENT | 进程存在或无法可靠确认退出；不因超时绕过 |
| RECOVERY_SOURCE_NOT_CONFIRMED_ENDED | 无法确认源 run 正常结束 |
| RECOVERY_NEWER_RUN_EXISTS | 同会话已有更新 run，旧卡点不能继续覆盖会话 |
| RECOVERY_CHECKPOINT_NOT_PERSISTED | 没有完整持久化 checkpoint，不能只凭部分归档自动重建并执行 |
| RECOVERY_DELIVERY_AMBIGUOUS | delivery 已进入 dispatching、held、submitted 等状态，可能发生过 reset 或提交，不重放 |

recover 不是通用 retry，也不是暂停工作流的业务 resume。摘要失败尚未提交 checkpoint、源 run 未结束、reset 成败不明、已提交下一阶段等情况不符合这一恢复范围；不得通过修改数据库或手动调用 work 绕过判定。

对 reset_confirmed 但未确认提交的情况，操作者仍需根据真实 Gateway 状态判断下一轮是否已存在，再决定如何向原会话恢复保存的 prompt；本命令不会自动重放该不确定操作。

暂停或失败归档不会自动等待用户答复后继续。需要明确安排后续执行，再按真实状态处理。新一轮完全独立的任务若复用同一会话和同一 workflow_id，会命中已有阶段状态；应使用新的、已配置的 workflow_id（并同步 Skill）或单独的新任务会话。不要为重跑直接删除历史证据。

## 10. 用样例做一次端到端演练

[examples/README.md](../examples/README.md) 提供本地需求输入、三阶段 Skill、配置样本和各阶段产物样本。它不需要联网调研，但 Hook 摘要步骤仍会调用你配置的摘要接口。

先做本地代码检查：

    npm test

这组测试使用临时目录和模拟的 Gateway/摘要服务。它验证已覆盖的逻辑边界，不会 reset 你的真实会话。

部署后的人工验收依次核查：

1. Hook 可被发现且已启用，Gateway 重启后无加载错误；源 Skill 能读到本轮注入信息。
2. research 只完成本阶段，产物已落盘；request 返回 accepted=true 后源 run 结束。
3. 外部终端能观察任务从 queued/working 到 done，非终点归档文件齐全且摘要引用真实产物。
4. research 的 checkpoint 中 completed_stages 只有 research，next_stage 为 draft。
5. 原会话 sessionKey 保持一致，sessionId 改变；draft 的输入等于保存的 restart-prompt.md。
6. draft 能找到归档 Skill 和前一阶段产物，不重复 research；再次交接到 review。
7. review 完成后 completed_stages 包含三个阶段，workflow.status 为 completed；终点没有新 reset 或自动第四轮。
8. report.md 和 review.json 符合原始需求；不能用 examples/artifacts 中的静态样本冒充本次实际产物。

选做故障演练应在专用测试任务中进行：缺少摘要配置时请求拒绝；摘要失败时保留原上下文；阶段参数不符时拒绝；不存在本轮 token 时拒绝；源 run 不结束时不提前 reset。不要为了演练修改真实业务归档或共享生产状态目录。

完成这些核查后，才可以称“当前部署已通过真实 Gateway 端到端演练”。发布包自带的模拟测试结果与这项部署结论应分开记录。
