#!/usr/bin/env python3
"""F-owned local PG -> safe projection -> independent Python oracle gate.

Derives a success-only test overlay from the pinned C test without changing it.
The initial boundary and sink receipts are controlled fixtures, never GPU or
Runtime physical-consumption proof. No cloud or provider credentials are used.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import tarfile
import tempfile
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--source', required=True)
    parser.add_argument('--old-oracle', required=True)
    parser.add_argument('--fixed-oracle', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--python', required=True)
    parser.add_argument('--pg-bin', type=Path, required=True)
    args = parser.parse_args()
    repo = args.repo.resolve()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    env = {k: os.environ[k] for k in ('PATH', 'HOME', 'TMPDIR', 'LANG') if k in os.environ}
    source = subprocess.check_output(['git', '-C', str(repo), 'rev-parse', args.source], text=True).strip()
    report = {'source': source, 'scope': 'local owned real PostgreSQL/A+C transactions; controlled initial boundary and sink receipts; no Runtime/GPU/browser/audibility', 'checks': []}
    tree = out / 'source'
    tree.mkdir()
    archive = subprocess.Popen(['git', '-C', str(repo), 'archive', source], stdout=subprocess.PIPE)
    with tarfile.open(fileobj=archive.stdout, mode='r|*') as handle:
        handle.extractall(tree, filter='data')
    if archive.wait():
        raise RuntimeError('archive failed')
    original = tree / 'backend/internal/narration/canonical_price_postgres_test.go'
    text = original.read_text()
    report['derivedTestParentSHA256'] = hashlib.sha256(original.read_bytes()).hexdigest()
    text = text.replace('func TestPostgresCanonicalCNYPriceDecisionAndCoverage(', 'func TestFPostgresCanonicalProjectionOracleData(', 1)
    text, count = re.subn(r'for _, scenario := range \[\]string\{[^\n]+\} \{', 'for _, scenario := range []string{"success"} {', text, count=1)
    if count != 1 or text.count('\n\t\t})\n\t}\n}\n') != 1:
        raise RuntimeError('pinned test overlay anchor changed')
    text = text.replace('"time"', '"time"\n"os"\n"path/filepath"', 1)
    export = '''
            dump := map[string]json.RawMessage{}
            for name, query := range goldenProofQueries() {
                var projected []byte
                if err := p.QueryRow(ctx, query).Scan(&projected); err != nil { t.Fatal("safe projection", name, err) }
                dump[name] = projected
            }
            encoded, err := json.MarshalIndent(dump, "", "  ")
            if err != nil { t.Fatal(err) }
            output := os.Getenv("F_CANONICAL_PROJECTION_OUTPUT")
            if output == "" { t.Fatal("local evidence output not configured") }
            if err := os.WriteFile(filepath.Join(output, "sql-proof.json"), encoded, 0600); err != nil { t.Fatal(err) }
            t.Log("CONTROLLED_BOUNDARY_SINKS: actual A journal and C policy, no Runtime/GPU consumption claim")
'''
    text = text.replace('\n\t\t})\n\t}\n}\n', export + '\n\t\t})\n\t}\n}\n', 1)
    overlay = tree / 'backend/internal/narration/f_canonical_projection_oracle_test.go'
    overlay.write_text(text)
    subprocess.run(['gofmt', '-w', str(overlay)], check=True, env=env)
    report['overlayChanges'] = ['rename test', 'success-only case', 'add os/filepath imports', 'execute F safe queries and export after existing assertions/Stop']
    report['overlaySHA256'] = hashlib.sha256(overlay.read_bytes()).hexdigest()
    (out / 'generated-overlay.go.txt').write_bytes(overlay.read_bytes())
    queries = tree / 'backend/internal/narration/golden_safe_projection_test.go'
    report['queryFileSHA256'] = hashlib.sha256(queries.read_bytes()).hexdigest()
    pgdata = out / 'pg'
    started = False
    failure = None

    def run(name, command, cwd=None, task_env=None, expected=0):
        clock = time.monotonic()
        with (out / (name + '.log')).open('wb') as log:
            process = subprocess.run(command, cwd=cwd, env=task_env or env, stdout=log, stderr=subprocess.STDOUT)
        raw = (out / (name + '.log')).read_bytes()
        row = {'name': name, 'command': command, 'exitCode': process.returncode, 'expectedExit': expected,
               'seconds': round(time.monotonic() - clock, 3), 'sha256': hashlib.sha256(raw).hexdigest()}
        report['checks'].append(row)
        (out / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps(row), flush=True)
        if process.returncode != expected:
            raise RuntimeError(name + ' unexpected result')

    oracle_driver = '''import json,sys,os,hashlib
from pathlib import Path
import canonical_coverage_audit as pinned_oracle
assert hashlib.sha256(Path(pinned_oracle.__file__).read_bytes()).hexdigest()==os.environ['F_CANONICAL_EXPECTED_ORACLE_SHA256']
from real_golden_audit import canonical_coverage_from_sql
data=json.loads(Path(sys.argv[1]).read_text())
try:
 coverage=canonical_coverage_from_sql(data,data['narrations'][0],data['turns'],data['commits'])
 target=data['narrations'][0]['plan_json']['_cnyPriceCoveragePolicy']['targets'][0]['segmentId']
 turn=data['turns'][0]['turn_id']
 if coverage != {target:[turn]}: raise ValueError('unexpected coverage map')
 print(json.dumps({'status':'PASS','coverageTargets':len(coverage),'scope':'controlled PG policy/sink fixture, not physical playback'}))
except Exception as error:
 print(json.dumps({'status':'FAIL','errorType':type(error).__name__,'code':getattr(error,'code','ORACLE_FAILED')}))
 sys.exit(1)
'''
    (out / 'oracle-driver.py').write_text(oracle_driver)
    try:
        run('pg-init', [str(args.pg_bin / 'initdb'), '-D', str(pgdata), '-A', 'trust', '--no-locale', '-E', 'UTF8'])
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
        with (pgdata / 'postgresql.conf').open('a') as handle:
            handle.write(f"\nport={port}\nlisten_addresses='127.0.0.1'\nunix_socket_directories=''\n")
        run('pg-start', [str(args.pg_bin / 'pg_ctl'), '-D', str(pgdata), '-l', str(out / 'postgres.log'), 'start'])
        started = True
        run('pg-createdb', [str(args.pg_bin / 'createdb'), '-h', '127.0.0.1', '-p', str(port), 'canonical_projection'])
        username = subprocess.check_output(['id', '-un'], text=True, env=env).strip()
        go_env = dict(env, DURABILITY_TEST_DATABASE_URL=f'postgres://{username}@127.0.0.1:{port}/canonical_projection?sslmode=disable', F_CANONICAL_PROJECTION_OUTPUT=str(out))
        run('go-pg-projection', ['go', 'test', '-race', '-count=1', '-timeout=90s', '-v', './internal/narration', '-run', '^TestFPostgresCanonicalProjectionOracleData$'], tree / 'backend', go_env)
        report['sqlSHA256'] = hashlib.sha256((out / 'sql-proof.json').read_bytes()).hexdigest()
        for name, revision, expected in [('old-oracle', args.old_oracle, 1), ('fixed-oracle', args.fixed_oracle, 0)]:
            pin = subprocess.check_output(['git', '-C', str(repo), 'rev-parse', revision], text=True).strip()
            folder = out / name
            folder.mkdir()
            module = subprocess.check_output(['git', '-C', str(repo), 'show', pin + ':integration/v0.5/canonical_coverage_audit.py'])
            (folder / 'canonical_coverage_audit.py').write_bytes(module)
            report.setdefault('oracleSources', {})[name] = {'source': pin, 'moduleSHA256': hashlib.sha256(module).hexdigest()}
            py_env = dict(env, PYTHONPATH=str(folder) + os.pathsep + str(tree / 'integration/v0.5'), F_CANONICAL_EXPECTED_ORACLE_SHA256=hashlib.sha256(module).hexdigest())
            run(name, [args.python, str(out / 'oracle-driver.py'), str(out / 'sql-proof.json')], task_env=py_env, expected=expected)
            current_sql_hash = hashlib.sha256((out / 'sql-proof.json').read_bytes()).hexdigest()
            report.setdefault('inputChecks', {})[name] = {'beforeSHA256': report['sqlSHA256'], 'afterSHA256': current_sql_hash}
            if current_sql_hash != report['sqlSHA256']:
                raise RuntimeError('oracle changed the shared SQL input')
            verdict = json.loads((out / (name + '.log')).read_text().splitlines()[-1])
            if name == 'old-oracle' and verdict.get('code') != 'CANONICAL_CHECKPOINT_SINK_RANGES':
                raise RuntimeError('old oracle failed for a different reason')
            if name == 'fixed-oracle' and (verdict.get('status') != 'PASS' or verdict.get('coverageTargets') != 1):
                raise RuntimeError('fixed oracle did not prove the single target')
    except Exception as error:
        failure = str(error)
        report['error'] = failure
    finally:
        if started:
            run('pg-stop', [str(args.pg_bin / 'pg_ctl'), '-D', str(pgdata), '-m', 'fast', 'stop'])
        report['status'] = 'PASS' if failure is None else 'FAIL'
        report['artifacts'] = {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in out.iterdir() if f.is_file() and f.name != 'result.json'}
        (out / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'source': source, 'status': report['status']}), flush=True)
    return int(failure is not None)


if __name__ == '__main__':
    raise SystemExit(main())
