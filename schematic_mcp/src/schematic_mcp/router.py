import asyncio
from collections import OrderedDict
from contextlib import asynccontextmanager
import logging
import time
import uuid
import httpx
from starlette.applications import Starlette
from starlette.responses import JSONResponse, StreamingResponse
from starlette.background import BackgroundTask
from starlette.routing import Route
from .security import authenticate, AuthenticationError, AuthenticationUnavailable, create_auth_provider

log = logging.getLogger(__name__)
REQUEST_HEADERS = {"content-type", "accept", "mcp-protocol-version",
                   "mcp-session-id", "last-event-id", "traceparent", "tracestate"}
RESPONSE_HEADERS = {"content-type", "mcp-session-id", "mcp-protocol-version", "cache-control",
                    "www-authenticate", "allow", "retry-after"}


class RateLimiter:
    """Bounded in-process fixed-window limiter; one Router worker only."""
    def __init__(self, limit, capacity=10000):
        self.limit, self.capacity, self.entries = limit, capacity, OrderedDict()

    def allow(self, key):
        now = time.monotonic()
        while self.entries and next(iter(self.entries.values()))[0] <= now:
            self.entries.popitem(last=False)
        if key not in self.entries:
            if len(self.entries) >= self.capacity:
                return False
            self.entries[key] = (now + 60, 0)
        expires, count = self.entries[key]
        if count >= self.limit:
            return False
        self.entries[key] = (expires, count + 1)
        return True


def create_router(settings, provider=None):
    provider = provider if provider is not None else create_auth_provider(settings)
    @asynccontextmanager
    async def lifespan(app):
        async with httpx.AsyncClient(timeout=httpx.Timeout(60, connect=3), trust_env=False) as client:
            app.state.client = client
            try:
                yield
            finally:
                await provider.aclose()

    limiter = RateLimiter(settings.requests_per_minute)

    async def health(request):
        return JSONResponse({"status": "ok"})

    async def ready(request):
        async def check(domain):
            try:
                response = await request.app.state.client.get(domain.base_url + "/healthz", timeout=2)
                return domain.name, response.status_code == 200
            except httpx.HTTPError:
                return domain.name, False
        states = dict(await asyncio.gather(*(check(d) for d in settings.domains.values())))
        return JSONResponse({"domains": states}, 200 if all(states.values()) else 503)

    async def proxy(request):
        rid = uuid.uuid4().hex
        def error(code, status):
            return JSONResponse({"error": code, "request_id": rid}, status,
                                headers={"X-Request-ID": rid})
        domain = settings.domains.get(request.path_params["domain"])
        if domain is None:
            return error("unknown_domain", 404)
        try:
            principal, credential = await authenticate(request.headers, settings, provider, request_id=rid)
        except AuthenticationError:
            return error("unauthorized", 401)
        except AuthenticationUnavailable:
            return error("authentication_unavailable", 503)
        if domain.scope not in principal.scopes:
            return error("forbidden", 403)
        if not limiter.allow((principal.tenant_id, principal.subject, domain.name)):
            return error("rate_limited", 429)
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > settings.max_body_bytes:
                return error("body_too_large", 413)
            body.extend(chunk)
        headers = {k: v for k, v in request.headers.items() if k.lower() in REQUEST_HEADERS}
        headers.update(credential.as_headers())
        headers["x-request-id"] = rid
        client = request.app.state.client
        # Avoid merging a shared cookie jar into another user's request.
        upstream_request = httpx.Request(request.method, domain.base_url + "/mcp",
                                                headers=headers, content=bytes(body))
        try:
            upstream = await client.send(upstream_request, stream=True)
        except httpx.TimeoutException:
            return error("domain_timeout", 504)
        except httpx.HTTPError:
            return error("domain_unavailable", 502)
        log.info("request_id=%s domain=%s status=%s", rid, domain.name, upstream.status_code)
        async def stream():
            try:
                async for chunk in upstream.aiter_bytes():
                    yield chunk
            finally:
                await upstream.aclose()
        outgoing = {k: v for k, v in upstream.headers.items() if k.lower() in RESPONSE_HEADERS}
        outgoing["x-request-id"] = rid
        return StreamingResponse(stream(), status_code=upstream.status_code, headers=outgoing,
                                 background=BackgroundTask(upstream.aclose))

    return Starlette(routes=[Route("/healthz", health), Route("/readyz", ready),
                             Route("/mcp/{domain}", proxy, methods=["GET", "POST", "DELETE"])], lifespan=lifespan)
