"""Recheck captured Agent3 Go output using the sole Agent4 Python SDK.
Run from repository root with PYTHONPATH=. and the contract test environment.
Only test fixture data; no Authority, SQL, media or external services.
"""
import hashlib
import json
from pathlib import Path
from astralive_contracts import durable_live_v2 as wire

folder = Path(__file__).resolve().parent
rows = json.loads((folder / "official-wire-artifacts.json").read_text())
for artifact in rows["artifacts"]:
    typed = wire.decode("AnswerArtifact", json.dumps(artifact, ensure_ascii=False).encode())
    wire.verify_answer_artifact_hashes(typed)
for name, requests in (("JournalPrepareAnswer", rows["prepares"]),
                       ("JournalSealAnswer", [rows["seal"]])):
    op = wire.OPERATIONS[name]
    for request in requests:
        wire.decode_request(op.id, json.dumps(request, ensure_ascii=False).encode(),
                            role=op.roles[0], target=op.target, method=op.method,
                            route_template=op.path)
artifacts = rows["artifacts"]
assert artifacts[0]["previousArtifactHash"] is None
assert artifacts[1]["previousArtifactHash"] == artifacts[0]["artifactHash"]
manifest = [{key: a[key] for key in ("artifactId", "sequence", "artifactHash")}
            for a in artifacts]
assert wire.digest(manifest) == rows["seal"]["manifestHash"]
assert hashlib.sha256("".join(a["answerText"] for a in artifacts).encode()).hexdigest() == rows["seal"]["finalAnswerTextHash"]
print("PASS: real Go/Python SDK artifacts=2 prepare=2 seal=1; hashes, chain and manifest")
