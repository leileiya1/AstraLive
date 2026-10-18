#!/usr/bin/env python3
"""Create/stop only a private native PostgreSQL cluster; retain evidence/data.
Requires PostgreSQL binaries and Go on PATH. Never uses DATABASE_URL or Docker.
"""
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time


def main():
    repo = Path(__file__).resolve().parents[4]
    root = Path(tempfile.mkdtemp(prefix="astralive-agent2-v2-acceptance.", dir="/tmp"))
    (root / "AGENT2_OWNED").write_text("private disposable acceptance instance\n")
    data = root / "data"
    sockets = root / "sockets"
    sockets.mkdir()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    started = False
    result = 1
    try:
        with (root / "init.log").open("w") as output:
            subprocess.run(["initdb", "-D", str(data), "-A", "trust", "-U", "agent2_owner", "--no-locale", "-E", "UTF8"], stdout=output, stderr=subprocess.STDOUT, check=True)
        subprocess.run(["pg_ctl", "-D", str(data), "-l", str(root / "postgres.log"), "-o", f"-h 127.0.0.1 -p {port} -k {sockets}", "-w", "start"], check=True)
        started = True
        subprocess.run(["createdb", "-h", "127.0.0.1", "-p", str(port), "-U", "agent2_owner", "agent2_v2_acceptance"], check=True)
        dsn = f"postgres://agent2_owner@127.0.0.1:{port}/agent2_v2_acceptance?sslmode=disable"
        env = dict(os.environ, DURABLE_V2_TEST_DATABASE_URL=dsn)
        command = ["go", "test", "-race", "./internal/durablelivev2/authority", "-count=1", "-v"]
        start = time.monotonic()
        with (root / "authority.log").open("w") as output:
            result = subprocess.run(command, cwd=repo / "backend", env=env, stdout=output, stderr=subprocess.STDOUT).returncode
        (root / "result.json").write_text(json.dumps({"command": command, "exitCode": result, "seconds": time.monotonic() - start, "database": "owned localhost PostgreSQL", "fsync": "default on", "physicalAdapters": "explicit test fixtures", "officialWire": "not mounted"}, indent=2) + "\n")
        print((root / "authority.log").read_text())
    finally:
        if started:
            subprocess.run(["pg_ctl", "-D", str(data), "-m", "fast", "-w", "stop"], check=True)
        print(f"Retained owned cluster and evidence: {root}")
    return result


if __name__ == "__main__":
    raise SystemExit(main())
