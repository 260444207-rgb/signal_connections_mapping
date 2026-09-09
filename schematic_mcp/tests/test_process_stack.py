"""Real HTTP smoke test, isolated ports and a test-only session provider."""
import os
import re
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
import httpx


def test_supervised_stack(tmp_path):
    sockets = [socket.socket() for _ in range(4)]
    for sock in sockets:
        sock.bind(("127.0.0.1", 0))
    ports = [sock.getsockname()[1] for sock in sockets]
    for sock in sockets:
        sock.close()
    config = (Path(__file__).parents[1] / "config.toml").read_text(encoding="utf-8")
    for old, new in zip((8000, 8101, 8102, 8103), ports):
        config = config.replace(f"port = {old}", f"port = {new}")
    config_file = tmp_path / "config.toml"
    config_file.write_text(config, encoding="utf-8")
    # The fake exists only in pytest's temporary directory, not in production source.
    (tmp_path / "smoke_auth.py").write_text('from schematic_mcp.security import Principal, AuthenticationError\nclass Provider:\n    async def authenticate(self, credential, *, request_id):\n        if credential.cookie != "test-session":\n            raise AuthenticationError("invalid")\n        return Principal("test", "test", frozenset({"mcp:search", "mcp:files", "mcp:github"}), account="test")\n    async def aclose(self):\n        pass\ndef create_provider(settings):\n    return Provider()\n', encoding="utf-8")
    config_file.write_text(config.replace("schematic_mcp.auth_provider:create_provider", "smoke_auth:create_provider"), encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": str(tmp_path) + os.pathsep + os.environ.get("PYTHONPATH", "")}
    options = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {}
    with (tmp_path / "stack.log").open("w+") as output:
        process = subprocess.Popen([sys.executable, "-m", "schematic_mcp.cli", "--config", str(config_file), "serve"],
                                   env=env, stdout=output, stderr=output, **options)
        try:
            with httpx.Client(base_url=f"http://127.0.0.1:{ports[0]}", trust_env=False, timeout=5) as client:
                deadline = time.monotonic() + 45
                while time.monotonic() < deadline:
                    try:
                        if client.get("/readyz").status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    if process.poll() is not None:
                        raise AssertionError("Supervisor exited early")
                    time.sleep(0.2)
                else:
                    raise AssertionError("Stack did not become ready")
                for domain in ("search", "files", "github"):
                    response = client.post(f"/mcp/{domain}", headers={"X-Cookie": "test-session", "X-User-Account": "test",
                        "Accept": "application/json, text/event-stream"}, json={"jsonrpc": "2.0", "id": 1,
                        "method": "initialize", "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                        "clientInfo": {"name": "smoke", "version": "1"}}})
                    assert response.status_code == 200, response.text
                    assert "serverInfo" in response.text
                # Kill only the child created by this test and verify replacement.
                output.seek(0)
                log_text = output.read()
                original = re.findall(r"started name=search pid=(\d+)", log_text)
                assert original, log_text
                os.kill(int(original[-1]), signal.SIGTERM)
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    output.seek(0)
                    restarted = re.findall(r"started name=search pid=(\d+)", output.read())
                    if len(restarted) > len(original) and client.get("/readyz").status_code == 200:
                        assert restarted[-1] != original[-1]
                        break
                    time.sleep(0.2)
                else:
                    raise AssertionError("Domain was not restarted")
        finally:
            if process.poll() is None:
                process.send_signal(signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGTERM)
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                raise AssertionError("Supervisor failed to stop gracefully")
        assert process.returncode == 0
