# 其他 MCP Server 接入 schematic_mcp 说明书

版本：1.0｜日期：2026-09-09｜适用对象：MCP Server 开发者、平台接入及运维人员。

本文以当前项目实现为准。文中 `inventory` 是新增服务示例，不会自动修改配置或注册业务能力。所有命令默认在项目根目录执行。

## 1. 接入方式与支持范围

**当前直接支持的是“Python 注册模块接入”：接入方提供 `register(mcp)`，平台创建 FastMCP 实例，并将该模块运行在独立 Domain 进程中。**

当前不是可以登记任意 MCP URL 的通用服务网关。配置中的 `module` 是 Python 模块导入路径，不是 URL、脚本路径或启动命令。

| 接入方现状 | 当前可用路径 | 是否需要修改平台 |
| --- | --- | --- |
| 新建 Python Domain | 按本文新增注册模块并配置 registry | 通常不需要 |
| 已有 Python/FastMCP Server，源码可改 | 抽取能力注册与业务逻辑，交给平台创建的实例注册 | 通常不需要；资源生命周期需另行评估 |
| 独立发布的 Python 能力包 | 在平台同一环境安装，暴露可导入的 register | 通常不需要 |
| 已部署的远程 HTTP MCP Server | 设计远程服务路由扩展或新增 MCP 客户端桥接 Domain | 需要开发，尚未实现 |
| stdio MCP Server、Node.js/Java 服务 | 抽取业务 API 后接入，或设计协议桥接/外部进程管理 | 需要开发，尚未实现 |

FastMCP 实例挂载、远程代理、stdio 桥接都不是当前配置已提供的功能。不要直接增加 `url`、`command`、`transport` 等未定义字段。

## 2. 运行架构与职责

```text
Agent / MCP Client
  │ Streamable HTTP + X-Cookie + X-User-Account
  ▼
Router :8000 /mcp/inventory
  │ 身份校验、账号绑定、Domain scope、限流、请求大小限制
  │ HTTP 转发到固定本机地址
  ▼
Inventory Domain 127.0.0.1:8104 /mcp
  │ 独立认证、账号绑定、MCP 协议、Tool/Prompt scope
  ▼
InventoryService → 数据/对象权限 → Integration Client → 现有业务系统

Supervisor：启动 Router 和所有 Domain；监控进程退出、退避重启、统一停止。
```

每个 Domain 具有自己的 FastMCP 实例、内部端口和进程。Client 通过 `/mcp/<domain>` 分别连接；当前没有跨 Domain 汇总的 `/mcp` 能力目录，也不会在一次 `tools/list` 中合并所有 Domain 的工具。

| 层级 | 平台负责 | 接入方负责 |
| --- | --- | --- |
| Router | 认证入口、Domain 权限、分流、限流、流式响应代理 | 提供 Domain 名称及入口 scope |
| Domain | 创建 FastMCP、HTTP 入口、认证包装、健康路由 | 注册能力、声明 schema、添加操作 scope |
| Service | 提供上下文与数据授权契约 | 用例逻辑、租户隔离、对象访问校验 |
| Integration Client | 提供后端契约 | 实际业务 API、凭证注入、错误映射、超时与资源释放 |
| Supervisor | 子进程启动、重启和停止 | 保持注册模块可导入，不自行启动第二个 Server |

## 3. 接入前准备

接入方应提供以下信息：

| 项目 | 示例或要求 |
| --- | --- |
| Domain 名 | `inventory`，满足 `[a-z][a-z0-9_]*` |
| 内部端口 | `8104`，不得与 Router 或其他 Domain 重复 |
| Python 模块 | `schematic_mcp.domains.inventory` 或已安装第三方包的模块路径 |
| Domain scope | `mcp:inventory` |
| 操作 scope | 如 `inventory:read`、`inventory:write`，由服务端权限策略授予 |
| 能力清单 | Tool/Prompt 名称、版本、输入输出、读写属性、幂等性 |
| 身份服务 | 能校验 X-Cookie 与账号，并返回可信身份和权限 |
| 业务依赖 | 后端地址、运行配置、超时、凭证用途、外部资源生命周期 |
| 验收信息 | 测试账号、授权/无授权场景、期望结果；交接文档不含真实凭证 |

