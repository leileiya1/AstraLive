#!/usr/bin/env python3
"""Create a review digest; this never marks a CCR approved."""
import hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'contracts/v0.5/durable-live-2'
paths=[BASE/n for n in ['schema.json','protocol.json','state-machines.json','examples/protocol.json','examples/objects.json','examples/comment-start.json','examples/hash-vectors.json','examples/go/canonical.go','examples/python/canonical.py']]
paths += [ROOT/'docs/v0.5/ccr'/n for n in ['CCR-ADL-001.md','ANSWER-PREPARATION-CONTRACT.md','CCR-ADL-001-HANDOFF.md']]
files={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
digest=hashlib.sha256(json.dumps(files,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
manifest=dict(ccr='CCR-ADL-001',contractRevision='durable-live-2',analysisBase='01a752baf79c25d4d268167d016c8c62e754cfdf',digestAlgorithm='SHA256(canonical sorted path-to-file-sha256 map)',normativeDigest=digest,files=files)
(BASE/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
ledger=ROOT/'docs/v0.5/ccr/CCR-ADL-001-ACKS.json'
a=json.loads(ledger.read_text())
if a['normativeDigest'] not in ('PENDING_FINAL_MANIFEST',digest) and any(o['status']=='ACK' for o in a['owners']):
    raise SystemExit('Normative edit invalidates prior ACKs; explicit review required')
a['normativeDigest']=digest
ledger.write_text(json.dumps(a,ensure_ascii=False,indent=2)+'\n')
print(digest)
