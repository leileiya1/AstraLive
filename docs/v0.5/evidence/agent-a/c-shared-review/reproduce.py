#!/usr/bin/env python3
"""Run the A-owned SQL/mutex diagnostic on an immutable C source archive."""
import argparse
import hashlib
import io
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--revision", required=True)
    args = parser.parse_args()
    if not os.environ.get("DURABILITY_TEST_DATABASE_URL"):
        parser.error("set DURABILITY_TEST_DATABASE_URL to an isolated test PostgreSQL database")
    revision = subprocess.check_output(
        ["git", "-C", str(args.repo), "rev-parse", "--verify", args.revision + "^{commit}"],
        text=True,
    ).strip()
    archive = subprocess.check_output(["git", "-C", str(args.repo), "archive", revision])
    fixture = Path(__file__).with_name("a_review_borrowed_stop_test.go.txt").read_bytes()
    print("sourceCommit=" + revision, flush=True)
    print("fixtureSHA256=" + hashlib.sha256(fixture).hexdigest(), flush=True)
    with tempfile.TemporaryDirectory(prefix="astralive-a-c-review-") as directory:
        root = Path(directory)
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            tar.extractall(root, filter="data")
        (root / "backend/internal/app/a_review_borrowed_stop_test.go").write_bytes(fixture)
        result = subprocess.run(
            ["go", "test", "-race", "./internal/app", "-run",
             "^TestAReviewBorrowedRetirementSchedulerLock$", "-count=1", "-v"],
            cwd=root / "backend",
        )
        return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
