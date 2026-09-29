# 验证报告

验证日期：2026-09-28。目标 OpenClaw 2026.7.1，测试 Node v24.16.0。交付为独立 HOOK.md + handler.js + 配套脚本。

运行 npm test：**44 项通过，0 失败、0 跳过**。

| 测试文件 | 项数 | 验证范围 |
| --- | ---: | --- |
| coordinator.test.mjs | 16 | 三阶段流转、幂等、隔离、归档/提交失败、恢复；sessionId 迁移事务、冲突保护、持久化及重复迁移不覆盖新进度 |
| hook.test.mjs | 15 | 可信绑定、等待源 run、归档后 reset、新 sessionId 发送、终点停止、失败阻断和 Skill 快照；原始事件与当前分支分离、无 revision、未换 ID 和 reset 后再次换 ID 拒绝 |
| process.test.mjs | 2 | 真正运行默认 Hook、并发 CLI 和 detached worker；外部 HTTP 与缺省 Agent 摘要；新 sessionId 无 lifecycleRevision，下一阶段保留原始输入和完成进度 |
| recovery.test.mjs | 5 | 真实测试进程 PID、pending 恢复、活进程及不确定投递拒绝重放 |
| summarizer.test.mjs | 6 | 缺省/空/旧模板配置、绑定 Agent 模型与认证、错误脱敏、部分外部配置拒绝、取消处理 |

跨进程测试运行真实业务代码、SQLite、归档、哈希和子进程调度；OpenClaw SDK、Gateway、模型与 transcript 分支解析使用测试替身。外部模式连接 loopback HTTP；默认 Agent 模式不设置独立摘要密钥，验证公开模型准备/完成函数调用，并确认没有请求外部摘要 HTTP 服务。

测试断言 reset 前已归档公共事件、原始用户输入和源阶段最后一条回复；发送内容与保存的 prompt 完全一致；sessionKey 不变、sessionId 更新，终点只归档。源 checkpoint 身份不变，后续进度属于新 sessionId。

已核对真实 npm 2026.7.1 包公开导出和实现，详见 [运行时能力](runtime-capabilities.md)。另执行 JS/MJS 语法、JSON、本地 Markdown 链接和无插件注册检查。

本次未连接用户真实 Gateway，未使用真实模型凭据，也未重置业务会话。真实认证、摘要语义质量、宿主窗口/历史显示、原生分支解析完整行为与模型遵守停止约定仍须通过 [部署演练](../examples/README.md) 验证。公共 API 缺少原子 reset/发送身份条件，不能声称消除了并发竞态。
