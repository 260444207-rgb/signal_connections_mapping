"""Integration point to fill once the X-Cookie / X-User-Account API contract is known."""
from .security import AuthProvider, AuthenticationUnavailable, Credential, Principal


class ExistingSessionAuthProvider:
    async def authenticate(self, credential: Credential, *, request_id: str) -> Principal:
        # TODO: validate credential.cookie together with credential.user_account via
        # your existing identity service. Preserve the full X-Cookie header value.
        # Map invalid/expired/revoked credentials to AuthenticationError.
        # Map outages/malformed responses to AuthenticationUnavailable.
        # Return Principal(subject, tenant_id, frozenset(server_verified_scopes),
        #                  account=account_from_trusted_backend).
        # Never copy the claimed account into Principal without verifying ownership.
        # Do NOT grant scopes merely because a token or cookie is present.
        raise AuthenticationUnavailable("Existing session authentication is not configured")

    async def aclose(self) -> None:
        # TODO: close your adapter's owned async HTTP client, if any.
        pass


def create_provider(settings) -> AuthProvider:
    """No network I/O in the factory; create one adapter per process."""
    return ExistingSessionAuthProvider()
