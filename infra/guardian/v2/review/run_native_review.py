"""Dedicated local PG/native regression; no physical-source production claims.

Owns one new cluster/database; only those resources are stopped/dropped. Runs
current Agent4 receiver1 package with the current Guardian source, no overlay.
"""

import argparse
import json
import os
import resource
import socket
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--postgres-bin", type=Path, default=Path("/opt/homebrew/opt/postgresql@17/bin")
    )
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    own = Path(tempfile.mkdtemp(prefix="ag5-native-", dir="/tmp"))
    (own / "AGENT4_RECEIVER1_OWNED").write_text(
        "Agent4 dedicated receiver1 PostgreSQL\n"
    )
    data, sockets = own / "data", own / "sockets"
    sockets.mkdir()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    name = "agent4_receiver1_ag5_owned"
    env = {
        k: os.environ[k]
        for k in ("PATH", "HOME", "TMPDIR", "GOCACHE", "GOPATH")
        if k in os.environ
    }
    env.update(
        PYTHONPATH=str(ROOT / "runtime") + os.pathsep + str(ROOT),
        PYTHONDONTWRITEBYTECODE="1",
        GOMAXPROCS="4",
        LC_ALL="C",
    )
    rows, started, created = [], False, False
    source_commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()

    def run(label, command, cwd=ROOT):
        before = resource.getrusage(resource.RUSAGE_CHILDREN)
        start = time.monotonic()
        with (args.output / (label + ".txt")).open("x") as log:
            result = subprocess.run(
                command, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT
            )
        after = resource.getrusage(resource.RUSAGE_CHILDREN)
        rows.append(
            dict(
                label=label,
                command=command,
                cwd=str(cwd),
                exitCode=result.returncode,
                seconds=time.monotonic() - start,
                userSeconds=after.ru_utime - before.ru_utime,
                systemSeconds=after.ru_stime - before.ru_stime,
                peakRSSBytes=after.ru_maxrss,
                generatedAtUTC=datetime.now(timezone.utc).isoformat(),
                sourceCommit=source_commit,
            )
        )
        (args.output / "native-commands.json").write_text(
            json.dumps(rows, indent=2) + "\n"
        )
        print(label, result.returncode, flush=True)
        return result.returncode

    bin_path = args.postgres_bin
    try:
        assert (
            run(
                "initdb",
                [
                    str(bin_path / "initdb"),
                    "-D",
                    str(data),
                    "-A",
                    "trust",
                    "-U",
                    "ag5_owner",
                    "--no-locale",
                    "-E",
                    "UTF8",
                ],
            )
            == 0
        )
        assert (
            run(
                "start",
                [
                    str(bin_path / "pg_ctl"),
                    "-D",
                    str(data),
                    "-l",
                    str(own / "postgres.log"),
                    "-o",
                    f"-h 127.0.0.1 -p {port} -k {sockets}",
                    "-w",
                    "start",
                ],
            )
            == 0
        )
        started = True
        assert (
            run(
                "createdb",
                [
                    str(bin_path / "createdb"),
                    "-h",
                    "127.0.0.1",
                    "-p",
                    str(port),
                    "-U",
                    "ag5_owner",
                    name,
                ],
            )
            == 0
        )
        created = True
        dsn = f"postgres://ag5_owner@127.0.0.1:{port}/{name}?sslmode=disable"
        env.update(
            AGENT4_RECEIVER1_PYTHON=sys.executable,
            AGENT4_RECEIVER1_DATABASE_URL=dsn,
            AGENT4_RECEIVER1_OWNED_ROOT=str(own),
            AGENT4_PR11_ARCHIVE=str(ROOT),
        )
        run(
            "settings",
            [
                str(bin_path / "psql"),
                dsn,
                "-c",
                "SELECT version(),current_database(); SHOW fsync; SHOW synchronous_commit; SHOW full_page_writes;",
            ],
        )
        run(
            "native-package-race",
            [
                "go",
                "test",
                "-race",
                "-json",
                "-count=1",
                "./internal/durableintegration/receiver1",
            ],
            ROOT / "backend",
        )
    finally:
        dropped = False
        if created:
            dropped = (
                run(
                    "dropdb",
                    [
                        str(bin_path / "dropdb"),
                        "-h",
                        "127.0.0.1",
                        "-p",
                        str(port),
                        "-U",
                        "ag5_owner",
                        name,
                    ],
                )
                == 0
            )
        if started:
            run(
                "stop",
                [str(bin_path / "pg_ctl"), "-D", str(data), "-m", "fast", "-w", "stop"],
            )
        stopped = not (data / "postmaster.pid").exists()
        (args.output / "cleanup.json").write_text(
            json.dumps(
                dict(
                    ownedRoot=str(own),
                    databaseDropped=dropped,
                    postgresStopped=stopped,
                    physical="explicit Agent4 installation/output fixture",
                    sharedServicesTouched=False,
                    sourceCommit=subprocess.check_output(
                        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
                    ).strip(),
                ),
                indent=2,
            )
            + "\n"
        )
        if (own / "postgres.log").exists():
            (args.output / "postgres.txt").write_bytes(
                (own / "postgres.log").read_bytes()
            )
    return int(any(r["exitCode"] for r in rows) or not dropped or not stopped)


if __name__ == "__main__":
    raise SystemExit(main())