项目声明 Python 3.11+、FastMCP `>=3.4.7,<4`；依赖范围以 `pyproject.toml` 为准。已有服务需要与平台使用的运行环境和依赖兼容。当前独立进程并不意味着独立虚拟环境或独立依赖版本。

## 4. 新建一个 Domain

### 4.1 文件结构

```text
src/schematic_mcp/domains/inventory/
├── __init__.py       # 平台调用的 register(mcp)
├── tools.py          # Tool 注册
├── prompts.py        # Prompt 注册
├── schemas.py        # 输入输出模型
└── service.py        # 业务用例与数据权限
```

`__init__.py`：

```python
from .tools import register_tools
from .prompts import register_prompts

def register(mcp) -> None:
    register_tools(mcp)
    register_prompts(mcp)
```

`tools.py`：

```python
def register_tools(mcp) -> None:
    """在此注册本 Domain 的异步 Tool；具体实现由接入方补充。"""
    pass
```

`prompts.py`：

```python
def register_prompts(mcp) -> None:
    """在此注册版本化 Prompt；具体模板由接入方补充。"""
    pass
```

这三个文件形成可加载的空 Domain。暂未实现 Tool/Prompt 时，能力列表为空是预期结果，不应注册返回假数据的占位工具。

### 4.2 注册入口约束

- 必须提供同步 `register(mcp) -> None`，平台不会 await 它。
- 使用传入的 FastMCP 实例，不要在模块中另建实例后只向另一实例注册。
- 注册阶段只声明能力，不访问后端、不启动线程/子进程，不调用 `mcp.run()`、`uvicorn.run()` 或 `asyncio.run()`。
- `/mcp`、`/healthz` 和内部监听由平台管理，接入模块不要覆盖。
- 单个 Domain 内能力名称不得冲突。注册失败会导致该 Domain 启动失败。

### 4.3 添加配置

在根目录 `config.toml` 增加：

```toml
[domains.inventory]
port = 8104
scope = "mcp:inventory"
module = "schematic_mcp.domains.inventory"
```

平台据此生成：

| 项目 | 地址或行为 |
| --- | --- |
| Client 入口 | `http://127.0.0.1:8000/mcp/inventory` |
| Domain 内部 MCP | `http://127.0.0.1:8104/mcp` |
| Domain 存活探测 | `http://127.0.0.1:8104/healthz` |
| 启动子进程 | `python -m schematic_mcp.cli --config <绝对配置路径> domain inventory` |

无需在 Router 写新路由，也无需在 Supervisor 写新进程分支。配置没有热加载，变更后需要重启整栈。

### 4.4 安装与启动

