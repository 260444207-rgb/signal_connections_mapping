from dataclasses import dataclass
from pathlib import Path
import re
import tomllib


@dataclass(frozen=True)
class Domain:
    name: str
    port: int
    scope: str
    module: str

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"


@dataclass(frozen=True)
class AuthSettings:
    provider_factory: str = "schematic_mcp.auth_provider:create_provider"
    timeout_seconds: float = 5.0


@dataclass(frozen=True)
class Settings:
    path: Path
    host: str
    port: int
    max_body_bytes: int
    requests_per_minute: int
    auth: AuthSettings
    domains: dict[str, Domain]
    grace_seconds: float
    max_restarts: int
    restart_window_seconds: float


def load_settings(path: str | Path) -> Settings:
    path = Path(path).resolve()
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    router, auth = data["router"], data["auth"]
    supervisor = data["supervisor"]
    domains = {name: Domain(name=name, **value) for name, value in data["domains"].items()}
    ports = [router["port"], *(d.port for d in domains.values())]
    if not domains or len(set(ports)) != len(ports) or any(not 1 <= p <= 65535 for p in ports):
        raise ValueError("Require domains and unique valid ports")
    for d in domains.values():
        if not re.fullmatch(r"[a-z][a-z0-9_]*", d.name) or not d.scope:
            raise ValueError("Invalid domain name or scope")
    if any(v <= 0 for v in (router["max_body_bytes"], router["requests_per_minute"], *supervisor.values())):
        raise ValueError("Limits must be positive")
    auth_settings = AuthSettings(**auth)
    validate_auth_settings(auth_settings)
    return Settings(path, router["host"], router["port"], router["max_body_bytes"],
                    router["requests_per_minute"], auth_settings,
                    domains, **supervisor)


def validate_auth_settings(auth):
    if not 0 < auth.timeout_seconds <= 60:
        raise ValueError("Auth timeout must be between 0 and 60 seconds")
    if not re.fullmatch(r"[A-Za-z_][\w.]*:[A-Za-z_]\w*", auth.provider_factory):
        raise ValueError("provider_factory must be module:factory")
