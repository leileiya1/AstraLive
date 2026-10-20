"""Start only with an operator-owned, mode 0600 config file (no secret env/argv)."""

import argparse
import asyncio
import json
import os
import signal
from pathlib import Path

from aiohttp import web

from .authority import PostgresAuthority
from .ingest import Ingest
from .service import Guardian, auth_app, ipc_app


def secret(path):
    p = Path(path)
    if p.stat().st_mode & 0o077:
        raise ValueError("secret file must be mode 0600/0400")
    value = p.read_text().strip()
    if len(value) < 32:
        raise ValueError("short secret")
    return value


async def serve(config):
    authority = PostgresAuthority(
        secret(config["dsnFile"]),
        config["guardianId"],
        config["tenantId"],
        config["ownerId"],
        config["roomId"],
    )
    ingest = Ingest(config["apiURL"], config["path"])
    guardian = Guardian(
        authority,
        ingest,
        config["stateDir"],
        config["recordingDir"],
        rtmp_url=config["rtmpURL"],
        path=config["path"],
        **config.get("media", {}),
    )
    auth_runner = web.AppRunner(auth_app(guardian), access_log=None)
    ipc_runner = None
    try:
        await auth_runner.setup()
        await web.TCPSite(
            auth_runner, "127.0.0.1", config.get("authPort", 19999)
        ).start()
        await guardian.start()
        producers = {
            secret(p["tokenFile"]): p["producerIncarnation"]
            for p in config["producers"]
        }
        ipc_runner = web.AppRunner(
            ipc_app(guardian, secret(config["controlTokenFile"]), producers),
            access_log=None,
            keepalive_timeout=2,
            shutdown_timeout=0.5,
        )
        await ipc_runner.setup()
        socket_path = Path(config["socketPath"])
        # Only after exclusive state ownership, never remove another live socket.
        socket_path.unlink(missing_ok=True)
        await web.UnixSite(ipc_runner, str(socket_path)).start()
        os.chmod(socket_path, 0o660)
        stopped = asyncio.Event()
        for sig in (signal.SIGINT, signal.SIGTERM):
            asyncio.get_running_loop().add_signal_handler(sig, stopped.set)
        await stopped.wait()
    finally:
        if ipc_runner:
            await ipc_runner.cleanup()
        await guardian.close()
        await auth_runner.cleanup()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    p = Path(args.config)
    if p.stat().st_mode & 0o022:
        raise SystemExit("unsafe configuration permissions")
    try:
        asyncio.run(serve(json.loads(p.read_text())))
    except Exception:
        # Never print DSN, URL, media payload, provider data or exception text.
        raise SystemExit("OUTPUT_FENCE_UNPROVEN") from None
