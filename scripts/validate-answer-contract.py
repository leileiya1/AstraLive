#!/usr/bin/env python3
"""Validate the isolated CCR candidate; never activate a production revision."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'contracts/v0.5/durable-live-2'
spec = importlib.util.spec_from_file_location('v1_canonical', ROOT/'scripts/validate-durable-live-contracts.py')
common = importlib.util.module_from_spec(spec)
spec.loader.exec_module(common)
canonical, digest, parse = common.canonical, common.digest, common.parse
SCHEMA = parse((BASE/'schema.json').read_text())
PROTOCOL = parse((BASE/'protocol.json').read_text())
REVISION = 'durable-live-2'

def load(name):
    return parse((BASE/name).read_text())

def validate(name, value):
    Draft202012Validator({'$schema': SCHEMA['$schema'], '$defs': SCHEMA['$defs'], '$ref': '#/$defs/'+name}, format_checker=common.FORMATS).validate(value)

def text_hash(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()

def artifact_hash(artifact):
    return digest({k:v for k,v in artifact.items() if k!='artifactHash'})

def validate_artifact(artifact):
    validate('AnswerArtifact', artifact)
    if artifact['artifactHash'] != artifact_hash(artifact) or artifact['answerTextHash'] != text_hash(artifact['answerText']):
        raise ValueError('ANSWER_CONFLICT')
    if len({f['kind'] for f in artifact['factDependencies']}) != len(artifact['factDependencies']):
        raise ValueError('duplicate answer fact kind')
    if set(artifact['assertionKinds']) != {f['kind'] for f in artifact['factDependencies']}:
        raise ValueError('answer assertions must have exact dependency kinds')
    for fact in artifact['factDependencies']:
        if fact['productId'] != artifact['productId']:
            raise ValueError('cross-product answer fact')
    # This is a conservative fixture boundary check, not a general NLU proof.
    if not artifact['answerText'].endswith(('。', '！', '？', '.', '!', '?')):
        raise ValueError('SEMANTIC_BOUNDARY_INVALID')

def command_hash(command):
    return digest({k:v for k,v in command.items() if k!='requestHash'})

def validate_command(command):
    validate('RuntimeCommand', command)
    if command_hash(command) != command['requestHash'] or text_hash(command['payload']['text']) != command['payload']['textHash']:
        raise ValueError('COMMAND_CONFLICT')

def validate_stream(answer):
    validate('AnswerStream', answer)
    artifacts = [x['artifact'] for x in answer['artifacts']]
    if len(artifacts) != answer['preparedCount'] or sum(len(a['answerText']) for a in artifacts)!=answer['totalCharacters']:
        raise ValueError('answer counters mismatch')
    previous = None
    for sequence, artifact in enumerate(artifacts, 1):
        validate_artifact(artifact)
        if artifact['sequence'] != sequence or artifact['previousArtifactHash'] != previous:
            raise ValueError('ANSWER_GAP')
        for key in ('answerId','commandId','attemptId','sessionId','tenantId','ownerId','runId','runEpoch','producerIncarnation','requestHash'):
            if artifact[key] != answer[key]:
                raise ValueError('cross-answer identity')
        previous=artifact['artifactHash']
    prefix=0
    for item in answer['artifacts']:
        if item['state']!='DRAINED':break
        prefix+=1
    if prefix != answer['drainedPrefix']:
        raise ValueError('drained prefix mismatch')
    if answer['state'] in ('SEALED','COMPLETED'):
        manifest=[{k:a[k] for k in ('artifactId','sequence','artifactHash')} for a in artifacts]
        if digest(manifest)!=answer['manifestHash'] or text_hash(''.join(a['answerText'] for a in artifacts))!=answer['finalAnswerTextHash']:
            raise ValueError('ANSWER_CONFLICT')
    if answer['state']=='COMPLETED' and prefix != len(artifacts):
        raise ValueError('cannot complete undrained answer')

def check_all():
    Draft202012Validator.check_schema(SCHEMA)
    ops={o['operationId']:o for o in PROTOCOL['operations']}
    assert len(ops)==len(PROTOCOL['operations'])==25
    assert PROTOCOL['approvalStatus']=='PENDING_OWNER_ACK' and PROTOCOL['productionEnabled'] is False
    assert all(o['path'].startswith('/internal/v0.5/durable-live-2/') for o in ops.values())
    assert len({(o['target'],o['method'],o['path']) for o in ops.values()})==len(ops)
    fixtures=load('examples/protocol.json')
    assert {f['operationId'] for f in fixtures}==ops.keys() and len(fixtures)==len(ops)
    for row in fixtures:
        op=ops[row['operationId']]
        validate(op['requestSchema'].split('/')[-1],row['request'])
        validate(op['responseSchema'].split('/')[-1],row['response'])
        if row['operationId']=='RuntimeExecute':validate_command(row['request'])
        if row['operationId']=='JournalPrepareAnswer':validate_artifact(row['request']['artifact'])
        if row['operationId']=='JournalQueryAnswer':validate_stream(row['response']['answer'])
    for obj in load('examples/objects.json'):
        validate(obj['schemaRef'].split('/')[-1],obj['value'])
        if obj['name'].startswith('AnswerUnit'):validate_artifact(obj['value'])
        if obj['name']=='CommentCommand':validate_command(obj['value'])
    start=load('examples/comment-start.json')
    validate('JournalStartRequest',start['request'])
    for key in ('response','duplicateResponse'):validate('JournalStartResponse',start[key])
    for vector in load('examples/hash-vectors.json'):
        assert canonical(vector['value']).decode()==vector['canonicalUtf8']
        assert digest(vector['value'])==vector['sha256']
    for name,machine in load('state-machines.json')['machines'].items():
        prop='status' if name in ('BroadcastRun','DispatchIntent') else 'state'
        assert set(machine['states'])==set(SCHEMA['$defs'][name]['properties'][prop]['enum'])
        pairs=set()
        for edge in machine['transitions']:
            pair=(edge['fromState'],edge['toState'])
            assert all(x in machine['states'] for x in pair) and pair not in pairs and edge['guard']
            pairs.add(pair)
    for path,expected in load('protected-files.json')['files'].items():
        assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest()==expected,path
    manifest=load('manifest.json')
    for path,expected in manifest['files'].items():
        assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest()==expected,path
    assert digest(manifest['files'])==manifest['normativeDigest']
    acks=parse((ROOT/'docs/v0.5/ccr/CCR-ADL-001-ACKS.json').read_text())
    assert acks['normativeDigest']==manifest['normativeDigest']
    assert acks['status']=='CCR BLOCKED' and acks['allRequiredAcksReceived'] is False
    return dict(definitions=len(SCHEMA['$defs']),operations=len(ops),goldenVectors=len(load('examples/hash-vectors.json')),protectedFiles=len(load('protected-files.json')['files']))

if __name__=='__main__':
    print('PASS '+json.dumps(check_all(),sort_keys=True))
