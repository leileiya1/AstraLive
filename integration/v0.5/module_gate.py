#!/usr/bin/env python3
"""Run CPU/SQL regression on an immutable source or actual merge commit archive."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--python", required=True)
    parser.add_argument("--pg-bin", required=True)
    parser.add_argument("--frontend-modules", type=Path)
    args = parser.parse_args()
    source = subprocess.check_output(["git", "-C", str(args.repo), "rev-parse", args.source], text=True).strip()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    report = {"source": source, "scope": "owned PostgreSQL/CPU process/Go/Python software regression; no real inference or audience acceptance", "checks": []}
    env = {key: os.environ[key] for key in ("PATH", "HOME", "TMPDIR", "LANG") if key in os.environ}
    env.update(DURABILITY_PG_BIN=args.pg_bin, DURABILITY_TEST_PYTHON=args.python, NARRATION_TEST_PYTHON=args.python, ASTRALIVE_IPC_TEST_PYTHON=args.python)
    with tempfile.TemporaryDirectory(prefix="astralive-f-module-") as temp:
        root = Path(temp).resolve()
        archive = subprocess.Popen(["git", "-C", str(args.repo), "archive", source], stdout=subprocess.PIPE)
        with tarfile.open(fileobj=archive.stdout, mode="r|*") as tar:
            tar.extractall(root, filter="data")
        if archive.wait():
            raise RuntimeError("git archive failed")
        for binary in ("go", "bun", args.python, str(Path(args.pg_bin) / "postgres")):
            version_args = [binary, "version"] if binary == "go" else [binary, "--version"]
            report.setdefault("environment", {})[binary] = subprocess.check_output(version_args, text=True, env=env).strip()
        commands = [
            ("faults", ["bash", "backend/scripts/test-durability-faults.sh"], root, env),
            ("runtime", [args.python, "-m", "unittest", "discover", "-s", "runtime/tests", "-p", "test_*.py", "-v"], root, dict(env, PYTHONPATH=str(root / "runtime"))),
        ]
        if args.frontend_modules:
            modules = args.frontend_modules.resolve(strict=True)
            source_lock = (root / "frontend/bun.lock").read_bytes()
            if source_lock != (modules.parent / "bun.lock").read_bytes():
                raise RuntimeError("Borrowed frontend dependencies have a different lockfile")
            report["frontendDependencies"] = {"directory": str(modules), "matchingLockSHA256": hashlib.sha256(source_lock).hexdigest()}
            (root / "frontend/node_modules").symlink_to(modules, target_is_directory=True)
            commands.extend((
                ("frontend-test", ["bun", "run", "test"], root / "frontend", env),
                ("frontend-build", ["bun", "run", "build"], root / "frontend", env),
            ))
        for name, argv, cwd, task_env in commands:
            started = time.monotonic()
            log = out / f"{name}.log"
            with log.open("wb") as handle:
                process = subprocess.run(argv, cwd=cwd, env=task_env, stdout=handle, stderr=subprocess.STDOUT)
            raw = log.read_bytes()
            row = {"name": name, "command": argv, "exitCode": process.returncode,
                   "durationSeconds": round(time.monotonic() - started, 3),
                   "log": log.name, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
            report["checks"].append(row)
            (out / "result.json").write_text(json.dumps(report, indent=2) + "\n")
            print(json.dumps(row), flush=True)
    report["status"] = "PASS" if all(row["exitCode"] == 0 for row in report["checks"]) else "FAIL"
    report["frontend"] = "EXECUTED" if args.frontend_modules else "NOT TESTED"
    (out / "result.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"source": source, "status": report["status"]}), flush=True)
    return int(report["status"] != "PASS")


if __name__ == "__main__":
    raise SystemExit(main())