首次准备环境，Windows PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[dev]'
.\.venv\Scripts\schematic-mcp.exe --config config.toml check
.\.venv\Scripts\schematic-mcp.exe --config config.toml serve
```

已有环境只需按依赖变更重新安装。独立能力包应预先安装到这同一个虚拟环境，例如安装经过审核的本地 wheel 后，将 `module` 指向其注册模块。

Linux/macOS 将 `.venv\Scripts\schematic-mcp.exe` 换成 `.venv/bin/schematic-mcp`。

只调试新增 Domain 时执行：

```powershell
.\.venv\Scripts\schematic-mcp.exe --config config.toml domain inventory
```

单独启动 Domain 不会启动 Router，也没有 Supervisor 的自动重启；不要与 `serve` 同时占用同一个端口。

`check` 只校验配置格式和端口等约束，不验证模块导入、业务 API 或真实认证是否可用。

## 5. 将已有 FastMCP Server 迁入

如果原服务形如“创建全局 FastMCP → 使用装饰器注册 → 执行 run”，迁入时：

1. 把装饰器注册部分收进 `register_tools(mcp)`、`register_prompts(mcp)`。
2. 保留已有 Service 和 schema，改成由注册函数引用。
3. 删除平台接入路径中的自行监听与 run 调用；原独立启动文件可以保留，但不得由注册模块在导入时执行。
4. 替换原 HTTP 会话身份获取逻辑，采用平台的 `principal_context`。
5. 补充 Domain scope、操作 scope 和数据权限映射。
6. 检查原服务是否依赖会话状态、初始化资源或私有请求头；不能默认这些行为会随注册函数迁入。

**生命周期需特别核对：当前 `register(mcp)` 没有配置化的 Domain 启动/关闭钩子，也不接受接入方已有 ASGI app。**平台负责自身 HTTP Client、认证适配器和 FastMCP 生命周期；接入方自己创建的数据库池、后台任务或业务 Client 不会自动被收集和关闭。

简单调用可以采用用完即关的异步上下文。需要长生命周期资源时，应先扩展 `domain.py` 的工厂契约，明确异步启动、依赖注入和关闭顺序，并增加退出测试；不能只在模块全局创建资源就视为接入完成。

## 6. 认证与权限规范

### 6.1 Client 必须传两个头

```http
X-Cookie: <用户当前完整凭证>
X-User-Account: <用户账号>
```

每个 MCP HTTP 请求均需携带，不能只在 initialize 时传一次。X-Cookie 为不透明字符串，保留空格和分号；普通 Cookie 或 Authorization 不替代它。

两个头缺失、空值、重复或格式非法返回 401。框架限制 X-Cookie 为 8192 字符、账号为 256 字符，当前接受可打印 ASCII。无需 JWT 或公钥。

### 6.2 可信身份来源

全局认证适配器由 `[auth].provider_factory` 配置。它调用现有认证服务，并返回：

```python
Principal(
    subject="后端确认的用户ID",
    tenant_id="后端确认的租户ID",
    scopes=frozenset({"mcp:inventory", "inventory:read"}),
    account="后端确认的账号",
)
```

以上仅演示数据结构，不是硬编码放行示例。账号必须来自可信校验结果，框架将其与 X-User-Account 精确比较。认证适配器不能直接复制客户端账号来伪造校验通过。

新增 Domain 后，必须在服务端权限映射中给相应用户/角色授予 `mcp:inventory`；只加 config 不会自动授予权限。每个 Domain 当前共用同一认证工厂配置，尚无按 Domain 单独配置认证工厂的字段。

当前真实认证调用仍留空：带齐两个头也会返回 503。完成实际接入前必须实现 `auth_provider.py` 或替换工厂。详见 [认证接入规范](AUTHENTICATION.md)。

### 6.3 操作权限与数据权限

Tool/Prompt 的权限装饰器次序示意：

```python
from schematic_mcp.security import require_scope

def register_tools(mcp):
    @mcp.tool
    @require_scope("inventory:read")
    async def read_inventory(item_id: str) -> dict:
        """示意签名：正式接入时补齐 schema、业务逻辑和数据权限。"""
        raise NotImplementedError("接入方补充")
