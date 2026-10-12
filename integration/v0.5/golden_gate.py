#!/usr/bin/env python3
"""Owned real-provider/remote-GPU/live Chrome+RTMP integration gate.

Exact source archive and isolated SQL. No synthetic provider substitution.
Credentials are passed only as private file paths; never serialized as values.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import stat
import subprocess
import tarfile
import tempfile
import time
import uuid


def private_file(value):
    path = Path(value).absolute()
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
        raise argparse.ArgumentTypeError("credential file must be private and regular")
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--python", required=True)
    parser.add_argument("--pg-bin", type=Path, required=True)
    parser.add_argument("--mode", choices=("short", "ten-minute", "soak", "faults"), required=True)
    parser.add_argument("--key-file", type=private_file, required=True)
    parser.add_argument("--tts-model-dir", type=Path, required=True)
    parser.add_argument("--worker-token-file", type=private_file, required=True)
    parser.add_argument("--management-token-file", type=private_file, required=True)
    parser.add_argument("--worker-port", type=int, required=True)
    parser.add_argument("--management-port", type=int, required=True)
    parser.add_argument("--worker-ref", default="soulx-lite-01")
    parser.add_argument("--avatar-ref", default="official-girl")
    parser.add_argument("--asset-sha256", required=True)
    parser.add_argument("--profile", choices=("staging-short-1", "staging-segment-8s-1"), default="staging-segment-8s-1")
    parser.add_argument("--short-gpu-gate-sha256", help="operator-pinned short real GPU evidence digest for 8s profile")
    parser.add_argument("--seed", type=int, default=5012)
    args = parser.parse_args()
    seconds = {"short": 60, "ten-minute": 600, "soak": 1800, "faults": 120}[args.mode]
    for port in (args.worker_port, args.management_port):
        if not 1 <= port <= 65535:
            parser.error("port outside valid range")
    if not args.tts_model_dir.is_dir():
        parser.error("cached TTS model directory missing")
    if args.profile == "staging-segment-8s-1":
        import re
        if args.short_gpu_gate_sha256 is None or not re.fullmatch(r"sha256:[0-9a-f]{64}", args.short_gpu_gate_sha256):
            parser.error("8s profile requires pinned short real GPU gate sha256")
    elif args.short_gpu_gate_sha256 is not None:
        parser.error("short profile has no earlier gate digest")
    source = subprocess.check_output(["git", "-C", str(args.repo), "rev-parse", args.source], text=True).strip()
    out = args.output.absolute()
    out.mkdir(parents=True, exist_ok=False)
    report = {"source": source, "mode": args.mode, "requestedSeconds": seconds, "seed": args.seed,
              "scope": "real Go production HTTP components/owned PostgreSQL/production Python Runtime/DeepSeek/XiaoYa/SoulX/native Chrome/local RTMP; fixture audience comment replay",
              "audienceAudible": False, "humanNaturalness": "REQUIRES_SEPARATE_REVIEW",
              "profile": args.profile, "status": "RUNNING", "checks": []}
    env = {key: os.environ[key] for key in ("PATH", "HOME", "TMPDIR", "LANG") if key in os.environ}
    env.update(ASTRALIVE_GOLDEN_LLM_KEY_FILE=str(args.key_file),
               ASTRALIVE_GOLDEN_SOURCE_SHA=source,
               ASTRALIVE_GOLDEN_TTS_MODEL_DIR=str(args.tts_model_dir.absolute()),
               ASTRALIVE_GOLDEN_WORKER_TOKEN_FILE=str(args.worker_token_file),
               ASTRALIVE_GOLDEN_WORKER_MANAGEMENT_TOKEN_FILE=str(args.management_token_file),
               ASTRALIVE_GOLDEN_WORKER_PORT=str(args.worker_port),
               ASTRALIVE_GOLDEN_WORKER_MANAGEMENT_PORT=str(args.management_port),
               ASTRALIVE_GOLDEN_WORKER_REF=args.worker_ref,
               ASTRALIVE_GOLDEN_AVATAR_REF=args.avatar_ref,
               ASTRALIVE_GOLDEN_ASSET_SHA256=args.asset_sha256,
               ASTRALIVE_GOLDEN_PROFILE=args.profile,
               NARRATION_GOLDEN_SECONDS=str(seconds), NARRATION_GOLDEN_SEED=str(args.seed),
               NARRATION_GOLDEN_MODE=args.mode, NARRATION_MEDIA_EVIDENCE_DIR=str(out / "media"),
               NARRATION_TEST_PYTHON=args.python, DURABILITY_TEST_PYTHON=args.python,
               ASTRALIVE_IPC_TEST_PYTHON=args.python)
    if args.short_gpu_gate_sha256:
        env["ASTRALIVE_GOLDEN_SHORT_GPU_GATE_SHA256"] = args.short_gpu_gate_sha256
    pgdata = Path(tempfile.mkdtemp(prefix="astralive-f-golden-pg-"))
    owner = uuid.uuid4().hex
    started = False
    failure = None

    def save():
        (out / "result.json").write_text(json.dumps(report, indent=2)+"\n")

    def run(name, argv, cwd=None):
        clock = time.monotonic()
        log = out / (name+".log")
        with log.open("wb") as handle:
            proc = subprocess.run(argv, cwd=cwd, env=env, stdout=handle, stderr=subprocess.STDOUT)
        raw = log.read_bytes()
        report["checks"].append({"name": name, "command": [str(x) for x in argv],
                                  "exitCode": proc.returncode, "durationSeconds": round(time.monotonic()-clock,3),
                                  "log": log.name, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)})
        save()
        print(json.dumps({"check": name, "exitCode": proc.returncode}), flush=True)
        if proc.returncode:
            raise RuntimeError(name+" failed")

    try:
        for binary, flag in (("go", "version"), (args.python, "--version"),
                             (str(args.pg_bin / "postgres"), "--version"), ("ffmpeg", "-version")):
            report.setdefault("environment", {})[binary] = subprocess.check_output([binary, flag], text=True, env=env).splitlines()[0]
        run("python-dependencies", [args.python, "-c", "import importlib.metadata as m; print(chr(10).join(sorted(d.metadata['Name']+'=='+d.version for d in m.distributions())))"])
        run("pg-init", [str(args.pg_bin/"initdb"), "-D", str(pgdata), "-A", "trust", "--no-locale", "-E", "UTF8"])
        (pgdata/".astralive-f-owned").write_text(owner)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1",0))
            port = sock.getsockname()[1]
        with (pgdata/"postgresql.conf").open("a") as handle:
            handle.write(f"\nport={port}\nlisten_addresses='127.0.0.1'\nunix_socket_directories='{pgdata}'\n")
        run("pg-start", [str(args.pg_bin/"pg_ctl"), "-D", str(pgdata), "-l", str(pgdata/"postgres.log"), "start"])
        started = True
        run("pg-database", [str(args.pg_bin/"createdb"), "-h", "127.0.0.1", "-p", str(port), "astralive_real_golden"])
        username = subprocess.check_output(["id", "-un"], text=True, env=env).strip()
        env["DURABILITY_TEST_DATABASE_URL"] = f"postgres://{username}@127.0.0.1:{port}/astralive_real_golden?sslmode=disable"
        with tempfile.TemporaryDirectory(prefix="astralive-f-golden-source-") as temp:
            root = Path(temp)
            proc = subprocess.Popen(["git", "-C", str(args.repo), "archive", source], stdout=subprocess.PIPE)
            with tarfile.open(fileobj=proc.stdout, mode="r|*") as tar:
                tar.extractall(root, filter="data")
            if proc.wait():
                raise RuntimeError("immutable source archive failed")
            case = "TestPostgresRealGPUContinuityGolden"
            run("golden", ["go", "test", "-count=1", f"-timeout={seconds+600}s", "-v", "./internal/narration", "-run", "^"+case+"$"], root/"backend")
            if "--- PASS: "+case+" " not in (out/"golden.log").read_text():
                raise RuntimeError("Golden case did not execute successfully; skipped/missing case cannot pass")
            if not (out/"media").is_dir():
                raise RuntimeError("real Golden case produced no evidence; possible skipped test")
    except Exception as error:
        failure = str(error)
        report["error"] = failure
    finally:
        marker = pgdata/".astralive-f-owned"
        clean = not started
        if started and marker.is_file() and marker.read_text()==owner:
            with (out/"pg-stop.log").open("wb") as handle:
                stopped = subprocess.run([str(args.pg_bin/"pg_ctl"), "-D", str(pgdata), "-m", "fast", "stop"], env=env, stdout=handle, stderr=subprocess.STDOUT)
            clean = stopped.returncode==0
        if clean:
            shutil.rmtree(pgdata)
        report["ownedPGCleanup"] = "PASS" if clean else "FAIL"
        leaks = []
        secrets = [path.read_bytes().strip() for path in (args.key_file, args.worker_token_file, args.management_token_file)]
        for path in sorted(out.rglob("*")):
            if path.is_file() and path.suffix in (".json", ".log", ".txt", ".html", ".csv"):
                raw = path.read_bytes()
                if any(len(value)>=16 and value in raw for value in secrets):
                    leaks.append(str(path.relative_to(out)))
        report["credentialEvidenceAudit"] = "FAIL" if leaks else "PASS"
        if leaks:
            report["privateArtifactsMustNotPublish"] = leaks
        report["status"] = "PASS_EXECUTED_SOFTWARE_GATE" if failure is None and clean and not leaks else "FAIL"
        report["artifacts"] = [{"path": str(path.relative_to(out)), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size}
                               for path in sorted(out.rglob("*")) if path.is_file() and path.name!="result.json"]
        save()
        print(json.dumps({"source": source, "status": report["status"]}), flush=True)
    return int(report["status"]!="PASS_EXECUTED_SOFTWARE_GATE")


if __name__=="__main__":
    raise SystemExit(main())
