# schematic_mcp

根据分享讨论的最终结论实现：统一 Router + Supervisor + 多 Domain 独立 FastMCP 进程。

```text
MCP Client → Router :8000 → Domain MCP 127.0.0.1:810x
                              ↓ Tool / Prompt
                            Service（数据权限）
                              ↓ BackendClient（接口待接入）
                            现有业务后端
Supervisor → 启动、退出监控、退避重启、优雅停止全部子进程
```

当前 search / files / github 是可启动的空 Domain；不注册虚构 Tool 或 Prompt。系统不存储 Agent Session、Memory、Checkpoint，MCP HTTP 使用 stateless 模式。

## 启动

Python 3.11+，在本目录执行（Windows PowerShell）：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[dev]'
# 修改 config.toml 中的 provider_factory，接入 auth_provider.py
.\.venv\Scripts\schematic-mcp.exe check
.\.venv\Scripts\schematic-mcp.exe serve
```

Linux/macOS 使用 `.venv/bin/schematic-mcp`。不需要 JWT、公钥、issuer 或 audience。认证接入见 [双请求头认证规范](docs/AUTHENTICATION.md)。

外部入口为 `http://127.0.0.1:8000/mcp/search`、`/mcp/files`、`/mcp/github`，使用 Streamable HTTP，同时附带 `X-Cookie` 和 `X-User-Account`。实际部署在 TLS 反向代理后。按需修改 Router 监听地址，Domain 始终仅监听 loopback。

Router 和 Domain 分别通过 AuthProvider 校验现有用户凭证，并获取服务端可信的用户、租户和权限；不解析 Token 内容，不采信客户端自报身份。当前没有真实认证接口约定，`auth_provider.py` 刻意保留待实现：无凭证返回 401，有凭证但认证尚未接入返回 503。服务进程可以启动，不会跳过鉴权。

每个 MCP HTTP 请求都需同时携带 `X-Cookie` 和 `X-User-Account`。完整 X-Cookie 原样传入认证适配器；可信认证结果中的账号必须与请求账号一致。具体规范见上述链接。

## 运行与边界

- `GET /healthz`：Router 存活；`GET /readyz`：聚合 Domain HTTP 健康状态，未全部就绪返回 503；不验证真实认证服务是否已接入。
- `schematic-mcp domain search` 或 `schematic-mcp router`：单独调试进程。
- Ctrl+C 停止 Supervisor，先发退出信号，超过 10 秒强制结束。Windows 使用独立进程组和 CTRL_BREAK。
- 子进程退出后指数退避重启，60 秒内最多重启 5 次；超预算停止整栈并报错，由外部服务管理器告警/恢复。其他 Domain 在普通故障重启期间继续服务。
- 监管器检测进程退出；运行中卡死由 readiness 探测反映，当前不根据探测自动杀进程。
- Router 单 worker；限流为内存固定窗口，每租户/用户/Domain 每分钟 120 次，最多 10000 个活动键，达到容量拒绝新键。多 Router 部署需替换为共享限流存储。
- 请求体上限 1 MiB；认证后读取；请求头采用白名单，生成新的 Request ID；保留 MCP 与追踪头，不转发客户端身份伪造头。默认无跨域授权。
- 代理连接超时 3 秒，读取空闲超时 60 秒；支持响应流式转发和断开清理。流开始后失败只能终止流；不自动重试 MCP 请求，避免重复写入。无状态模式不承诺跨请求服务端通知、采样或会话恢复。
- 日志记录请求 ID、Domain、响应状态，不记录 M Token、Cookie、请求体或业务结果。
- BackendClient 为契约，尚未实现具体 HTTP API；认证适配器、工具、Prompt、业务权限规则由你后续补充。

## 后续开发

其他 MCP Server 接入请阅读 [MCP Server 接入说明书](docs/MCP_SERVER_INTEGRATION.md)，包含可直接接入的模块方式，以及远程/stdio 服务所需的适配边界。

见 [扩展规范](docs/EXTENDING.md) 和 [认证接入规范](docs/AUTHENTICATION.md)。执行 `python -m pytest` 验证基础设施。

架构来源：[你的讨论](https://chatgpt.com/share/6aa00adb-353c-83ec-aadc-8658f77a9d57)。FastMCP 的 HTTP app 使用 `http_app(stateless_http=True)`，参照 [官方源码文档](https://github.com/PrefectHQ/fastmcp/blob/main/docs/deployment/http.mdx)。
