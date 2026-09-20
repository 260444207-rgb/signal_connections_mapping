# Workflow Checkpoint

OpenClaw 2026.9.2 / Node 24.15–24.x native plugin，参考 JustDo plan-mode 的重置交接流程。

## 实际流程

1. Skill 完成 A 后，单独调用 workflow_checkpoint。
2. **先归档本地上下文**：保存公开 transcript 的原始事件、可见消息及 session lifecycleRevision。
3. 提取原始用户输入（保留原内容），用当前 agent 模型提取任务完成状态、结果、约束、中间产物与下一阶段所需数据。
4. 生成并保存 restart-prompt.md；checkpoint 与 workflow/outbox 在 SQLite 同事务提交。
5. 返回工具结果，阻止来源 run 的后续工具，结束 A 的 run。
6. 后台工作器通过 agent.wait 确认来源 run 结束，补存最终上下文。
7. 调用官方 sessions.reset 清空模型上下文；确认返回的 sessionKey/sessionId 保留、lifecycleRevision 已变化。
8. 把已保存的 restart-prompt.md 原文通过 agent RPC 发回这个会话，开始 C。

这是**保存上下文后重置会话**，不调用 sessions.compact，也不依赖旧历史继续推理。
沿用原任务窗口和业务会话标识；模型上下文由 reset 清空。系统提示、已安装工具/Skill
仍由 OpenClaw 正常加载。JustDo 原有 patch 可保留界面中的旧聊天展示，但模型上下文
仍遵守 reset 边界；插件没有新增或修改这些 patch。

## 启动 prompt 包含什么

- 用户输入原文：初始需求及后续用户补充；过滤插件自身生成的 continuation 消息。
- 原始目标与验收条件。
- 已完成阶段、待完成阶段、当前应执行的下一阶段。
- 重要结果、决策、约束、阻塞项。
- 中间产物的类型、路径、用途，以及下一阶段需要的信息。
- 本地上下文归档路径，供缺少细节时按需查阅。

**不会把 A 的全部工具结果、聊天历史自动重新塞进 prompt。**
这里的“中间件”按中间产物与交接数据实现；原始产物文件仍在其原路径。

## 本地文件

插件服务提供的 stateDir 下：

```text
workflow-checkpoint/
  state.sqlite
  archives/cp_<hash>/
    context.json          # checkpoint 时的原始上下文，先于总结写盘
    checkpoint.json       # 提取后的结构化任务状态
    restart-prompt.md     # reset 后实际发送的 prompt
    context-final.json    # 来源 run 完全结束后的最终上下文
    restart-receipt.json  # reset_requested / reset_confirmed / submitted
```

文件通过临时文件、fsync、rename 和 SHA-256 回读校验保存。
归档/状态持久化失败不 reset；本地归档或 prompt 被改动后不自动 reset。
SQLite 使用 WAL + synchronous FULL；checkpoint、workflow state、continuation outbox
同事务提交。文件写入先于事务，因此失败时可能留下可恢复的归档，不会留下允许执行
下一阶段但没有归档的成功状态。

## 安装与配置

将本目录放入 openclaw-extensions/workflow-checkpoint。向现有配置合并以下内容，
保留已有 plugins.allow、load.paths 和 entries：

```json
{
  "plugins": {
    "allow": ["workflow-checkpoint"],
    "load": { "paths": ["D:/github/JustDo/openclaw-extensions/workflow-checkpoint"] },
    "entries": {
      "workflow-checkpoint": {
        "enabled": true,
        "config": { "workflows": { "research-report": ["A", "C", "D"] } }
      }
    }
  }
}
```

重启 Gateway 后生效。agent 工具策略需要允许 workflow_checkpoint，prompt hook
需要保持启用。Gateway RPC 读取本地认证配置，agent.wait 需要 operator.read，
sessions.reset 需要 operator.admin，agent 需要 operator.write；不写死凭据。
未修改默认插件清单，也未自动启用或操作运行中的会话。

## Skill 触发条件

只由显式机器协议触发，不识别“阶段完成”等文字，不按 token 数自动触发。
等待 A 的其他工具全部结束后，单独调用：

```json
{"workflow_id":"research-report","stage_id":"A","status":"completed","next_stage":"C","reason":"stage_boundary"}
```

成功后立即结束当前 run，不能马上做 C。C 完成后同样 checkpoint 到 D。
最后一阶段 completed 不传 next_stage，只归档并完成流程，不 reset。
paused/failed 不推进阶段、不自动 reset；后续完成后可提交 completed。
完整样例见 examples/SKILL.md。

阶段顺序由配置决定；state_hint 是非权威提示，不能据此跳阶段。
幂等键包含 agent、sessionKey、sessionId、workflow、stage、status 和 revision 1。
重复 checkpoint 不重置、不再发送 C；重跑完整任务需配置新的 workflow ID。

## 异常和恢复

- 归档后发现新用户输入：保留状态，暂停售话重启，避免遗漏新指令。
- 发现外部 reset（即使 sessionId 没变，lifecycleRevision 已变化）：拒绝本次交接。
- reset 失败：不会发送下一阶段 prompt，保留本地文件。
- reset 已成功但发送失败：保留 restart-prompt.md 与 receipt，可确认后在原会话恢复。
- 启动时扫描 pending 尝试恢复；只有能确认来源 run 已正常结束时才继续 reset。
  若 Gateway 重启后来源 run 状态无法确认，则 held，不能声称全自动恢复。
- 已发出 reset/agent 请求但确认丢失：held，不盲目重发；避免重复 reset 清掉已开始的 C。

人工恢复前确认旧 run 已结束，查看 receipt，必要时把 restart-prompt.md 原文发送到
原会话。不要重新提交 A 来强行触发第二次 reset。

sessions.reset 没有插件可传的 expectedLifecycleRevision 条件。本插件在调用前检查
revision 和用户消息，但不能消除“检查后、RPC 执行前”并发外部操作的全部竞态；
生产环境应避免在自动交接窗口同时手动 reset 或发起另一 run。

## 验证与边界

```powershell
npm install --ignore-scripts
npm test
# 类型检查需可解析真实 SDK：
npm install --no-save --ignore-scripts openclaw@2026.9.2
npm run typecheck
```

20 项自动化测试通过，严格 TypeScript 检查通过，使用官方 2026.9.2 的类型。
包含归档/数据库失败、阶段链、幂等、并发锁、reset 请求顺序、归档损坏、新用户输入、
外部 reset、reset 失败不发 C，以及“原始 A 工具数据在归档中，但不在启动 prompt 中”。
SDK 调用测试使用 mock；尚未在真实 Gateway + 模型完成端到端验证。

摘要是模型抽取结果，schema 校验不能证明事实完整性；长上下文超过 4,000,000 字符
明确失败，不静默截断。已经启动的并行工具无法靠本插件撤回，所以 checkpoint 必须
单独调用。任意工具动作的阶段语义依赖 Skill 指令；状态转换本身强制校验。
本版不支持 rollback 或任意 DAG。升级 OpenClaw 需先验证 adapter 再调整版本检查。

公开接口与源码证据见 docs/runtime-capabilities.md。
