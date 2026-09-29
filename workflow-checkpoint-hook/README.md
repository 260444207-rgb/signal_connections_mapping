# Workflow checkpoint：独立 Hook + 配套脚本

针对 OpenClaw 2026.7.1，Node >=24.15 <25。没有 openclaw.plugin.json，也不注册 workflow_checkpoint 工具。

流程：Skill 完成配置中的阶段 → 脚本持久化交接请求 → Skill 结束当前轮 → 后台确认 run 已结束 → 本地归档完整可读 transcript（messages + events） → 提取用户输入、完成状态和中间产物引用 → 保存 restart prompt → reset 原 sessionKey 的上下文（sessionId 更新） → 发入保存的 prompt 执行下一阶段。A、C 不写死，由 config.json 的 stages 和 Skill 卡点决定。

详细操作见 [使用说明](docs/usage-guide.md)，直接改造 Skill 见 [卡点规范](docs/skill-checkpoint-adaptation.md)，从零演练见 [完整示例](examples/README.md)。公开 API 核查见 [运行时能力](docs/runtime-capabilities.md)。

## 安装

1. 将本目录完整复制到 ~/.openclaw/hooks/workflow-checkpoint（Windows 对应用户目录下 .openclaw/hooks/workflow-checkpoint）。
2. 编辑本目录 config.json。openclawPackageRoot 指向正在运行的 OpenClaw 安装包根目录（包含 package.json），不是 JustDo 项目根目录。若 Node 能直接解析 openclaw 公共导出，可以留空。
3. 默认无需配置 summarizer：后台读取 OpenClaw 配置，使用本轮绑定的注册 Agent 的主模型及其认证（包括 SDK 支持的 OAuth/auth profile）。确保后台继承与 Gateway 相同的配置路径、用户和认证环境。需要独立摘要服务时再显式配置 summarizer，详见使用说明。
4. stateDir 留空时使用 OPENCLAW_STATE_DIR 或 ~/.openclaw 下的 workflow-checkpoint-hook。自定义必须为绝对路径。Gateway 与脚本须使用相同配置、用户和文件系统。
5. 若装过旧 workflow-checkpoint 插件，先禁用它，避免两套协调器同时处理。
6. 执行 openclaw hooks enable workflow-checkpoint，重启 Gateway。可用 openclaw hooks list 检查发现结果。
7. 按 docs/skill-checkpoint-adaptation.md 改造 Skill。

本包不修改 OpenClaw 核心，也不自动启用 Hook 或设置 API 密钥。公共 SDK 路径虽命名为 openclaw/plugin-sdk/...，这里仅导入公开运行时能力，不注册插件。

## 配置示例

config.json 默认 stages 为 research-report: research → draft → review。替换为实际 Skill 阶段。终点不传 --next。paused/failed 只归档，不 reset、不续跑。

建议配置 workflowSkills，将 workflow_id 映射到原 SKILL.md 的绝对路径。每次卡点会保存 Skill 副本及哈希，把恢复所需的 Skill 路径写入下一轮 prompt。

摘要模型必须返回结构化 JSON。接口无工具执行权限，摘要结果不得控制阶段跳转；跳转只取脚本参数与配置校验结果。摘要失败保留原上下文及已落盘归档，任务置 held。

## 状态与产物

脚本 request 返回 accepted=true 表示交接请求已入队，不等于归档或 reset 已完成。此时源 Skill 必须停止调用工具，以便 worker 等待的 run 能结束。后台默认最多等 15 分钟。

由另一个终端运行：node "<Hook目录>/checkpoint.mjs" status --job "<job_id>"。

queued：等待 worker；working：处理或等待源 run；done：卡点已处理（若有下一阶段，仅表示续跑已提交）；held：需要人工检查。源轮次不得轮询状态。

stateDir 中保存 bindings.sqlite、state.sqlite、logs 和归档目录。每次卡点包含 context.json、checkpoint.json、restart-prompt.md；发生交接时还保存 context-final.json 与 restart-receipt.json。文件名以实际归档路径为准。产物保存路径及用途引用，不自动复制所有外部文件；请保留中间产物原文件。

## 行为边界

- 独立 Hook 无 agent_end 内部事件，也不能注册工具或硬拦截源 Agent 的工具调用。它使用公开 onAgentEvent 观察生命周期；无法绑定可信 run 身份时拒绝请求。Skill 停止约定是必需条件。
- reset 使用 sessions.reset，保留 sessionKey，生成新的 sessionId；确认后原子迁移工作流进度，再发入启动 prompt。界面是否继续显示历史取决于宿主；JustDo 的既有历史保留行为不由本 Hook 修改。
- 只支持普通持久会话；对标记为 incognito 的记录保留拒绝保护。
- 归档范围是公共 transcript API 提供的完整记录，不包含服务端未公开的隐藏推理或未写入 transcript 的内存状态。
- 重置前检查会话代次、用户输入与其他活动 run。公共 reset 无 expectedRevision 原子条件，检查与 reset 之间仍存在极短竞态；交接时不要同时向原会话发送新消息。
- 不自动重放 working/held 的不确定任务。进程崩溃后先检查日志和 restart-receipt.json：reset_requested 可能已重置，reset_confirmed 表示已重置，submitted 表示已提交。避免重复 reset 或执行。
- 外部终端可执行 `node "<Hook目录>/checkpoint.mjs" recover --job "<job_id>"` 恢复已持久化但尚未开始 dispatch 的卡点。脚本必须确认原 worker PID 不存在、源 run 正常结束、没有更新 run。已开始 reset/发送的投递一律拒绝重放；详细条件见使用说明。
- 终点、暂停、失败卡点只归档。新一轮相同 workflow 若要从头执行，需使用新 workflow_id 或经核实后迁移状态；已有完成阶段不会重复。

## 验证

运行 npm test。测试使用临时本地目录和注入的 Gateway/摘要替身；不访问真实会话或模型服务。当前支持版本经过公开包源码核对，真实部署仍需配置后进行一次端到端演练。

本次 44 项自动测试的覆盖范围与未验证事项见 [验证报告](docs/validation-report.md)。
