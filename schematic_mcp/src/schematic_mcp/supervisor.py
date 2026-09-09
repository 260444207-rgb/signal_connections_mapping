"""Own child processes only; bounded restarts and cooperative shutdown."""
import asyncio
from collections import deque
import logging
import os
import signal
import subprocess
import sys
import time

log = logging.getLogger(__name__)


async def run_supervisor(settings):
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    previous = {}
    signals = [signal.SIGINT, signal.SIGTERM]
    if hasattr(signal, "SIGBREAK"):
        signals.append(signal.SIGBREAK)
    for sig in signals:
        previous[sig] = signal.signal(sig, lambda *_: loop.call_soon_threadsafe(stop.set))

    async def terminate(process):
        if process.returncode is not None:
            return
        try:
            if os.name == "nt":
                process.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                process.terminate()
        except ProcessLookupError:
            return
        try:
            await asyncio.wait_for(process.wait(), settings.grace_seconds)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()

    async def monitor(name, arguments):
        attempts = deque()
        failures = 0
        while not stop.is_set():
            started = time.monotonic()
            options = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {}
            process = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "schematic_mcp.cli", "--config", str(settings.path), *arguments, **options)
            log.info("started name=%s pid=%s", name, process.pid)
            waiting = asyncio.create_task(process.wait())
            stopping = asyncio.create_task(stop.wait())
            try:
                await asyncio.wait([waiting, stopping], return_when=asyncio.FIRST_COMPLETED)
                if stop.is_set():
                    return
                now = time.monotonic()
                if now - started >= settings.restart_window_seconds:
                    failures = 0
                while attempts and attempts[0] < now - settings.restart_window_seconds:
                    attempts.popleft()
                if len(attempts) >= settings.max_restarts:
                    log.error("restart budget exhausted name=%s; stopping stack", name)
                    stop.set()
                    raise RuntimeError(f"Restart budget exhausted: {name}")
                attempts.append(now)
                failures += 1
                delay = min(2 ** (failures - 1), 30)
                log.warning("exited name=%s code=%s restart_in=%s", name, process.returncode, delay)
                try:
                    await asyncio.wait_for(stop.wait(), delay)
                except asyncio.TimeoutError:
                    pass
            finally:
                await terminate(process)
                stopping.cancel()
                await asyncio.gather(waiting, stopping, return_exceptions=True)

    async def guarded(name, arguments):
        try:
            await monitor(name, arguments)
        except BaseException:
            stop.set()
            raise

    tasks = [asyncio.create_task(guarded(name, ["domain", name])) for name in settings.domains]
    tasks.append(asyncio.create_task(guarded("router", ["router"])))
    try:
        results = await asyncio.gather(*tasks, return_exceptions=True)
        failures = [r for r in results if isinstance(r, BaseException)]
        if failures:
            raise RuntimeError("Supervisor stopped after child failure") from failures[0]
    finally:
        stop.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        for sig, handler in previous.items():
            signal.signal(sig, handler)
