# 当前认证版本验证

2026-09-09，X-Cookie + X-User-Account 版本：**23 passed，12.22 秒**。

覆盖双头必填、空值/重复头/控制字符拒绝、完整 X-Cookie 保留、敏感字段 repr 脱敏、Router 与 Domain 账号绑定、请求间 Cookie jar 隔离，以及真实多进程 MCP 初始化、故障重启和优雅退出。真实后端校验仍为待接入适配器，测试使用假认证结果。仍有两条原有第三方弃用警告。

以下为上一版 M Token/Cookie 入口的历史测试记录：

2026-09-08，Windows / Python 3.14.4，**19 passed，12.41 秒**。

使用工作区临时目录运行 pytest（系统临时目录的旧缓存权限受限），禁用 pytest 缓存。验证 M Token/Cookie 提取、重复/冲突凭证拒绝、无关 Cookie 过滤、凭证 repr 脱敏、认证失败与超时、可信主体校验、默认适配器 503、Domain 独立校验、操作 scope、HTTP 代理，以及真实多进程启动、MCP 初始化、故障重启和优雅退出。

真实多进程测试使用只生成在测试临时目录的假认证适配器，生产包不提供测试令牌或免鉴权配置。测试未调用 OpenCloud 或你们的真实认证接口；过期/撤销等业务判定仍由后续适配器实现。

仍有两条第三方弃用警告（Starlette/httpx TestClient 与 AnyIO BlockingPortal 别名），不影响测试结果。

---

以下为旧 JWT 版本的历史验证记录，不代表当前认证方式：

## 历史验证记录

2026-09-08，在 Windows / Python 3.14.4 上执行 `python -m pytest -q`：**8 passed，9.96 秒**。

实际依赖：FastMCP 3.4.7、MCP SDK 1.30.0、Starlette 1.6.0、httpx 0.28.1、PyJWT 2.13.0、uvicorn 0.52.4。

验证范围：JWT 有效/过期/issuer/audience/租户字段、Domain scope、Tool scope、请求体限制、限流容量、代理头过滤与流式响应、后端连接失败、Domain MCP 初始化与空 Tool/Prompt 列表；真实 Supervisor 启动 Router 和三个 Domain，通过 Router 初始化全部 Domain，终止 Search 子进程后恢复就绪，CTRL_BREAK 后所有服务完成 application shutdown。

测试发现并修复 Windows Supervisor 未捕获 SIGBREAK 的问题。健康探测测试客户端超时调整为 5 秒，高于服务端探测的 2 秒，避免故障恢复期间超时边界竞争。

依赖库有两条弃用警告：Starlette TestClient 对 httpx 的支持未来迁移至 httpx2；AnyIO BlockingPortal 的别名弃用。当前不影响测试结果。Linux/macOS 信号分支尚未实机验证；具体业务 Tool、Prompt 和后端未实现，因此不包含业务验收或生产负载测试。
