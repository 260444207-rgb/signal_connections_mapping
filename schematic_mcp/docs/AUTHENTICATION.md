# X-Cookie + X-User-Account 认证

## 客户端协议

每次 MCP HTTP 请求（包括初始化、能力发现和工具调用）必须同时携带：

```http
X-Cookie: <用户的完整凭证字符串>
X-User-Account: <用户账号>
```

请求头名称大小写不敏感。两项缺一、为空、重复，或包含控制字符时返回 401。X-Cookie 最大 8192 字符，X-User-Account 最大 256 字符，目前接受可打印 ASCII。非 ASCII 账号如有需要，应与客户端约定编码后补充解析测试。

X-Cookie 被当作不透明字符串，保留其中的空格、分号和等号；不按普通 Cookie 头拆分，不猜测 M Token 所在字段。普通 Cookie、Authorization 或 X-M-Token 不能替代这两个请求头。凭证与账号不放到 URL、Tool 参数、Prompt 参数、日志或返回结果中。

## 服务端流程

```text
Agent → X-Cookie + X-User-Account
  → Router 读取 Credential(cookie, user_account)
  → AuthProvider 调用现有身份服务，验证凭证和账号关系
  → 返回可信 Principal(subject, tenant_id, scopes, account)
  → 比较 Principal.account 与 X-User-Account，并检查 Domain scope
  → 原样转发这两个头到对应本机 Domain
  → Domain 独立执行同样的认证和账号匹配
  → Tool/Prompt 权限 → Service 数据权限
```

X-User-Account 是待校验的账号声明，不是独立的可信身份证明。Principal.account 必须来自后端认证结果，不能直接从请求头复制。主体 subject 可以是内部用户 ID，与 account 不必相同。框架采用账号字符串精确比较；若实际身份系统有别名或大小写归一化规则，应明确规则后调整绑定校验，不能未经验证直接替换账号。

## 适配器契约

实现 `src/schematic_mcp/auth_provider.py` 的异步方法：

```python
async def authenticate(self, credential: Credential, *, request_id: str) -> Principal:
    # credential.cookie：X-Cookie 的完整值
    # credential.user_account：X-User-Account 的值（尚未验证）
    # TODO：调用现有认证服务，并从可信结果映射 Principal
    ...
```

Principal 的字段为 subject（用户 ID）、tenant_id（可信租户）、scopes（服务端权限集合 frozenset）和 account（经验证的账号）。如果后端只有角色，使用明确的服务端角色→scope 映射；如果没有租户，使用服务端固定的单租户标识。认证成功不等于拥有全部工具权限。

```toml
[auth]
provider_factory = "schematic_mcp.auth_provider:create_provider"
timeout_seconds = 5.0
```

无需 JWT、公钥、issuer 或 audience。当前未知真实认证接口的地址、方法和响应格式，因此认证网络调用仍为 TODO，默认返回 503，不会仅凭头存在就放行。

| 情况 | 行为 |
| --- | --- |
| 缺头、空值、重复头、格式错误 | HTTP 401 |
| 凭证无效、过期、撤销，或账号不匹配 | AuthenticationError / HTTP 401 |
| 服务不可用、超时或返回数据不符合契约 | AuthenticationUnavailable / HTTP 503 |
| 认证通过但无 Domain scope | HTTP 403 |
| Tool/Prompt 无操作权限 | MCP 调用错误 |

## 生命周期和隔离

每进程一个认证适配器，工厂不访问网络。使用异步网络调用，整个认证调用受 timeout_seconds 限制；aclose 在进程退出时释放连接。Router 和 Domain 每次各校验一次，当前不缓存认证结果。

认证请求只发往服务端配置的可信身份接口，禁止自动跨站重定向，按接口约定传递两个字段。不要将用户凭证存入共享 HTTP Client 默认头或跨用户 Cookie jar；按请求注入。Router 转发时不会合并共享 Cookie jar，也不转发普通 Cookie、无关 Authorization 或 Set-Cookie。

healthz/readyz 只检查服务进程，不表示真实认证已接通。测试使用临时假认证服务，未联调真实用户凭证。接通剩余所需信息：校验接口 URL、请求方法、成功/失败的脱敏响应，以及权限来源；无需提供真实 Cookie。
