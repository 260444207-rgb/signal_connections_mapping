from dataclasses import replace
from pathlib import Path
import pytest
from starlette.datastructures import Headers
from starlette.testclient import TestClient
from schematic_mcp.config import Settings, Domain, AuthSettings
from schematic_mcp.security import (authenticate, AuthorizationError, AuthenticationError, AuthenticationUnavailable,
                               principal_context, require_scope, Principal, extract_credential)
from schematic_mcp.router import create_router, RateLimiter
from schematic_mcp.domain import create_domain
import httpx


class FakeProvider:
    """Test-only identities. Never configured as a production provider."""
    def __init__(self):
        self.closed = False

    async def authenticate(self, credential, *, request_id):
        if credential.cookie == "valid":
            return Principal("alice", "a", frozenset({"mcp:search", "search:read"}), account="alice")
        if credential.cookie == "no-scope":
            return Principal("alice", "a", frozenset(), account="alice")
        raise AuthenticationError("Invalid credential")

    async def aclose(self):
        self.closed = True


@pytest.fixture
def setup():
    settings = Settings(Path("config.toml"), "127.0.0.1", 8000, 32, 120, AuthSettings(),
                        {"search": Domain("search", 8101, "mcp:search", "schematic_mcp.domains.search")}, 10, 5, 60)
    def token(**overrides):
        return "no-scope" if overrides else "valid"
    return settings, token


async def test_session_validation(setup):
    settings, token = setup
    principal, _ = await authenticate(Headers({"x-user-account": "alice", "x-cookie": token()}), settings, FakeProvider())
    assert principal.subject == "alice"
    for value in ("expired", "revoked", "invalid"):
        with pytest.raises(AuthenticationError):
            await authenticate(Headers({"x-user-account": "alice", "x-cookie": value}), settings, FakeProvider())


def test_router_guards(setup):
    settings, token = setup
    with TestClient(create_router(settings, FakeProvider())) as client:
        assert client.get("/healthz").status_code == 200
        assert client.post("/mcp/search").status_code == 401
        assert client.post("/mcp/search", headers={"x-user-account": "alice", "x-cookie": token(scope="")}).status_code == 403
        assert client.post("/mcp/search", content="x" * 33,
                           headers={"x-user-account": "alice", "x-cookie": token()}).status_code == 413