```

此段仅说明装饰器位置，不建议将未实现工具注册到生产能力列表。正式输出使用明确的类型模型。

Tool 内可从 `principal_context.get()` 和 `request_id_context.get()` 构造 `CallContext`。Service 必须校验对象/租户访问权，不能将传入 item_id 视为授权依据。Prompt 同样声明操作 scope；它只生成模板，不隐式执行写操作。完整规范见 [能力扩展规范](EXTENDING.md)。

原始 Credential 当前不会注入 Tool/Service 上下文。若业务后端也需要 X-Cookie，应另行设计受限的请求级凭证注入；不能认为 Tool 已经能直接从 CallContext 取得 Cookie。

## 7. HTTP、流式响应与状态约束

| 项目 | 当前实现 |
| --- | --- |
| 外部路由 | `/mcp/{domain}`，不支持任意子路径 |
| 内部目标 | 固定 `127.0.0.1:<port>/mcp` |
| 方法 | Router 接受 GET、POST、DELETE；实际协议响应由 Domain 决定 |
| 传输 | FastMCP Streamable HTTP，`stateless_http=True` |
| 会话 | 不维护业务 Session/Memory/Checkpoint；不能依赖会话亲和或服务端跨请求状态 |
| 请求体 | 认证后读取，上限默认 1 MiB |
| 响应 | 流式转发；响应开始后失败只能终止流 |
| 超时 | Router 连接 3 秒、读取空闲 60 秒；认证调用默认每层 5 秒 |
| 重试 | Router 不重试 MCP 请求，避免重复写入 |
| 查询参数 | 当前不转发 query string，不把认证或业务参数放在 URL |
| 其他服务路径 | OAuth 回调、下载地址等不会自动被代理 |

请求转发白名单：`Content-Type`、`Accept`、`Mcp-Protocol-Version`、`Mcp-Session-Id`、`Last-Event-ID`、`traceparent`、`tracestate`；另外加入本次认证的 X-Cookie、X-User-Account 和新生成的 X-Request-ID。

响应保留：`Content-Type`、`Mcp-Session-Id`、`Mcp-Protocol-Version`、`Cache-Control`、`WWW-Authenticate`、`Allow`、`Retry-After`，另附 Router Request ID。Set-Cookie 和 Location 不在白名单。原服务若依赖其他请求头、重定向或会话 Cookie，须明确设计后修改代理，不能假定透明兼容。

外部生产入口应部署在 TLS 入口后；内部 Domain 当前固定 loopback。不要把当前固定本机 HTTP 的配置直接理解为远程凭证传输方案。

## 8. 远程或非 Python MCP Server 的接入设计

本节是后续开发指引，**不是已经可用的配置功能**。

### 方案 A：迁移业务能力，使用平台 Domain

适用于能修改源码或已有业务 API 的服务。复用业务逻辑/API，按第 4～6 节注册本地能力。改动边界最清楚，可沿用现有监管与权限机制。

### 方案 B：新增本地桥接 Domain

```text
Router → 本地 Bridge Domain → MCP Client → 既有 HTTP/stdio MCP Server
```

桥接方需实现下游连接及关闭、工具/Prompt schema 映射、结果和错误映射、权限映射、请求级身份传递、超时取消及失败恢复。对于 stdio，还需明确谁创建和终止下游子进程。平台当前未提供这些实现。

不要把一个用户的下游会话、默认请求头或 Cookie jar 复用于另一个用户。不能直接将全局 X-Cookie 发送给不在信任范围内的第三方服务；下游若使用服务凭证或另一种身份机制，应显式转换。桥接不是普通 HTTP 代理，MCP 调用和结果需要遵循下游协议。

### 方案 C：扩展 registry，直接路由到外部服务

至少需要共同修改以下部分：

| 位置 | 必须新增的能力 |
| --- | --- |
| `config.py` | 区分本地模块/外部 endpoint、校验地址及传输配置 |
| `router.py` | 可配置目标 URL/路径、明确头与查询参数规则、TLS、身份转换及超时 |
| `supervisor.py` | 外部服务不再按 Python Domain 启动，或提供明确的外部进程管理模式 |
| 健康探测 | 外部存活/就绪探测地址、认证策略、失败处理 |
| 权限层 | 确保外部服务校验身份与操作权限，防止只通过 Router 即绕过权限 |
| 测试 | 远端失败、账号隔离、流式断开、状态会话与协议兼容性 |

只增加一个 URL 字段不足以完成该方案。本次说明书不改动上述运行时代码。

## 9. 联调与验收

### 9.1 启动与健康

启动整栈后检查 Router `/healthz` 和 `/readyz`。新增 inventory 后，readyz 返回的 `domains` 中应有 `inventory: true`。这只证明 HTTP 健康端点可达，不证明认证服务或业务后端可用。

### 9.2 MCP 协议联调

Client 连接 `/mcp/inventory`，在所有请求附加两个认证头，使用 Streamable HTTP。顺序为：initialize → notifications/initialized → tools/list、prompts/list → 实际能力调用。客户端应处理协议版本协商和响应 Content-Type；不能把 SSE 响应直接当普通 JSON 解析。

initialize 请求体示意：

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "initialize",
  "params": {
    "protocolVersion": "2025-03-26",
    "capabilities": {},
    "clientInfo": {"name": "integration-check", "version": "1.0"}
  }
}
```

