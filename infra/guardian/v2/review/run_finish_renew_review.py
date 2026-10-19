"""Fixed-source original Agent4 probes + bounded RTMP repetitions, owned CPU only.

Copies original probe bytes exactly. The executable copy replaces only its OUT
directory, as authorized; assertions, inputs and time windows remain unchanged.
Each run needs a new output directory; every nonzero exit is retained.
"""

import argparse
import hashlib
import json
import os
import resource
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SOURCES = (
    ROOT / "docs/v0.5/evidence/agent-4/pr11-rereview-2026-10-19/independent-probes"
)
PROBES = [
    (
        "deterministic-race",
        "test_finish_renew_race",
        "/tmp/agent4-pr11-rereview-finish-renew-results",
    ),
    (
        "deterministic-budget",
        "test_finish_renew_budget",
        "/tmp/agent4-pr11-rereview-finish-renew-budget-results",
    ),
    ("rtmp-ledger-20", "test_agent4_rtmp", "/tmp/agent4-pr11-rereview-rtmp-results"),
    (
        "rtmp-phases-20",
        "test_agent4_rtmp_phases",
        "/tmp/agent4-pr11-rereview-rtmp-phase-results",
    ),
    (
        "stress-phases-8",
        "test_agent4_rtmp_phases",
        "/tmp/agent4-pr11-rereview-rtmp-phase-results",
    ),
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=False)
    own = Path(tempfile.mkdtemp(prefix="ag5-final-finish-probes-", dir="/tmp"))
    (own / "AGENT5_OWNED").write_text("private probe copies only\n")
    env = dict(
        os.environ,
        PYTHONPATH=str(ROOT / "runtime") + os.pathsep + str(ROOT),
        ASTRALIVE_DURABLE_LIVE_ENABLED="false",
    )
    for key in tuple(env):
        if key.startswith("RUN_REAL_") or key in (
            "RUN_FULL_REAL_CHAIN",
            "RUN_WEBRTC_INTEGRATION",
        ):
            env[key] = "0"
    env.pop("AG5_OWNED_CGROUP_PARENT", None)
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()

    def sha(raw):
        return hashlib.sha256(raw).hexdigest()

    original_hashes = {
        p: sha((ROOT / p).read_bytes())
        for p in ("output_guardian/service.py", "output_guardian/process.py")
    }
    rows, provenance = [], []

    def run(name, command):
        before = resource.getrusage(resource.RUSAGE_CHILDREN)
        started = time.monotonic()
        with (args.output / (name + ".txt")).open("xb") as log:
            result = subprocess.run(
                command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT
            )
        after = resource.getrusage(resource.RUSAGE_CHILDREN)
        rows.append(
            dict(
                name=name,
                log=name + ".txt",
                command=command,
                cwd=str(ROOT),
                exitCode=result.returncode,
                seconds=time.monotonic() - started,
                userSeconds=after.ru_utime - before.ru_utime,
                systemSeconds=after.ru_stime - before.ru_stime,
                peakRSSBytes=after.ru_maxrss,
                sourceCommit=commit,
                generatedAtUTC=datetime.now(timezone.utc).isoformat(),
            )
        )
        (args.output / "commands.json").write_text(json.dumps(rows, indent=2) + "\n")
        print(name, result.returncode, flush=True)

    try:
        for name, source, old_out in PROBES:
            raw = (SOURCES / (source + ".py.txt")).read_bytes()
            exact = own / (name + "-exact.py")
            exact.write_bytes(raw)
            output = args.output / name
            output.mkdir()
            assert raw.count(old_out.encode()) == 1
            code = raw.replace(old_out.encode(), str(output).encode())
            executable = own / ("test_" + name.replace("-", "_") + ".py")
            executable.write_bytes(code)
            provenance.append(
                dict(
                    name=name,
                    source=str((SOURCES / (source + ".py.txt")).relative_to(ROOT)),
                    sourceSHA256=sha(raw),
                    exactCopySHA256=sha(exact.read_bytes()),
                    executableSHA256=sha(code),
                    onlyReplacement=dict(before=old_out, after=str(output)),
                )
            )
            (args.output / "probe-provenance.json").write_text(
                json.dumps(provenance, indent=2) + "\n"
            )
            selection = [str(executable)]
            if name == "stress-phases-8":
                selection = [
                    str(executable)
                    + f"::test_original_rtmp_with_passive_diagnostics[{i}]"
                    for i in range(8)
                ]
            run(
                name,
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "-p",
                    "no:cacheprovider",
                    "-p",
                    "output_guardian.tests.conftest",
                    *selection,
                    "-q",
                    "-s",
                    "--tb=short",
                ],
            )
        run(
            "lifecycle",
            [
                sys.executable,
                "-m",
                "pytest",
                "output_guardian/tests/lifecycle",
                "-v",
                "--tb=short",
            ],
        )
        scope = own / "test_agent4_current_scope.py"
        scope.write_bytes((SOURCES / "test_current_scope.py.txt").read_bytes())
        run(
            "independent-cgroup-8",
            [sys.executable, "-m", "pytest", str(scope), "-v", "--tb=short"],
        )
    finally:
        unchanged = all(
            sha((ROOT / p).read_bytes()) == h for p, h in original_hashes.items()
        )
        shutil.rmtree(own)
        (args.output / "source-and-cleanup.json").write_text(
            json.dumps(
                dict(
                    commit=commit,
                    protectedSourceHashes=original_hashes,
                    sourceUnchangedDuringRun=unchanged,
                    probeCopyRoot=str(own),
                    probeCopyRootRemoved=not own.exists(),
                    realCgroupKill=False,
                    sharedServiceTouched=False,
                    gpu="NOT RUN",
                ),
                indent=2,
            )
            + "\n"
        )
    return int(any(row["exitCode"] for row in rows) or not unchanged)


if __name__ == "__main__":
    raise SystemExit(main())
