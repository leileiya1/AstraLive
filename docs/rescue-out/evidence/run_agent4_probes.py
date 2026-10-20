"""Run Agent4's original PR11 probes unchanged except for their output directory.

Usage: .venv-guardian/bin/python docs/rescue-out/evidence/run_agent4_probes.py <phase> [stale|media]

The probes need the protected v1 ``rig`` fixture, so they are copied into a
temporary package under output_guardian/tests/ for the run and removed after.
Only the literal ``/tmp/agent4-pr11-final-results`` string is rewritten.
"""

import datetime
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = Path(__file__).resolve().parent
SETS = {
    "stale": [
        "test_stale_callbacks",
        "test_real_stale_media_scoped",
        "test_real_stale_media_fresh_output",
        "test_fixture_sql_concurrency",
    ],
    "media": [
        "test_finish_renew_race",
        "test_finish_renew_budget",
        "test_agent4_rtmp",
        "test_agent4_rtmp_phases",
        "test_stress8",
    ],
}


def main(phase, name="stale"):
    out = EVIDENCE / phase / "probe-out"
    (out / "media").mkdir(parents=True, exist_ok=True)
    package = ROOT / "output_guardian/tests/agent4_probes"
    shutil.rmtree(package, ignore_errors=True)
    package.mkdir()
    (package / "__init__.py").write_text("")
    for probe in SETS[name]:
        source = (EVIDENCE / "probes" / (probe + ".original.py")).read_text()
        assert source.count("/tmp/agent4-pr11-final-results") <= 1
        (package / (probe + ".py")).write_text(
            source.replace("/tmp/agent4-pr11-final-results", str(out))
        )
    log = EVIDENCE / phase / f"agent4-probes-{name}.txt"
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=True,
        cwd=ROOT,
        capture_output=True,
        text=True,
    ).stdout.strip()
    service = hashlib.sha256((ROOT / "output_guardian/service.py").read_bytes())
    command = [
        sys.executable,
        "-m",
        "pytest",
        str(package),
        "-p",
        "no:cacheprovider",
        "-q",
        "-rA",
    ]
    try:
        with log.open("w") as f:
            f.write(f"utc={datetime.datetime.now(datetime.UTC).isoformat()}\n")
            f.write(f"head={head}\nservice.py sha256={service.hexdigest()}\n")
            f.write("command=" + " ".join(command) + "\n")
            f.flush()
            result = subprocess.run(
                command, check=False, cwd=ROOT, stdout=f, stderr=f, env=os.environ
            )
            f.write(f"\nexit={result.returncode}\n")
    finally:
        shutil.rmtree(package, ignore_errors=True)
    print(log.read_text()[-1500:])
    return result.returncode


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:3]))
