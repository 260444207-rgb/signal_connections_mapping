import argparse
import asyncio
import logging
import signal
import uvicorn
from .config import load_settings


def main():
    parser = argparse.ArgumentParser(description="Schematic MCP process entry point")
    parser.add_argument("--config", default="config.toml")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("serve")
    sub.add_parser("router")
    sub.add_parser("check")
    sub.add_parser("domain").add_argument("name")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(process)d %(levelname)s %(name)s %(message)s")
    settings = load_settings(args.config)
    if args.command == "check":
        print("Configuration valid; domains:", ", ".join(settings.domains))
        return
    if args.command == "serve":
        from .supervisor import run_supervisor
        asyncio.run(run_supervisor(settings))
        return
    if args.command == "router":
        from .router import create_router
        app, host, port = create_router(settings), settings.host, settings.port
    else:
        from .domain import create_domain
        app, host, port = create_domain(settings, args.name), "127.0.0.1", settings.domains[args.name].port
    server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, access_log=False,
                                          timeout_graceful_shutdown=settings.grace_seconds))
    # CTRL_BREAK is scoped to each child process group on Windows.
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, server.handle_exit)
    server.run()


if __name__ == "__main__":
    main()
