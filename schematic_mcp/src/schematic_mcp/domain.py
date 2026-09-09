import importlib
from fastmcp import FastMCP
from starlette.responses import JSONResponse
from .security import DomainAuth, create_auth_provider


def create_domain(settings, name, provider=None):
    domain = settings.domains[name]
    mcp = FastMCP(f"Schematic/{name}", mask_error_details=True)
    module = importlib.import_module(domain.module)
    module.register(mcp)

    @mcp.custom_route("/healthz", methods=["GET"])
    async def health(request):
        return JSONResponse({"status": "ok", "domain": name})

    app = mcp.http_app(path="/mcp", stateless_http=True)
    return DomainAuth(app, settings, domain, provider if provider is not None else create_auth_provider(settings))
