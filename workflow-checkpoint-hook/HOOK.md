---
name: workflow-checkpoint
description: "在 Skill 卡点归档上下文，重置原会话并通过保存的 prompt 续跑。配套脚本默认复用注册 Agent 模型。"
metadata:
  { "openclaw": { "events": ["gateway:startup", "gateway:shutdown", "gateway:pre-restart", "agent:bootstrap"], "requires": { "bins": ["node"] } } }
---

# Workflow checkpoint Hook

这是独立文件 Hook，入口为 handler.js；不使用插件 manifest、registerTool 或 api.on。

启动时订阅公开 onAgentEvent 观察实际 run；agent:bootstrap 向本轮 AGENTS.md 注入运行绑定 token 与脚本路径。Skill 在卡点调用 checkpoint.mjs request，收到 accepted=true 后立即结束本轮。后台 worker 等待源 run 结束，归档、摘要、持久化启动 prompt，再 reset 同一会话并提交下一阶段。

安装配置见 README.md；改造 Skill 见 docs/skill-checkpoint-adaptation.md。
