"""Validate exported CPU requests/commands against unchanged durable-live-1."""
from pathlib import Path
import hashlib
import json
import sys
from jsonschema import Draft202012Validator, FormatChecker
root = Path(__file__).resolve().parents[4]
base = root / 'contracts/v0.5/durable-live'
schema = json.loads((base / 'schema.json').read_text())
ops = {x['operationId']: x for x in json.loads((base / 'protocol.json').read_text())['operations']}
directory = Path(sys.argv[1])
rows = json.loads((directory / 'cpu-contract-requests.json').read_text())
for row in rows:
    Draft202012Validator({**schema, '$ref': ops[row['operation']]['requestSchema']},
                         format_checker=FormatChecker()).validate(row['request'])
commands = json.loads((directory / 'cpu-commands.json').read_text())
for command in commands.values():
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(command)
    without = {k: v for k, v in command.items() if k != 'requestHash'}
    canonical = json.dumps(without, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    assert hashlib.sha256(canonical.encode()).hexdigest() == command['requestHash']
print(f'PASS: {len(rows)} CPU requests; {len(commands)} commands and canonical hashes; durable-live-1 unchanged')
