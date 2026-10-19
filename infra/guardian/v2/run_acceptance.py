"""Dedicated CPU acceptance; explicitly disables all real provider/GPU opt-ins.

Run using .venv-guardian/bin/python infra/guardian/v2/run_acceptance.py.
Original Guardian fixtures own their temporary PG and MediaMTX processes.
Every command, exit status and full combined output is preserved; no fail/skip
is converted to PASS. This never installs services or enables LIVE.
"""

import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = Path(__file__).parent / "evidence"


def main():
    EVIDENCE.mkdir(exist_ok=True)
    test_env = dict(
        os.environ, PYTHONPATH="runtime:.", ASTRALIVE_DURABLE_LIVE_ENABLED="false"
    )
    for name in (
        "RUN_FULL_REAL_CHAIN",
        "RUN_REAL_AVATAR_INTEGRATION",
        "RUN_WEBRTC_INTEGRATION",
        "RUN_REAL_TTS_INTEGRATION",
        "RUN_REAL_LLM_WITH_TTS",
        "RUN_REAL_LLM_INTEGRATION",
    ):
        test_env[name] = "0"
    py = sys.executable  # retain venv path, do not resolve its symlink
    commands = [
        (
            "guardian-v2",
            [
                py,
                "-m",
                "pytest",
                "output_guardian/tests/v2",
                "-v",
                "--junitxml=" + str(EVIDENCE / "guardian-v2.xml"),
            ],
        ),
        (
            "guardian-original",
            [
                py,
                "-m",
                "pytest",
                "output_guardian/tests/test_guardian.py",
                "output_guardian/tests/test_supervisor_cleanup.py",
                "-v",
                "--junitxml=" + str(EVIDENCE / "guardian-original.xml"),
            ],
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
            "journal-11",
            [py, "-m", "pytest", "runtime/tests/test_durable_live_journal.py", "-v"],
        ),
        (
            "runtime-unit",
            [
                py,
                "-m",
                "unittest",
                "discover",
                "-s",
                "runtime/tests",
                "-p",
                "test_*.py",
                "-v",
            ],
        ),
        ("validator-v2", [py, "scripts/validate-answer-contract.py"]),
        ("validator-v1", [py, "scripts/validate-durable-live-contracts.py"]),
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
                "infra/guardian/v2/run_acceptance.py",
            ],
        ),
        ("diff-check", ["git", "diff", "--check"]),
    ]
    results = []
    for name, command in commands:
        target = EVIDENCE / (name + ".txt")
        # Each named run writes a new directory or must explicitly preserve the
        # prior failed evidence before rerunning; no silent overwrite.
        if target.exists():
            raise SystemExit("evidence exists; preserve it before rerunning")
        began = time.monotonic()
        with target.open("x") as log:
            result = subprocess.run(
                command, cwd=ROOT, env=test_env, stdout=log, stderr=subprocess.STDOUT
            )
        row = dict(
            name=name,
            command=command,
            cwd=str(ROOT),
            exitCode=result.returncode,
            seconds=round(time.monotonic() - began, 3),
            output=target.name,
        )
        results.append(row)
        print(json.dumps(row), flush=True)
        (EVIDENCE / "commands.json").write_text(json.dumps(results, indent=2) + "\n")
    files = {}
    for pattern in (
        "output_guardian/v2/*.py",
        "output_guardian/tests/v2/*.py",
        "infra/guardian/v2/*.service",
        "infra/guardian/v2/*.conf",
        "infra/guardian/v2/run_acceptance.py",
    ):
        for path in ROOT.glob(pattern):
            files[str(path.relative_to(ROOT))] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
    source = dict(
        implementationCommit=subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        baseline="e98d8cf53d1aa5518f9c908785b7a5feae5117f8",
        timestamp=datetime.now(timezone.utc).isoformat(),
        platform=platform.platform(),
        python=sys.version,
        files=files,
        realProviderOptIns="all explicitly disabled",
        gpu="NOT TESTED",
        production="OUTPUT_FENCE_UNPROVEN",
    )
    (EVIDENCE / "source-manifest.json").write_text(json.dumps(source, indent=2) + "\n")
    return int(any(row["exitCode"] != 0 for row in results))


if __name__ == "__main__":
    raise SystemExit(main())
