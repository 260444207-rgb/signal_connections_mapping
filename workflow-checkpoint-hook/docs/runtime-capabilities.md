# OpenClaw 2026.7.1 运行时能力核查

本 Hook 仅接受 openclaw@2026.7.1，Hook 自身要求 Node >=24.15 <25，不修改宿主项目的 OpenClaw 依赖版本。核查使用 npm 原始发布包，SHA512 为 `ge/Xss99CHAjPL/ikmH/UFoiOrjcxDB4sW3y9mhyCD+dYW3wzV7TKbAVdkrXFgAG2d2BjpJofP97zUZ+umxo8g==`。

| 能力 | 实现与限制 |
| --- | --- |
| 独立 Hook | HOOK.md + handler.js；agent:bootstrap 注入 CLI 路径/token。没有插件 manifest、自定义工具、agent_end 文件 Hook 事件或工具拦截器 |
| 生命周期 | agent-harness-runtime 的 onAgentEvent，绑定可信 agentId/sessionKey/sessionId/runId；CLI 接受后 Skill 必须结束当前轮 |
| 当前会话 | session-store-runtime 的 getSessionEntry；边界优先使用 lifecycleRevision，缺失时使用 sessionId |
| 完整归档 | session-transcript-runtime 的 readSessionTranscriptEvents；不包括隐藏推理或未持久化内存 |
| 当前分支 | agent-core 的 SessionManager.open(...).getBranch()。解析临时本地副本，避免打开真实 transcript 时发生修复/迁移；保留当前分支原始消息、压缩及分支摘要证据，原始全量 events 另存归档 |
| 源 run 确认 | 生命周期结束后，再调用公开 agent.wait 验证 status=ok |
| 原会话重置 | sessions.reset 保留 sessionKey、创建新的 sessionId。验证后事务迁移进度；checkpoint 和原始证据保持源身份 |
| 续跑 | agent RPC 显式传相同 sessionKey、新 sessionId、固定 idempotencyKey；message 等于保存的 prompt |
| 并发边界 | reset 没有 expectedRevision，agent 没有 expectedExistingSessionId。发送前检查不能提供原子保证，交接期间不要并行发送消息 |
| 默认摘要 | agent-runtime 的 prepareSimpleCompletionModelForAgent、completeWithPreparedSimpleCompletionModel；config-runtime 的 loadConfig。按绑定 Agent 选择主模型和认证，useUtilityModel=false；不创建新 Agent 会话 |
| 可选外部摘要 | 配置 summarizer.baseUrl/model/apiKeyEnv 时使用 OpenAI-compatible HTTP；配置不完整、认证或服务失败不静默回退 |
| 恢复 | 只恢复旧 worker 已退出且尚未 dispatch 的持久卡点；不确定 reset/发送禁止盲目重放 |

默认摘要读取后台可见的 OpenClaw 文件配置，不继承当前会话临时模型覆盖或 Gateway 只在内存中修改的配置。SDK 负责提供者模型解析、auth profile/OAuth 等认证；部署时仍需验证实际账号和服务环境。

公开调用示意（reset/agent 有副作用，不应手动照抄执行）：

```js
sdk.getSessionEntry({ sessionKey, agentId, readConsistency: 'latest' });
await sdk.readSessionTranscriptEvents({ sessionKey, sessionId, agentId });
sdk.SessionManager.open(privateCopyPath, privateCopyDirectory).getBranch();
await sdk.callGatewayFromCli('sessions.reset', { timeout: '30000' },
  { key: sessionKey, agentId, reason: 'reset' },
  { progress: false, scopes: ['operator.admin'] });
await sdk.callGatewayFromCli('agent', { timeout: '15000', expectFinal: false },
  { sessionKey, agentId, sessionId: newSessionId, idempotencyKey,
    message: savedPrompt, deliver: false },
  { progress: false, expectFinal: false, scopes: ['operator.write'] });
```

源码定位：dist/agent-events-CRggPZCM.js、dist/session-store-runtime-WGOSL-_8.js、dist/session-transcript-runtime-icobTS5c.js、dist/session-manager-BKz2VYho.js、dist/session-reset-service-DCAn5wjx.js、dist/schema-BuOFpc7K.js、dist/simple-completion-runtime-Dh4VRlEc.js。这些散列文件仅用于核查，生产代码只导入 openclaw/plugin-sdk/* 公开子路径。

升级前重新核查导出、身份、分支投影、reset/发送参数和模型认证接口，再修改版本闸门。替身测试不等于真实 Gateway 已通过部署验收。
