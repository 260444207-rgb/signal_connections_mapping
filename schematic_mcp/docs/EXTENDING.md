# 扩展规范

## 分层约束

Router 只处理入口身份与 Domain scope、限流、转发。禁止在 Router 解析 tools/call 或编写业务权限判断。

每个 Domain 包必须提供同步 `register(mcp) -> None`。注册过程只声明能力，不访问网络、创建子进程或读取业务数据。业务接口由异步 Tool 调用 Service，Service 校验对象/租户权限后调用 BackendClient。Prompt 返回模板，不执行写操作。

新增 Domain：复制任一空 Domain 包，改 Service 类名，在 config.toml 添加唯一名称、内部端口、入口 scope 和模块名。Supervisor、Router 自动读取同一 registry；不再修改中央路由代码。配置变更需重启整栈。

## Tool

1. 文件位于 `domains/<domain>/tools.py`，在 `register_tools` 内使用 `@mcp.tool` 注册。
2. 名称采用明确动作的 snake_case；函数必须 async，参数和返回值完整标注类型，docstring 写清用途、限制和副作用。使用明确 Pydantic 模型，`extra='forbid'`，给字符串长度、分页数量、枚举设界限。不要以任意 dict 代替公开业务 schema。
3. `@require_scope('search:read')` 放在 `@mcp.tool` 下方。每个 Tool 都需显式操作权限，不能仅依赖 Domain scope。读写 scope 分离。
4. 身份从 `principal_context.get()` 获取，不能由 Tool 参数传入可信 user_id、tenant_id。构造 CallContext 后传给 Service，业务参数和输出中不携带原始 M Token/Cookie。
5. Service 必须执行 DataAuthorizer.require_access；搜索场景同样需要数据过滤/后端授权，不允许先获取跨租户数据再返回。未配置数据授权默认拒绝。
6. Tool annotation 的 readOnlyHint/destructiveHint/idempotentHint 按真实行为填写；这些是提示，不替代鉴权。
7. 预期业务错误映射为安全错误；不得把后端响应全文、凭证或堆栈作为 Tool 结果。基础服务已启用 mask_error_details。

示意签名（不自动注册，函数体由你补）：

```python
@mcp.tool
@require_scope("search:read")
async def search_documents(query: str, limit: int = 20) -> SearchResult:
    """搜索当前主体可访问的文档，最多返回 limit 条。"""
    ...
```

## Prompt

在 `prompts.py` 的 `register_prompts` 注册 `@mcp.prompt`，下方同样加 require_scope。用 `purpose_v1` 等名称做显式版本；参数必须具名、有类型和长度限制，不接收任意模板代码。返回 FastMCP 支持的字符串或 PromptMessage 列表。

模板文本放本 Domain 的 `templates/`，以 UTF-8 保存，发布前补充打包 package-data 配置。用户变量视为数据，不可改变权限或工具集合。模板不得含密钥，不在渲染时隐式请求后端或写数据。schema 或模板语义的破坏性变更使用新版本，记录迁移说明。

每个能力在同目录能力清单中记录：名称、版本、说明、输入/输出 schema、所需 scope、是否写入、幂等性、超时、错误、维护人。Prompt 另记模板版本与变量。当前空能力不编造清单条目。

## 后端适配

实现 `BackendClient.execute`，允许按 Domain 分别适配，无须另建 Backend Gateway 服务。将 operation 映射到固定方法和路由，不允许客户端提供任意 URL。通过生命周期管理 httpx.AsyncClient 连接池和关闭，显式超时；重试仅用于已确认幂等的调用并限定次数。写操作需业务幂等键及后端支持后才能重试。

认证适配器将 X-Cookie 与 X-User-Account 一起交给固定的可信身份接口校验，见 AUTHENTICATION.md。业务后端若也需要该用户凭证，应在 Integration Client 单独设计请求级凭证注入，限定接收服务，不把 X-Cookie 或凭证放进业务 schema、日志或返回结果。当前 BackendClient 仅含业务上下文，尚未实现这部分转发；也可按后端要求使用服务凭证。禁止将用户凭证保存为跨用户共享 HTTP Client 的默认 headers/cookies，避免串号。

## 验收

新增能力至少验证 schema/边界、正常调用、缺少 scope、跨租户拒绝、后端超时与安全错误；写操作验证重复请求语义。通过真实 HTTP MCP Client 检查能力发现与调用。Tool/Prompt 具体实现留空时，验收标准是进程可启动、初始化成功，能力列表为空。