该版本是本项目已有测试使用的示例值，并非固定服务端协议版本要求；按 initialize 响应与客户端能力完成协商。请求 Content-Type 为 `application/json`，Accept 包含 `application/json, text/event-stream`。

### 9.3 验收清单

| 场景 | 预期 |
| --- | --- |
| 模块注册与启动 | 服务进程正常，inventory 健康状态可见 |
| 有效凭证且具备 scope | 初始化成功，能力列表符合实际注册 |
| 缺少任一认证头、重复头 | 401 |
| Cookie 与账号不匹配 | Router 和直连 Domain 均拒绝，401 |
| 缺 Domain scope | 403，不执行工具 |
| 缺操作 scope | MCP 错误，不执行对应业务操作 |
| 跨租户/无对象权限 | Service 拒绝，后端不得泄漏数据 |
| 认证接口不可用 | 503，无假放行 |
| 后端超时/业务异常 | 安全错误，无凭证或堆栈泄漏 |
| 多用户交替/并发调用 | 身份、Cookie、结果均无串号 |
| 写操作重复请求 | 满足声明的幂等性，不依赖 Router 自动重试 |
| Domain 退出 | 由 Supervisor 重启，其他 Domain 在普通重启期间继续工作 |
| 整栈停止 | 所有拥有的资源和子进程退出 |

运行现有基线测试：`python -m pytest -q`。截至本说明书编写，现有 23 项测试验证的是平台基线和临时假认证适配器；新增 Domain 仍需新增自身用例，并完成真实认证及业务联调。

## 10. 运维与问题定位

Supervisor 默认在 60 秒窗口内最多重启 5 次，退避延迟上限 30 秒；重启预算耗尽时停止整栈，而不是永久忽略故障 Domain。关闭宽限期为 10 秒。当前只自动处理进程退出，不自动杀掉健康探测失败但仍存活的进程。

Router 限流为单 worker 内存固定窗口，默认每租户/用户/Domain 每分钟 120 次，容量 10000 个活动键。扩容多个 Router 时需单独设计共享限流。

| 现象 | 优先排查 |
| --- | --- |
| 404 unknown_domain | config 中名称与请求路径是否一致，是否重启加载配置 |
| 模块导入失败 | 包是否安装到运行解释器，module 是导入路径还是误填文件路径 |
| 启动后不断重启 | register 异常、端口占用、依赖冲突；查看启动日志 |
| 401 | 两个头是否完整、重复，Cookie 是否有效，账号是否精确匹配 |
| 403 | 身份映射是否包含当前 Domain scope |
| 503 authentication_unavailable | 默认适配器未实现，或认证超时/响应不符合契约 |
| 502 domain_unavailable | 内部进程是否存活、内部端口是否可达 |
| 504 domain_timeout | Domain 在响应开始前是否超时 |
| tools/list 为空 | 是否仍为空骨架，是否向平台传入的 mcp 实例注册 |
| Tool 报权限错误 | require_scope 是否与服务端角色映射一致 |
| 浏览器/原 Client 接入失败 | 是否依赖被过滤的头、查询参数、其他路径或状态会话 |

用 Router 返回的 X-Request-ID 关联请求。不要为定位问题打印 X-Cookie 或真实账号凭证组合。

## 11. 接入交付物

接入完成应提交：注册模块及依赖变更、Domain 配置、能力清单及 schema、权限映射、后端配置说明、生命周期设计、测试报告和运行回退步骤。敏感配置通过部署环境提供，不写入说明书或示例代码。

移除 Domain 时，先协调 Client 停止使用，再删除配置项并重启整栈。当前没有热摘流或按配置局部重载能力；停止过程中的在途请求可能中断。代码和依赖的移除按正常发布流程进行。

实现依据：`config.py`、`domain.py`、`router.py`、`security.py`、`supervisor.py`、`cli.py`、现有测试，以及本项目 [认证规范](AUTHENTICATION.md) 和 [扩展规范](EXTENDING.md)。
