"""One CPU-only verification pass, with raw logs and explicit boundary labels."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
root = Path(__file__).resolve().parents[3]
evidence = root / 'docs/v0.5/evidence/agent-3'
evidence.mkdir(parents=True, exist_ok=True)
python = sys.executable
env = {**os.environ, 'ASTRALIVE_DIRECTOR_EVIDENCE': str(evidence), 'PYTHONPATH': str(root / 'runtime'), 'NO_COLOR': '1'}
jobs = [
 ('go-race', ['go', 'test', '-count=1', '-race', '-json', './...'], root / 'backend'),
 ('go-vet', ['go', 'vet', './...'], root / 'backend'),
 ('contracts', [python, '-m', 'unittest', 'tests.test_durable_live_contracts', 'tests.test_contracts', '-v'], root),
 ('freeze', [python, 'scripts/validate-durable-live-contracts.py'], root),
 ('runtime-regression', [python, '-m', 'unittest', 'runtime.tests.test_runtime', 'runtime.tests.test_interaction_streaming', 'runtime.tests.test_interaction_faults', 'runtime.tests.test_independent_audit', '-v'], root),
 ('runtime-helper', [python, '-m', 'unittest', 'discover', '-s', 'runtime/tests', '-p', 'test_durable_live_segments.py', '-v'], root),
 ('scheduler-patch', [python, 'docs/v0.5/agent-3/check-patches.py'], root),
 ('frontend-tests', ['bun', 'run', 'test'], root / 'frontend'),
 ('frontend-build', ['bun', 'run', 'build'], root / 'frontend'),
]
def run(job):
 name, cmd, cwd = job
 start = time.monotonic()
 result = subprocess.run(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
 (evidence / (name + '.log')).write_bytes(result.stdout.rstrip(b'\n')+b'\n' if result.stdout else b'')
 return dict(name=name, command=cmd, cwd=str(cwd.relative_to(root)) or '.', exitCode=result.returncode,
             elapsedSeconds=round(time.monotonic()-start, 3), log=name+'.log')
selected = set(sys.argv[1:])
if selected:
    jobs = [job for job in jobs if job[0] in selected]
# Avoid the local schema-export reader racing the tests which create its files.
with ThreadPoolExecutor(max_workers=4) as workers:
 results = list(workers.map(run, jobs))
if not selected or 'go-race' in selected or 'export-schema' in selected:
    results.append(run(('export-schema', [python, 'backend/internal/contentplan/contract/validate_evidence.py', str(evidence)], root)))
if selected and (evidence/'verification.json').exists():
    previous = json.loads((evidence/'verification.json').read_text())['results']
    new = {r['name']: r for r in results}
    results = [new.pop(r['name'], r) for r in previous] + list(new.values())
report = dict(baseMainSHA='7fe5d24810e2df348c58dd7748e97ffbe5cff384', contractRevision='durable-live-1',
              acceptanceLayer='CPU / Mock only; shared production wiring NOT INTEGRATED', results=results,
              notTested=['real PostgreSQL/guardian crash recovery','real DeepSeek/XiaoYa/SoulX/GPU','Chrome/WebRTC','local RTMP','official audience','busy 5/8 second SLA','idle 3/5 second SLA'])
code = [* (root/'backend/internal/contentplan').rglob('*'), * (root/'backend/internal/turnmanager').rglob('*'),
        root/'runtime/app/durable_live_segments.py', root/'runtime/tests/test_durable_live_segments.py',
        root/'frontend/src/features/live-console/TurnManagerPanel.tsx', root/'frontend/src/features/live-console/TurnManagerPanel.test.tsx']
report['implementationSHA256'] = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                                  for p in sorted(code) if p.is_file() and p.suffix in {'.py','.go','.tsx'}}
(evidence/'verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
for row in results: print(row['name'], 'PASS' if row['exitCode']==0 else 'FAIL', row['log'])
raise SystemExit(any(r['exitCode'] for r in results))
