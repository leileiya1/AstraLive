#!/usr/bin/env python3
"""Pinned CPU serializer-boundary diagnostic; no HTTP/GPU/media acceptance."""
import argparse
import asyncio
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--a", default="edd4e1ed2dae2056d69e899991ed877fc3811f77")
    parser.add_argument("--b", default="dda7936faba56efe01659b6393a4d32a93322508")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = {"a": args.a, "b": args.b, "scope": "CPU B identity/A SQLite proof staging; diagnostic payload, no HTTP/PG dispatch/GPU", "sources": {}, "cases": []}
    with tempfile.TemporaryDirectory(prefix="astralive-f-worker-id-") as root:
        package = Path(root) / "app"
        package.mkdir()
        (package / "__init__.py").write_text("")
        for filename, pin in (("media_timeline.py", args.b), ("providers.py", args.b),
                              ("models.py", args.b), ("durability_client.py", args.a),
                              ("durable_events.py", args.a)):
            raw = subprocess.check_output(["git", "-C", args.repo, "show", f"{pin}:runtime/app/{filename}"])
            (package / filename).write_bytes(raw)
            result["sources"][filename] = hashlib.sha256(raw).hexdigest()
        sys.path.insert(0, root)
        from app.media_timeline import Lane, MediaIdentity
        from app.durable_events import DurableEventPublisher
        from app.durability_client import JournalError
        spool = DurableEventPublisher(SimpleNamespace(incarnation="f_probe"), str(Path(root) / "spool"))
        try:
            for value in (2**53 - 1, 2**53, 2**63 - 1, 2**63):
                case = {"workerGenerationId": value, "frozenWireValid": 0 < value < 2**63}
                try:
                    identity = MediaIdentity("s", 1, 1, 1, "seg", "utt", Lane.NARRATION, "worker", value)
                    case["bIdentityAccepted"] = True
                except ValueError:
                    case["bIdentityAccepted"] = False
                    result["cases"].append(case)
                    continue
                # This exercises actual staging serialization, not Go semantic admission.
                try:
                    spool.stage_timeline({"operation": "SEGMENT_READY", "command": {"commandId": f"cmd_{value}"},
                                          "proof": {"identity": asdict(identity)}, "producerIncarnation": "f_probe"})
                    case["aSpoolAccepted"] = True
                except JournalError as error:
                    case.update(aSpoolAccepted=False, errorCode=error.code)
                result["cases"].append(case)
        finally:
            asyncio.run(spool.close())
    mismatch = any(case["frozenWireValid"] and not case.get("aSpoolAccepted", False) for case in result["cases"])
    result["status"] = "FAIL" if mismatch else "PASS"
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return int(mismatch)


if __name__ == "__main__":
    raise SystemExit(main())
