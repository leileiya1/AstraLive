#!/usr/bin/env python3
"""Run an opt-in native narration fixture on an immutable source and owned PG.

Real Chrome/RTMP/SQL with synthetic inference; never a GPU/human release gate.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tarfile
import tempfile
import time
import uuid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--python", required=True)
    parser.add_argument("--pg-bin", type=Path, required=True)
    parser.add_argument("--mode", choices=("short", "soak", "control"), required=True)
    parser.add_argument("--overlay-test", type=Path)
    args = parser.parse_args()
    if args.mode == "control" and args.overlay_test is None:
        parser.error("control requires --overlay-test")
    source = subprocess.check_output(["git", "-C", str(args.repo), "rev-parse", args.source], text=True).strip()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    env = {key: os.environ[key] for key in ("PATH", "HOME", "TMPDIR", "LANG") if key in os.environ}
    report = {"source": source, "mode": args.mode,
              "scope": "owned PostgreSQL/Go HTTP journal/production Scheduler/Python Timeline/native Chrome/local RTMP; deterministic language/synthetic TTS/Lightweight2D",
              "audienceAudible": False, "realGPU": "NOT TESTED", "humanNaturalness": "NOT TESTED",
              "status": "RUNNING", "checks": []}
    pgdata = Path(tempfile.mkdtemp(prefix="astralive-f-narration-pg-"))
    owner = uuid.uuid4().hex
    started = False
    failure = None
    def save():
        (out / "result.json").write_text(json.dumps(report, indent=2) + "\n")
    def run(name, argv, cwd=None, task_env=None):
        clock = time.monotonic()
        log = out / (name + ".log")
        with log.open("wb") as handle:
            proc = subprocess.run(argv, cwd=cwd, env=task_env or env, stdout=handle, stderr=subprocess.STDOUT)
        raw = log.read_bytes()
        row = {"name": name, "command": [str(x) for x in argv], "exitCode": proc.returncode,
               "durationSeconds": round(time.monotonic() - clock, 3), "log": log.name,
               "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
        report["checks"].append(row)
        save()
        print(json.dumps(row), flush=True)
        if proc.returncode:
            raise RuntimeError(name + " failed")
    try:
        for binary, version in (("go", "version"), (args.python, "--version"),
                                (str(args.pg_bin / "postgres"), "--version"), ("ffmpeg", "-version")):
            report.setdefault("environment", {})[binary] = subprocess.check_output([binary, version], text=True, env=env).splitlines()[0]
        run("python-dependencies", [args.python, "-c", "import importlib.metadata as m; print(chr(10).join(sorted(d.metadata['Name']+'=='+d.version for d in m.distributions())))"])
        run("pg-init", [str(args.pg_bin / "initdb"), "-D", str(pgdata), "-A", "trust", "--no-locale", "-E", "UTF8"])
        (pgdata / ".astralive-f-owned").write_text(owner)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        with (pgdata / "postgresql.conf").open("a") as handle:
            handle.write(f"\nport = {port}\nlisten_addresses = '127.0.0.1'\nunix_socket_directories = '{pgdata}'\n")
        run("pg-start", [str(args.pg_bin / "pg_ctl"), "-D", str(pgdata), "-l", str(pgdata / "postgres.log"), "start"])
        started = True
        run("pg-database", [str(args.pg_bin / "createdb"), "-h", "127.0.0.1", "-p", str(port), "astralive_narration"])
        username = subprocess.check_output(["id", "-un"], text=True, env=env).strip()
        env.update(DURABILITY_TEST_DATABASE_URL=f"postgres://{username}@127.0.0.1:{port}/astralive_narration?sslmode=disable",
                   DURABILITY_TEST_PYTHON=args.python, NARRATION_TEST_PYTHON=args.python,
                   NARRATION_REAL_SINKS="true", NARRATION_MEDIA_EVIDENCE_DIR=str(out / "media"))
        case = "TestPostgresNativeChromeRTMPContinuity"
        package = "./internal/narration"
        deadline = "5m"
        if args.mode == "soak":
            env["NARRATION_TEN_MINUTE"] = "true"
            case, deadline = "TestPostgresTenMinuteFiveQuestions", "20m"
        if args.mode == "control":
            case, deadline, package = "TestFReviewBorrowedRetirementSchedulerLock", "30s", "./internal/app"
            env.pop("NARRATION_REAL_SINKS", None)
            report["scope"] = "real owned SQL/production Scheduler/App retirement hook; rollback and lock-order oracle; no provider/sinks"
        with tempfile.TemporaryDirectory(prefix="astralive-f-narration-source-") as temp:
            root = Path(temp)
            archive = subprocess.Popen(["git", "-C", str(args.repo), "archive", source], stdout=subprocess.PIPE)
            with tarfile.open(fileobj=archive.stdout, mode="r|*") as tar:
                tar.extractall(root, filter="data")
            if archive.wait():
                raise RuntimeError("archive failed")
            if args.mode == "control":
                overlay = args.overlay_test.read_bytes()
                report["overlay"] = {"name": args.overlay_test.name, "sha256": hashlib.sha256(overlay).hexdigest()}
                (root / "backend/internal/app/f_review_borrowed_stop_test.go").write_bytes(overlay)
            argv = ["go", "test", "-count=1", "-timeout=" + deadline, "-v", package, "-run", "^" + case + "$" ]
            if args.mode == "control":
                argv.insert(2, "-race")
            run("control" if args.mode == "control" else "native", argv, cwd=root / "backend")
    except Exception as error:
        failure = str(error)
        report["error"] = failure
    finally:
        marker = pgdata / ".astralive-f-owned"
        owned = marker.exists() and marker.read_text() == owner
        clean = not started
        if started and owned:
            with (out / "pg-stop.log").open("wb") as handle:
                stopped = subprocess.run([str(args.pg_bin / "pg_ctl"), "-D", str(pgdata), "-m", "fast", "stop"], env=env, stdout=handle, stderr=subprocess.STDOUT)
            clean = stopped.returncode == 0
        if clean:
            shutil.rmtree(pgdata)
        report["ownedPGCleanup"] = "PASS" if clean else "FAIL"
        if not clean:
            report["retainedOwnedPG"] = str(pgdata)
        report["status"] = "PASS" if failure is None and clean else "FAIL"
        report["artifacts"] = [{"path": str(p.relative_to(out)), "sha256": hashlib.sha256(p.read_bytes()).hexdigest(), "bytes": p.stat().st_size}
                               for p in sorted(out.rglob("*")) if p.is_file() and p.name != "result.json"]
        save()
        print(json.dumps({"source": source, "status": report["status"]}), flush=True)
    return int(report["status"] != "PASS")


if __name__ == "__main__":
    raise SystemExit(main())
