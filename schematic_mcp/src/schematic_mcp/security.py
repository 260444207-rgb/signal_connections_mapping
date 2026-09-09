"""Opaque credentials: never decode a token or trust client identity headers."""
from contextvars import ContextVar
from dataclasses import dataclass, field
import functools
import asyncio
import importlib
from typing import Protocol
from starlette.responses import JSONResponse
from starlette.datastructures import Headers
from .config import validate_auth_settings


@dataclass(frozen=True)
class Principal:
    subject: str
    tenant_id: str
    scopes: frozenset[str]
    account: str  # Account returned by the trusted authentication backend.


@dataclass(frozen=True)
class Credential:
    cookie: str = field(repr=False)
    user_account: str = field(repr=False)  # Unverified claim until backend validation.

    def as_headers(self) -> dict[str, str]:
        """Forward this request's pair only to its trusted internal Domain."""
        return {"x-cookie": self.cookie, "x-user-account": self.user_account}


class AuthenticationError(Exception):
    """Missing, expired, revoked or invalid credential (HTTP 401)."""


class AuthenticationUnavailable(Exception):
    """Unconfigured provider, backend outage or invalid provider result (HTTP 503)."""


class AuthorizationError(Exception):
    """Authenticated identity lacks permission."""


class AuthProvider(Protocol):
    async def authenticate(self, credential: Credential, *, request_id: str) -> Principal:
        """Validate with existing backend and map trusted identity/permissions."""
        ...

    async def aclose(self) -> None:
        """Close owned connections during process shutdown."""
        ...


principal_context: ContextVar[Principal] = ContextVar("principal")
request_id_context: ContextVar[str] = ContextVar("request_id", default="")


def create_auth_provider(settings) -> AuthProvider:
    validate_auth_settings(settings.auth)
    module, factory = settings.auth.provider_factory.split(":")
    return getattr(importlib.import_module(module), factory)(settings)


def extract_credential(headers: Headers, auth) -> Credential:
    def required(name, max_length):
        values = headers.getlist(name)
        if len(values) != 1:
            raise AuthenticationError("Missing or duplicate authentication header")
        value = values[0]
        # Preserve the full X-Cookie string, including spaces and semicolons.
        if not value.strip() or len(value) > max_length or any(not 32 <= ord(c) <= 126 for c in value):
            raise AuthenticationError("Invalid authentication header")
        return value
    return Credential(required("x-cookie", 8192), required("x-user-account", 256))


async def authenticate(headers, settings, provider, *, request_id=""):
    credential = extract_credential(headers, settings.auth)
    try:
        async with asyncio.timeout(settings.auth.timeout_seconds):
            principal = await provider.authenticate(credential, request_id=request_id)
    except (AuthenticationError, AuthenticationUnavailable):
        raise
    except Exception:
        # Provider/network exceptions may contain credentials: do not log or expose them.
        raise AuthenticationUnavailable("Authentication service unavailable") from None
    if (not isinstance(principal, Principal)
        or not isinstance(principal.subject, str) or not principal.subject
        or not isinstance(principal.tenant_id, str) or not principal.tenant_id
        or not isinstance(principal.account, str) or not principal.account.strip()
        or not isinstance(principal.scopes, frozenset)
        or not all(isinstance(s, str) and s for s in principal.scopes)):
        raise AuthenticationUnavailable("Invalid authentication result")
    if principal.account != credential.user_account:
        raise AuthenticationError("Cookie and account do not match")
    return principal, credential


def require_scope(scope: str):
    """Place below @mcp.tool / @mcp.prompt; checks trusted request identity."""
    if not scope:
        raise ValueError("A nonempty scope is required")
    def decorate(fn):
        @functools.wraps(fn)
        async def wrapped(*args, **kwargs):
            principal = principal_context.get(None)
            if principal is None or scope not in principal.scopes:
                raise AuthorizationError("Permission denied")
            return await fn(*args, **kwargs)
        return wrapped
    return decorate


class DomainAuth:
    def __init__(self, app, settings, domain, provider):
        self.app, self.settings, self.domain, self.provider = app, settings, domain, provider

    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":
            try:
                return await self.app(scope, receive, send)
            finally:
                await self.provider.aclose()
        if scope["type"] != "http" or scope["path"] == "/healthz":
            return await self.app(scope, receive, send)
        headers = Headers(scope=scope)
        try:
            principal, _ = await authenticate(headers, self.settings, self.provider,
                                               request_id=headers.get("x-request-id", ""))
        except AuthenticationError:
            return await JSONResponse({"error": "unauthorized"}, 401)(scope, receive, send)
        except AuthenticationUnavailable:
            return await JSONResponse({"error": "authentication_unavailable"}, 503)(scope, receive, send)
        if self.domain.scope not in principal.scopes:
            return await JSONResponse({"error": "forbidden"}, 403)(scope, receive, send)
        token = principal_context.set(principal)
        rid = request_id_context.set(headers.get("x-request-id", ""))
        try:
            await self.app(scope, receive, send)
        finally:
            principal_context.reset(token)
            request_id_context.reset(rid)
