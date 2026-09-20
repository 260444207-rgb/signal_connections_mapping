# Runtime capability investigation

调查更新：2026-09-19。以用户最新要求为准：A 上下文本地归档，提取启动 prompt，
reset 原会话上下文，再发送 prompt 启动 C。旧版“仅注入、不 reset”的选择已替换。

## 版本与证据

参考仓库 package.json 锁定 OpenClaw v2026.9.2；未找到运行中的 Gateway，不能把仓库
版本当作实际实例版本。插件注册时检查 api.runtime.version，限定 2026.9.2。
Node 使用 24.16.0 验证；要求 >=24.15 <25。

SDK 随 OpenClaw 同包，无单独版本号。已下载官方 npm 包并核验发布 integrity：
sha512-M6C7UsnX815nv26qBJFYGe6aGzv+ftZLRzV6S9oRXUtXg2Yn67eVntpssT94kgkquKVSeUxerUg0j1ONp4WYQg==

发布信息：https://registry.npmjs.org/openclaw/2026.9.2
该包不导出 openclaw/plugin-sdk 根入口，使用公开 openclaw/plugin-sdk/core。

## 能力

| 能力 | 状态 | 依据/实现 |
|---|---|---|
| 真实运行版本确认 | PARTIAL | 源码及发布包已核实；未连接真实 Gateway |
| 注册 Agent Tool | SUPPORTED | OpenClawPluginApi.registerTool(factory, options) |
| runtime identity | SUPPORTED | ToolContext / HookContext 的 sessionKey、sessionId、agentId、runId |
| 原始 transcript | SUPPORTED | readSessionTranscriptEvents(identity) |
| 可见消息 | SUPPORTED | readVisibleSessionTranscriptMessageEntries(identity) |
| 结构化状态提取 | SUPPORTED | api.runtime.llm.complete，当前 agent 凭据/模型 |
| agent_end / prompt 准备 | SUPPORTED | agent_end、agent_turn_prepare、before_agent_finalize |
| 明确清空模型上下文 | SUPPORTED | sessions.reset({key,agentId,reason:'reset'}) |
| 原业务会话续跑 | SUPPORTED | agent({sessionKey,expectedExistingSessionId,message,idempotencyKey}) |
| 等待来源 run 结束 | SUPPORTED | agent.wait({runId,timeoutMs})；只有 status=ok 才 reset |
| 无竞态条件 reset | UNSUPPORTED | reset 参数无 expectedLifecycleRevision；只有调用前检查 |
| Gateway 重启后不确定调用自动重放 | PARTIAL | 不证明远端去重跨重启持久；无法确认则 held |
| sessions.compact | SUPPORTED | 有公开 RPC，但不用于用户要求的 reset 交接 |
| 外部插件 scheduleSessionTurn | UNSUPPORTED | 文档标记 bundled-only；不用该接口 |

SUPPORTED 表示发布包中有公开契约，不等于真实实例端到端验收通过。

## 关于 sessionId 的纠正

2026.9.2 的实际 reset 实现：nextSessionId = currentEntry?.sessionId ?? randomUUID()。
已有 session 被 reset 时保留 sessionId，更新 lifecycleRevision，并追加 context:'clear'
的 reset boundary。因此不能用“sessionId 没变”证明上下文没变；本插件会检查并保存
lifecycleRevision，reset 后要求它发生变化。

参考 JustDo 的 src/main/engine/openclaw/openclawRuntimeAdapter.ts 中 plan handoff
也是 sessions.describe -> sessions.reset -> 检查原 sessionId 保留 -> runTurn。
原有 scripts/patches/v2026.9.2/022-justdo-reset-display-history.cjs 只保留 UI 历史展示，
注释与实现明确模型上下文仍受 reset 限制。本次没有新增运行时 patch。

## 发布包源码定位

- dist/plugin-sdk/core.d.ts：OpenClawPluginApi 等公共类型。
- dist/plugin-entry-BJ7nwfgz.d.ts：OpenClawPluginToolContext、PluginRuntimeCore.llm。
- dist/hook-runner-global-Bj0SlbYF.d.ts：hook context、block 与 finalize 返回契约。
- dist/plugin-sdk/session-transcript-runtime.js：原始事件与可见消息的公共导出。
- dist/session-transcript-runtime-unJeSCUF.js：readSessionTranscriptEvents、
  readVisibleSessionTranscriptMessageEntries 按 identity 读取 transcript 的实现。
- dist/plugin-sdk/session-store-runtime.d.ts：getSessionEntry 公共导出。
- dist/plugin-sdk/gateway-runtime.d.ts：callGatewayFromCli 公共导出。
- dist/src-BiL5aQto.js：SessionsResetParamsSchema、AgentWaitParamsSchema、AgentParamsSchema。
- dist/session-reset-service-DsSXKjai.js：resetSessionEntryLifecycle、context:'clear'、
  nextSessionId 保留逻辑、lifecycleRevision 更新；清理活动 run 需要等待其退出。

插件只导入公共 SDK，不导入带 hash 的内部文件。transcript SDK 该发布版未提供 d.ts，
src/transcript-sdk.d.ts 补充已核查的两个窄接口声明。

## 时序

workflow_checkpoint：snapshot -> context.json -> structured summary -> restart-prompt.md
-> checkpoint.json -> SQLite atomic commit -> return。

agent_end：安排后台工作后立即返回，避免在 hook 内等自己的 run 结束。
后台：agent.wait -> 最终 snapshot -> 校验用户消息/revision -> context-final.json
-> receipt(reset_requested) -> sessions.reset -> 验证 identity/revision
-> receipt(reset_confirmed) -> agent(message=本地 prompt 原文) -> receipt(submitted)。

文件或 reset 失败不 dispatch C。重启扫描 pending 仍要求确认来源 run 的终态；
无法确认时保持 held。reset/dispatch 应答不确定时不重试破坏性步骤。

## 官方文档与验证

- https://docs.openclaw.ai/plugins/sdk-overview
- https://docs.openclaw.ai/plugins/hooks
- https://docs.openclaw.ai/plugins/sdk-runtime/agent
- https://docs.openclaw.ai/gateway/protocol

版本证据优先采用发行包内 docs/plugins/*.md 与 docs/gateway/protocol.md，
线上文档可能更新。最小可执行验证为 tests/plugin.test.ts：mock 公开 SDK，检查调用
顺序 agent.wait -> sessions.reset -> agent，验证本地归档和启动 prompt 内容分离。
20 项测试与真实 SDK 的类型检查通过；真实 Gateway/模型测试尚未执行。
