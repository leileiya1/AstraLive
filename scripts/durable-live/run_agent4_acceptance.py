"""Agent 4 isolated regression; real SQL/Redis/processes, controlled media evidence.

Never reads .env, starts GPUs, sends business traffic, or kills shared processes.
Retains logs and owned data. Ports must be free, markers gate fault injection.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import resource
import socket
import subprocess
import tempfile
import time

parser = argparse.ArgumentParser()
parser.add_argument('--python', required=True)
parser.add_argument('--evidence-dir', required=True)
args = parser.parse_args()
root = Path(__file__).resolve().parents[2]
evidence = Path(args.evidence_dir).resolve()
evidence.mkdir(parents=True, exist_ok=True)
for port in (55462, 56382):
    with socket.socket() as sock:
        try:
            sock.bind(('127.0.0.1', port))
        except OSError:
            raise SystemExit(f'refuse occupied isolated port {port}')
owned = Path(tempfile.mkdtemp(prefix='astralive-agent2-agent4-', dir='/tmp'))
pg, redis_dir = owned / 'pg', owned / 'redis'
redis_dir.mkdir()
(redis_dir / 'AGENT2_OWNED').touch()  # explicit contract of existing safe probes
# Start from an allowlist. Never inherit provider secrets, cloud flags, a shared
# database target, legacy real-service opt-ins or an ambient production profile.
env = {k: os.environ[k] for k in ('PATH', 'HOME', 'TMPDIR', 'LANG', 'LC_ALL', 'GOCACHE', 'GOMODCACHE') if k in os.environ}
env.update(DURABLE_LIVE_TEST_DATABASE_URL='postgres://127.0.0.1:55462/agent2_agent4_acceptance?sslmode=disable',
           CONFIG_TEST_DATABASE_URL='postgres://127.0.0.1:55462/agent2_agent4_acceptance?sslmode=disable',
           RUN_INTERACTION_CPU='1', INTERACTION_TEST_REDIS_URL='redis://127.0.0.1:56382/1',
           INTERACTION_TEST_PYTHON=str(Path(args.python).absolute()),
           DATABASE_URL='postgres://127.0.0.1:55462/agent2_agent4_acceptance?sslmode=disable',
           DURABLE_LIVE_TEST_REDIS_URL='redis://127.0.0.1:56382/0',
           REDIS_URL='redis://127.0.0.1:56382/0',
           DURABLE_LIVE_TEST_PYTHON=str(Path(args.python).absolute()),
           DURABLE_LIVE_ISOLATED_PGDATA=str(pg), DURABLE_LIVE_ISOLATED_REDISDIR=str(redis_dir),
           PYTHONPATH=str(root / 'runtime') + ':' + str(root / 'runtime/tests'), NO_COLOR='1')
def source_manifest():
    paths = subprocess.check_output(['git', 'ls-files', '-co', '--exclude-standard', '--', 'backend', 'runtime', 'frontend', 'contracts', 'tests', 'scripts'], cwd=root).decode().splitlines()
    return {name: hashlib.sha256((root/name).read_bytes()).hexdigest() for name in sorted(set(paths)) if (root/name).is_file()}

initial_manifest = source_manifest()
(evidence / 'source-manifest.json').write_text(json.dumps(initial_manifest, indent=2) + '\n')
commands = []
report = dict(contractRevision='durable-live-1', ownedCluster=str(owned), commands=commands,
              platform=platform.platform(), gpu={'status': 'NOT TESTED', 'samples': 0, 'reason': 'OUTPUT_FENCE_UNPROVEN and pending CCR-ADL-001'},
              mediaProofs='Controlled fixtures, not production Guardian/GPU/Chrome/RTMP',
              sourceSHA=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip(),
              dirtySource=subprocess.check_output(['git', 'status', '--short'], cwd=root, text=True).splitlines())

def run(cmd, name, cwd=root):
    start = time.monotonic()
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    with (evidence / name).open('w') as log:
        result = subprocess.run(cmd, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT)
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    commands.append(dict(command=cmd, cwd=str(cwd.relative_to(root)) if cwd != root else '.', exitCode=result.returncode, log=name,
                         elapsedSeconds=round(time.monotonic()-start, 3), userCPUSeconds=round(after.ru_utime-before.ru_utime, 3),
                         systemCPUSeconds=round(after.ru_stime-before.ru_stime, 3), cumulativeChildrenPeakRSS=after.ru_maxrss,
                         rssUnit='bytes' if platform.system() == 'Darwin' else 'KiB'))
    (evidence / 'acceptance.json').write_text(json.dumps(report, indent=2) + '\n')
    print(('PASS' if result.returncode == 0 else 'FAIL'), name, flush=True)
    if result.returncode:
        raise RuntimeError(f'{name}: exit {result.returncode}; inspect raw log')

pg_started = redis_started = False
try:
    run(['initdb', '-D', str(pg), '--auth=trust', '--no-locale', '-E', 'UTF8'], 'initdb.log')
    (pg / 'AGENT2_OWNED').touch()
    run(['pg_ctl', '-D', str(pg), '-l', str(owned / 'postgres.log'), '-o', '-h 127.0.0.1 -p 55462 -k /tmp', '-w', 'start'], 'postgres-start.log')
    pg_started = True
    run(['createdb', '-h', '127.0.0.1', '-p', '55462', 'agent2_agent4_acceptance'], 'createdb.log')
    run(['redis-server', '--bind', '127.0.0.1', '--port', '56382', '--dir', str(redis_dir), '--save', '', '--appendonly', 'no', '--daemonize', 'yes', '--pidfile', str(redis_dir / 'redis.pid'), '--logfile', str(redis_dir / 'redis.log')], 'redis-start.log')
    redis_started = True
    # Sequential packages prevent intentional PostgreSQL shutdown in fault probes
    # from disrupting unrelated concurrently executing regression packages.
    run(['go', 'test', '-p', '1', './...', '-count=1', '-json'], 'go-test.jsonl', root / 'backend')
    run(['go', 'test', '-race', '-p', '1', './...', '-count=1', '-json'], 'go-race.jsonl', root / 'backend')
    run(['go', 'vet', './...'], 'go-vet.log', root / 'backend')
    run([args.python, '-m', 'unittest', 'discover', '-s', 'runtime/tests', '-p', 'test_*.py', '-v'], 'runtime-unittest.log')
    run([args.python, '-m', 'pytest', 'runtime/tests/test_durable_live_journal.py', '-q'], 'runtime-journal.log')
    run([args.python, 'scripts/validate-durable-live-contracts.py'], 'contract-schema.log')
    run([args.python, '-m', 'unittest', 'tests.test_contracts', 'tests.test_durable_live_contracts', '-v'], 'contract-unittest.log')
    run(['bun', 'install', '--frozen-lockfile'], 'bun-install.log', root / 'frontend')
    run(['bun', 'run', 'test'], 'bun-test.log', root / 'frontend')
    run(['bun', 'run', 'build'], 'bun-build.log', root / 'frontend')
    run(['git', 'diff', '--check'], 'diff-check.log')
    # Dedicated binary tool versions; no Provider/Worker environment is dumped.
    for name, cmd in [('go-version', ['go', 'version']), ('python-version', [args.python, '--version']), ('postgres-version', ['postgres', '--version']), ('redis-version', ['redis-server', '--version']), ('bun-version', ['bun', '--version'])]:
        run(cmd, name + '.log')
finally:
    cleanup = []
    if redis_started:
        cleanup.append(subprocess.run(['redis-cli', '-h', '127.0.0.1', '-p', '56382', 'shutdown', 'nosave'], env=env, capture_output=True).returncode)
    if pg_started:
        cleanup.append(subprocess.run(['pg_ctl', '-D', str(pg), '-m', 'fast', '-w', 'stop'], env=env, capture_output=True).returncode)
    report['sourceUnchangedDuringVerification'] = source_manifest() == initial_manifest
    report['ownedServicesCleanupExitCodes'] = cleanup
    (evidence / 'acceptance.json').write_text(json.dumps(report, indent=2) + '\n')
    print('Owned services stopped; disposable data retained:', owned, flush=True)
