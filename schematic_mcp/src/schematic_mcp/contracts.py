"""Shared business contracts; no invented backend endpoints."""
from typing import Any, Protocol
from dataclasses import dataclass
from .security import Principal


@dataclass(frozen=True)
class CallContext:
    principal: Principal
    request_id: str


class BackendClient(Protocol):
    async def execute(self, *, operation: str, payload: dict[str, Any], context: CallContext) -> dict[str, Any]:
        """Use an allowlisted operation; never accept user-supplied URLs."""
        ...


class DataAuthorizer(Protocol):
    async def require_access(self, *, context: CallContext, action: str, resource_id: str) -> None:
        """Raise on denial; tenant and principal come from verified authentication only."""
        ...


class UnconfiguredBackend:
    async def execute(self, *, operation, payload, context):
        raise NotImplementedError("Configure a backend adapter before enabling business tools")


class DenyAllAuthorizer:
    async def require_access(self, *, context, action, resource_id):
        from .security import AuthorizationError
        raise AuthorizationError("Data authorization is not configured")
