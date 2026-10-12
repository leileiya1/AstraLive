#!/usr/bin/env python3
"""Reproduce A/B integration gaps without merging branches or faking durable ACKs.

Actual Go journal + PostgreSQL + Python HTTP Runtime + B Timeline primitive.
LLM/TTS/media are CPU fixture providers; no C, GPU, Chrome or RTMP acceptance.
Exit 1 means a core integration gate is unavailable; it is retained as failure evidence.
"""
import argparse
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request


def port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def archive(repo, sha, dest):
    proc = subprocess.Popen(["git", "-C", str(repo), "archive", sha, "backend", "runtime", "contracts", "gpu_worker", "tests", "integration"], stdout=subprocess.PIPE)
    with tarfile.open(fileobj=proc.stdout, mode="r|*") as tar:
        tar.extractall(dest, filter="data")
    if proc.wait():
        raise RuntimeError("git archive failed")


def request(url, value=None, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(url, data=None if value is None else json.dumps(value).encode(), headers=headers)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=4) as resp:
            return resp.status, json.load(resp)
    except urllib.error.HTTPError as exc:
        try:
            body = json.load(exc)
        except ValueError:
            body = {"code": "NON_JSON_ERROR"}
        return exc.code, body


def wait(url, child, token=None):
    for _ in range(150):
        if child.poll() is not None:
            raise RuntimeError("owned fixture exited; inspect probe logs")
        try:
            if request(url, token=token)[0] == 200:
                return
        except OSError:
            pass
        time.sleep(.1)
    raise TimeoutError("owned fixture startup timeout")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--a-sha", required=True)
    parser.add_argument("--b-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--pg-bin", type=Path, default=Path("/opt/homebrew/opt/postgresql@17/bin"))
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[2]
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    report = {"scope": "premerge negative core-seam probe; CPU providers, real SQL/Go/Python HTTP, no C/GPU/Chrome/RTMP", "A": args.a_sha, "B": args.b_sha, "merged": False, "checks": [], "coreIntegration": "FAIL"}
    handles = []
    children = []
    pg_started = False
    with tempfile.TemporaryDirectory(prefix="astralive-f-seam-") as tmp:
        work = Path(tmp).resolve()
        a, b, data = work / "a", work / "b", work / "pg"
        a.mkdir(); b.mkdir()
        archive(repo, args.a_sha, a); archive(repo, args.b_sha, b)
        fixture = a / "backend/cmd/f-journal-probe"
        fixture.mkdir()
        shutil.copy(repo / "integration/v0.5/fixtures/journal_probe/main.go", fixture / "main.go")
        # Do not use real deployment environment or provider credentials.
        env = {k: os.environ[k] for k in ("PATH", "HOME", "TMPDIR", "LANG") if k in os.environ}
        pgport, goport, pyport = port(), port(), port()
        journal_token, control_token = secrets.token_hex(32), secrets.token_hex(32)
        journal_file, control_file = work / "journal.token", work / "control.token"
        for path, token in ((journal_file, journal_token), (control_file, control_token)):
            path.write_text(token); path.chmod(0o600)
        subprocess.run([str(args.pg_bin / "initdb"), "-D", str(data), "-A", "trust", "--no-locale", "-E", "UTF8"], check=True, stdout=subprocess.DEVNULL)
        with (data / "postgresql.conf").open("a") as f:
            f.write(f"\nport={pgport}\nlisten_addresses='127.0.0.1'\n")
        try:
            subprocess.run([str(args.pg_bin / "pg_ctl"), "-D", str(data), "-l", str(work / "pg.log"), "start"], check=True, stdout=subprocess.DEVNULL)
            pg_started = True
            user = subprocess.check_output(["id", "-un"], text=True).strip()
            subprocess.run([str(args.pg_bin / "createdb"), "-h", "127.0.0.1", "-p", str(pgport), "f_probe"], check=True)
            env.update(F_PROBE_DATABASE_URL=f"postgres://{user}@127.0.0.1:{pgport}/f_probe?sslmode=disable", F_PROBE_ADDR=f"127.0.0.1:{goport}", RUNTIME_JOURNAL_TOKEN_FILE=str(journal_file))
            binary = work / "journal-probe"
            subprocess.run(["go", "-C", str(a / "backend"), "build", "-o", str(binary), "./cmd/f-journal-probe"], check=True, env=env)
            log = (out / "go-journal.log").open("w"); handles.append(log)
            go = subprocess.Popen([str(binary)], env=env, stdout=log, stderr=subprocess.STDOUT); children.append(go)
            base = f"http://127.0.0.1:{goport}"
            wait(base + "/fixture/capabilities", go)
            tables = request(base + "/fixture/capabilities")[1]
            report["checks"].append({"name": "C/B durable tables", "result": "FAIL" if not all(tables.values()) else "PASS", "tables": tables})
            env.update(PYTHONPATH=str(a / "runtime") + ":" + str(a / "runtime/tests"), ASTRALIVE_DURABILITY_ENABLED="true", ASTRALIVE_EVENT_MODE="postgres_only", SESSION_BINDINGS_ENABLED="false", APP_ENV="development", CONFIG_BACKEND_URL=base, RUNTIME_CONTROL_TOKEN_FILE=str(control_file), RUNTIME_EVENT_SPOOL_DIR=str(work / "spool"), DURABILITY_CPU_EFFECT_FILE=str(work / "cpu-effects.txt"), REDIS_URL="redis://127.0.0.1:1")
            log = (out / "python-runtime.log").open("w"); handles.append(log)
            runtime = subprocess.Popen([sys.executable, "-m", "uvicorn", "durability_cpu_server:app", "--host", "127.0.0.1", "--port", str(pyport)], cwd=a, env=env, stdout=log, stderr=subprocess.STDOUT); children.append(runtime)
            pybase = f"http://127.0.0.1:{pyport}"
            wait(pybase + "/internal/v1/health", runtime, control_token)
            create = {"commandId": "f-legacy-create", "traceId": "f-create-trace", "sessionId": "f-session", "avatar": {"avatarId": "f-avatar", "engine": "MOCK"}, "voice": {"voiceId": "f-voice", "provider": "MOCK"}, "config": {"fps": 25, "preview": {"type": "WEBRTC"}}, "context": {"roomId": "f-room", "systemPrompt": "CPU fixture only"}}
            cmd = request(base + "/fixture/command", {"kind": "BEGIN_RUN", "payload": {"expectedPreviousEpoch": 0, "createSession": create}})[1]
            status, body = request(pybase + "/internal/v0.5/sessions/f-session/commands", cmd, control_token)
            if status != 202:
                raise RuntimeError("ordinary BEGIN_RUN prerequisite failed: " + str(status))
            report["checks"].append({"name": "real journal/Runtime PostgreSQL-only BEGIN_RUN", "result": "PASS", "httpStatus": status})
            statuses = {}
            commands = {}
            for kind in ("START_NARRATION", "COMMIT_SEGMENT", "BEGIN_EPOCH"):
                epoch = 2 if kind == "BEGIN_EPOCH" else 1
                cmd = request(base + "/fixture/command", {"kind": kind, "timelineEpoch": epoch, "payload": {"fixture": "typed negative seam", "expectedPreviousEpoch": 1} if kind == "BEGIN_EPOCH" else {"fixture": "typed negative seam"}})[1]
                commands[kind] = cmd
                status, body = request(pybase + "/internal/v0.5/sessions/f-session/commands", cmd, control_token)
                receipt = request(base + f"/internal/v0.5/durability/sessions/f-session/commands/{cmd['commandId']}", token=journal_token)[1]
                statuses[kind] = {"httpStatus": status, "code": body.get("code"), "executionState": receipt.get("executionState")}
            report["checks"].append({"name": "frozen media/narration command dispatch", "result": "FAIL", "observations": statuses, "limit": "fixture payloads probe registration, not real NarrationPlan generation"})
            cmd = commands["COMMIT_SEGMENT"]
            obs = {"sessionId": "f-session", "runEpoch": 1, "commandId": cmd["commandId"], "receiptSeq": 3, "state": "committed", "producerIncarnation": "f-timeline-probe", "evidenceType": "COMMIT_INSTALLED", "evidenceRef": "f-segment"}
            status, body = request(base + "/internal/v0.5/durability/receipts", obs, journal_token)
            report["checks"].append({"name": "A accepts B committed proof", "result": "FAIL", "httpStatus": status, "code": body.get("code"), "limit": "ordinary A receipt seam, no approved Timeline adapter supplied"})
            os.environ.update({k: env[k] for k in ("CONFIG_BACKEND_URL", "RUNTIME_JOURNAL_TOKEN_FILE")})
            sys.path.insert(0, str(a / "runtime"))
            from app.durability_client import DurabilityClient
            spec = importlib.util.spec_from_file_location("app.media_timeline", b / "runtime/app/media_timeline.py")
            timeline_mod = importlib.util.module_from_spec(spec); sys.modules[spec.name] = timeline_mod; spec.loader.exec_module(timeline_mod)
            async def probe_timeline():
                client = DurabilityClient()
                try:
                    timeline = timeline_mod.MediaTimeline("f-session", 1, sample_rate=16000, journal=client)
                    descriptor = {"sampleCount": 640, "contentHash": "sha256:" + "a" * 64, "utteranceId": "f-utterance", "finalMarker": True, "requiredSinks": ["f-preview"], "videoTiming": {"fps": 25}, "factVersion": "f-fixture-v1"}
                    try:
                        await timeline.CommitSegment(cmd, "f-attempt", 1, descriptor, timeline.position(0), 0)
                        observation = {"result": "PASS"}
                    except (AttributeError, RuntimeError, ValueError) as exc:
                        observation = {"result": "FAIL", "exceptionType": type(exc).__name__, "journalHasRecord": hasattr(client, "record"), "committedSample": timeline.committed_end}
                    report["checks"].append({"name": "B CommitSegment using supplied A client", **observation})
                finally:
                    await client.close()
            asyncio.run(probe_timeline())
            report["coreIntegration"] = "FAIL" if any(c["result"] == "FAIL" for c in report["checks"]) else "PASS"
            report["liveProcesses"] = "actual Go journal and Python uvicorn, owned PostgreSQL, Redis URL unreachable; CPU_SIMULATION providers"
        finally:
            for child in reversed(children):
                if child.poll() is None:
                    child.terminate()
                    try:
                        child.wait(timeout=8)
                    except subprocess.TimeoutExpired:
                        child.kill(); child.wait()
            for handle in handles:
                handle.close()
            if pg_started:
                subprocess.run([str(args.pg_bin / "pg_ctl"), "-D", str(data), "-m", "fast", "stop"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    (out / "result.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 1 if report["coreIntegration"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
