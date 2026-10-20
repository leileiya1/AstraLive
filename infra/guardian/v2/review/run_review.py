"""CPU-only owner regression. New output directory required; retain every result.

Run with .venv-guardian/bin/python .../run_review.py --output <new directory>.
No shared service, GPU, installation or live output is invoked. The v1 fixtures
own their local PostgreSQL, MediaMTX and FFmpeg. Protection failures are recorded
as failures; Agent5 must not rewrite the protected-file inventory.
"""

import argparse
import json
import os
import platform
import resource
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cold-repeats", type=int, default=20)
    parser.add_argument("--base", default="0cc1a141e443ee1069dc997a91182e4b48257be5")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    env = dict(
        os.environ, PYTHONPATH="runtime:.", ASTRALIVE_DURABLE_LIVE_ENABLED="false"
    )
    for key in tuple(env):
        if key.startswith("RUN_REAL_") or key in (
            "RUN_FULL_REAL_CHAIN",
            "RUN_WEBRTC_INTEGRATION",
        ):
            env[key] = "0"
    env.pop(
        "AG5_OWNED_CGROUP_PARENT", None
    )  # this round authorizes NO real cgroup test
    py = sys.executable
    source_commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    rows = []

    def run(name, command, *, probe=False):
        child_env = dict(env)
        if probe:
            child_env.update(
                PYTHONPATH=str(Path(__file__).parent) + os.pathsep + "runtime:.",
                AG5_PROBE=str(args.output.resolve() / (name + ".json")),
            )
        before = resource.getrusage(resource.RUSAGE_CHILDREN)
        start = time.monotonic()
        with (args.output / (name + ".txt")).open("x") as log:
            result = subprocess.run(
                command, cwd=ROOT, env=child_env, stdout=log, stderr=subprocess.STDOUT
            )
        after = resource.getrusage(resource.RUSAGE_CHILDREN)
        row = dict(
            name=name,
            command=command,
            cwd=str(ROOT),
            exitCode=result.returncode,
            seconds=time.monotonic() - start,
            userSeconds=after.ru_utime - before.ru_utime,
            systemSeconds=after.ru_stime - before.ru_stime,
            peakRSSBytes=after.ru_maxrss,
            generatedAtUTC=datetime.now(timezone.utc).isoformat(),
            sourceCommit=source_commit,
        )
        rows.append(row)
        (args.output / "commands.json").write_text(json.dumps(rows, indent=2) + "\n")
        print(json.dumps(row), flush=True)

    tests = [
        (
            "v1-25",
            [
                py,
                "-m",
                "pytest",
                "output_guardian/tests/test_guardian.py",
                "output_guardian/tests/test_supervisor_cleanup.py",
                "-v",
                "--tb=short",
            ],
        ),
        (
            "v2-original-69",
            [
                py,
                "-m",
                "pytest",
                "output_guardian/tests/v2",
                "--ignore=output_guardian/tests/v2/test_readiness.py",
                "--ignore=output_guardian/tests/v2/test_official.py",
                "--ignore=output_guardian/tests/v2/test_physical.py",
                "--ignore=output_guardian/tests/v2/test_cgroup_scope.py",
                "--ignore=output_guardian/tests/v2/test_evidence_archive.py",
                "-v",
                "--tb=short",
            ],
        ),
        (
            "v2-full",
            [py, "-m", "pytest", "output_guardian/tests/v2", "-v", "--tb=short", "-rs"],
        ),
        (
            "cgroup-inert-56",
            [
                py,
                "-m",
                "pytest",
                "output_guardian/tests/v2/test_cgroup_scope.py",
                "-v",
                "--tb=short",
            ],
        ),
        (
            "wire-13",
            [py, "-m", "unittest", "tests.test_durable_live_v2_wire", "-v"],
        ),
        (
            "contracts-137",
            [
                py,
                "-m",
                "unittest",
                "tests.test_contracts",
                "tests.test_durable_live_contracts",
                "tests.test_durable_answer_contracts",
                "tests.test_answer_contract_repairs",
                "tests.test_receiver_contracts",
                "tests.test_receiver_stop_races",
                "-v",
            ],
        ),
        (
            "official-wire-adapter-21",
            [
                py,
                "-m",
                "unittest",
                "tests.test_receiver1_wiring",
                "tests.test_durable_live_v2_wire",
                "-v",
            ],
        ),
        (
            "journal-11",
            [py, "-m", "pytest", "runtime/tests/test_durable_live_journal.py", "-v"],
        ),
        ("validator-v1", [py, "scripts/validate-durable-live-contracts.py"]),
        ("validator-v2", [py, "scripts/validate-answer-contract.py"]),
        (
            "generated-check",
            [py, "scripts/durable-live/generate_v2_wire.py", "--check"],
        ),
        (
            "lint",
            [
                str(ROOT / ".venv-guardian/bin/ruff"),
                "check",
                "--isolated",
                "--select",
                "E4,E7,E9,F,I",
                "output_guardian/v2",
                "output_guardian/tests/v2",
                "infra/guardian/v2/review",
            ],
        ),
        (
            "diff-check-full-pr",
            [
                "git",
                "diff",
                "--check",
                args.base,
                "HEAD",
            ],
        ),
    ]
    for name, command in tests:
        run(name, command)
    for i in range(args.cold_repeats):
        run(
            f"cold-after-{i:02}",
            [
                py,
                "-m",
                "pytest",
                "-p",
                "ag5_cold_probe",
                "output_guardian/tests/v2/test_cpu.py::test_real_decode_unit1_finish_unit2_same_process_clocks",
                "-q",
                "--tb=short",
            ],
            probe=True,
        )
    for i in range(6):
        run(
            f"delayed-ready-{i:02}",
            [
                py,
                "-m",
                "pytest",
                "output_guardian/tests/v2/test_readiness.py",
                "-v",
                "--tb=short",
            ],
        )
    (args.output / "source.json").write_text(
        json.dumps(
            dict(
                commit=subprocess.check_output(
                    ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
                ).strip(),
                platform=platform.platform(),
                python=sys.version,
                realProviderOptIns="disabled",
                gpu="NOT TESTED",
                production="OUTPUT_FENCE_UNPROVEN",
            ),
            indent=2,
        )
        + "\n"
    )
    return int(any(r["exitCode"] for r in rows))


if __name__ == "__main__":
    raise SystemExit(main())