def test_domain_auth_and_mcp(setup):
    settings, token = setup
    with TestClient(create_domain(settings, "search", FakeProvider())) as client:
        assert client.post("/mcp").status_code == 401
        headers = {"x-user-account": "alice", "x-cookie": token(), "Accept": "application/json, text/event-stream"}
        response = client.post("/mcp", headers=headers, json={"jsonrpc": "2.0", "id": 1,
            "method": "initialize", "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                                                 "clientInfo": {"name": "test", "version": "1"}}})
        assert response.status_code == 200
        assert "serverInfo" in response.text
        for method, field in (("tools/list", "tools"), ("prompts/list", "prompts")):
            response = client.post("/mcp", headers=headers,
                                   json={"jsonrpc": "2.0", "id": 2, "method": method, "params": {}})
            assert response.status_code == 200
            assert f'"{field}":[]' in response.text.replace(" ", "")


async def test_tool_scope(setup):
    settings, token = setup
    @require_scope("write")
    async def operation():
        return "ok"
    value = principal_context.set(Principal("alice", "a", frozenset({"search:read"}), account="alice"))
    try:
        with pytest.raises(AuthorizationError):
            await operation()
    finally:
        principal_context.reset(value)


def test_limiter_capacity():
    limiter = RateLimiter(1, capacity=1)
    assert limiter.allow("alice")
    assert not limiter.allow("alice")
    assert not limiter.allow("bob")


def test_router_forwards_protocol_and_filters_identity(setup):
    settings, token = setup
    seen = []
    async def backend(request):
        seen.append(request)
        return httpx.Response(200, headers={"Content-Type": "text/event-stream", "Mcp-Session-Id": "test"},
                              content=b'data: {"jsonrpc":"2.0","id":1,"result":{}}\n\n')
    with TestClient(create_router(settings, FakeProvider())) as client:
        old = client.app.state.client
        client.app.state.client = httpx.AsyncClient(transport=httpx.MockTransport(backend))
        response = client.post("/mcp/search", content="{}", headers={
            "x-user-account": "alice", "x-cookie": token(), "Accept": "text/event-stream",
            "X-User-Id": "admin", "Mcp-Protocol-Version": "2025-03-26"})
        client.portal.call(client.app.state.client.aclose)
        client.app.state.client = old
        assert response.status_code == 200
        assert response.headers["mcp-session-id"] == "test"
        assert response.text.startswith("data:")
        assert seen[0].url.path == "/mcp"
        assert "x-user-id" not in seen[0].headers
        assert seen[0].headers["x-request-id"] == response.headers["x-request-id"]


def test_router_upstream_failure(setup):
    settings, token = setup
    async def backend(request):
        raise httpx.ConnectError("unavailable")
    with TestClient(create_router(settings, FakeProvider())) as client:
        old = client.app.state.client
        client.app.state.client = httpx.AsyncClient(transport=httpx.MockTransport(backend))
        response = client.post("/mcp/search", headers={"x-user-account": "alice", "x-cookie": token()})
        client.portal.call(client.app.state.client.aclose)
        client.app.state.client = old
        assert response.status_code == 502


@pytest.mark.parametrize("headers", [
    {}, {"x-cookie": "valid"}, {"x-user-account": "alice"},
    {"x-cookie": "", "x-user-account": "alice"},
    {"x-cookie": "valid", "x-user-account": "   "},
    {"Cookie": "session=valid", "x-user-account": "alice"},
    {"x-cookie": "bad\r\nvalue", "x-user-account": "alice"},
])
def test_reject_missing_or_invalid_pair(headers):
    with pytest.raises(AuthenticationError):
        extract_credential(Headers(headers), AuthSettings())


@pytest.mark.parametrize("name", [b"x-cookie", b"x-user-account"])
def test_duplicate_header(name):
    raw = [(b"x-cookie", b"valid"), (b"x-user-account", b"alice"), (name, b"duplicate")]
    with pytest.raises(AuthenticationError):
        extract_credential(Headers(raw=raw), AuthSettings())


def test_full_cookie_and_redaction():
    headers = {"X-Cookie": "session=secret; tenant=a", "X-User-Account": "alice@example.com"}
    credential = extract_credential(Headers(headers), AuthSettings())
    assert credential.as_headers() == {"x-cookie": headers["X-Cookie"], "x-user-account": headers["X-User-Account"]}
    assert "secret" not in repr(credential)
    assert "alice" not in repr(credential)


def test_pair_forwarding_and_close(setup):
    settings, _ = setup
    seen = []
    async def backend(request):
        seen.append(request)
        return httpx.Response(200, content=b"ok", headers={"Set-Cookie": "unwanted=stored"})
    provider = FakeProvider()
    with TestClient(create_router(settings, provider)) as client:
        old = client.app.state.client
        client.app.state.client = httpx.AsyncClient(transport=httpx.MockTransport(backend))
        for _ in range(2):
            response = client.post("/mcp/search", headers={"X-Cookie": "valid", "X-User-Account": "alice",
                                  "Cookie": "unrelated=secret", "Authorization": "unrelated-secret"})
            assert response.status_code == 200
        client.portal.call(client.app.state.client.aclose)
        client.app.state.client = old
        for request in seen:
            assert request.headers["x-cookie"] == "valid"
            assert request.headers["x-user-account"] == "alice"
            assert "cookie" not in request.headers
            assert "authorization" not in request.headers
    assert provider.closed


@pytest.mark.parametrize("domain", [False, True])
def test_account_binding_and_close(setup, domain):
    settings, _ = setup
    provider = FakeProvider()
    app = create_domain(settings, "search", provider) if domain else create_router(settings, provider)
    path = "/mcp" if domain else "/mcp/search"
    with TestClient(app) as client:
        response = client.post(path, headers={"X-Cookie": "valid", "X-User-Account": "mallory"})
        assert response.status_code == 401
        response = client.post(path, headers={"X-Cookie": "no-scope", "X-User-Account": "alice"})
        assert response.status_code == 403
        assert principal_context.get(None) is None
    assert provider.closed


def test_unconfigured_provider_fails_closed(setup):
    settings, _ = setup
    for app, path in ((create_router(settings), "/mcp/search"), (create_domain(settings, "search"), "/mcp")):
        with TestClient(app) as client:
            assert client.post(path, headers={"X-Cookie": "anything", "X-User-Account": "alice"}).status_code == 503


async def test_provider_failure_and_result_validation(setup):
    import asyncio
    settings, _ = setup
    class Provider(FakeProvider):
        async def authenticate(self, credential, *, request_id):
            if credential.cookie == "timeout":
                await asyncio.sleep(1)
            if credential.cookie == "exception":
                raise RuntimeError("secret backend detail")
            return Principal("alice", "", frozenset(), account="alice")
    settings = replace(settings, auth=replace(settings.auth, timeout_seconds=0.01))
    for value in ("timeout", "exception", "bad-result"):
        with pytest.raises(AuthenticationUnavailable) as error:
            await authenticate(Headers({"x-user-account": "alice", "x-cookie": value}), settings, Provider())
        assert "secret" not in str(error.value)
