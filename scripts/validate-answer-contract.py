#!/usr/bin/env python3
"""Validate the isolated CCR candidate; never activate a production revision."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from datetime import datetime
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

def drain_identity(request):
    return {'operation':'JournalConfirmAnswerSegment',**{
        k:v for k,v in request.items() if k not in ('requestId','expectedAnswerRevision')}}

def validate_lifecycle_trace(trace):
    """Trusted fixture cross-language timing check, not live authorization."""
    validate('AnswerLifecycleTrace',trace)
    def when(value):return datetime.fromisoformat(value.replace('Z','+00:00'))
    grant,binding=trace['grant'],trace['consumption']
    registration=trace['registration']
    if registration['state']!='ACTIVE':raise ValueError('REGISTRATION_REVOKED')
    if digest(registration['binding'])!=registration['registrationHash']:raise ValueError('registration hash mismatch')
    for key,value in registration['binding'].items():
        if key in binding and binding[key]!=value:raise ValueError('bootstrap binding mismatch')
    if when(registration['registeredAt'])>when(binding['consumedAt']):raise ValueError('BOOTSTRAP_REQUIRED')
    issued,consume,deadline=map(when,(grant['issuedAt'],binding['consumedAt'],grant['expiresAt']))
    if not issued<=consume<deadline:raise ValueError('GRANT_EXPIRED')
    keys=('tenantId','ownerId','runId','commandId','attemptId','sessionId','runEpoch',
          'producerIncarnation','answerId','artifactId','artifactHash','generationId')
    for key in keys:
        if key in grant and grant[key]!=binding[key]:raise ValueError('grant identity mismatch')
    if grant['grantId']!=binding['grantId']:raise ValueError('grant mismatch')
    def unique(rows,key):
        result={r[key]:r for r in rows}
        if len(result)!=len(rows):raise ValueError('duplicate proof ID')
        return result
    observations=unique(trace['observations'],'observationId')
    permits=unique(trace['permits'],'permitId')
    first_observation=observations[grant['factObservationId']]
    previous=consume
    def proof(permit,at):
        observation=observations[permit['factObservationId']]
        for row in (permit,observation):
            if any(row[k]!=binding[k] for k in keys):raise ValueError('renewed proof identity mismatch')
        if permit['guardianIncarnation']!=binding['guardianIncarnation']:raise ValueError('guardian restart')
        if not when(permit['issuedAt'])<=at<when(permit['expiresAt']):raise ValueError('permit expired')
        if (when(permit['expiresAt'])-when(permit['issuedAt'])).total_seconds()>1:raise ValueError('unbounded permit')
        if not when(observation['verifiedAt'])<=at<when(observation['validUntil']):raise ValueError('FACT_EXPIRED')
        if (when(observation['validUntil'])-when(observation['verifiedAt'])).total_seconds()>2:raise ValueError('unbounded fact proof')
        for key in ('productSnapshotVersion','factSetHash'):
            if observation[key]!=first_observation[key]:raise ValueError('changed answer facts')
        return observation
    proof(permits[grant['permitId']],consume)
    for handoff in trace['handoffs']:
        at=when(handoff['at'])
        if at<previous or handoff['executionId']!=binding['executionId']:raise ValueError('execution changed')
        observation=proof(permits[handoff['permitId']],at)
        if observation['observationId']!=handoff['factObservationId']:raise ValueError('observation mismatch')
        previous=at
    return dict(handoffs=len(trace['handoffs']),lastOffsetMs=round((previous-issued).total_seconds()*1000),
                initialConsumeWindowMs=round((deadline-issued).total_seconds()*1000),
                globalStartCount=trace['globalStartCount'],unitGrantCount=trace['unitGrantCount'])

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

def receiver_ticket_verifier(registration,grant_id,ticket):
    return digest(dict(domain='receiver-consume-ticket-1',contractRevision=REVISION,
                       receiverRevision='receiver-1',grantId=grant_id,
                       registrationHash=registration['registrationHash'],
                       runtimePrincipalId=registration['binding']['runtimePrincipalId'],ticket=ticket))

def check_receiver():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    import base64
    protocol=load('receiver-protocol.json');ops={x['operationId']:x for x in protocol['operations']}
    assert len(ops)==13 and protocol['productionEnabled'] is False
    assert protocol['approvalStatus']=='PENDING_AGENT2_STOP_REPAIR_FINAL_ACK'
    sync=protocol['localSynchronization']
    assert sync['trace']=='examples/receiver-stop-trace.json'
    assert len({(o['target'],o['path']) for o in ops.values()})==len(ops)
    assert all(o['path'].startswith(('/internal/v0.5/durable-live-2/receiver/','/guardian/durable-live-2/','/registrar/receiver-1/')) for o in ops.values())
    def closure(name,seen):
        if name in seen:return
        seen.add(name)
        def walk(v):
            if isinstance(v,dict):
                if '$ref' in v:closure(v['$ref'].split('/')[-1],seen)
                for value in v.values():walk(value)
            elif isinstance(v,list):
                for value in v:walk(value)
        walk(SCHEMA['$defs'][name])
    reachable=set()
    for op in ops.values():
        for side in ('requestSchema','responseSchema'):closure(op[side].split('/')[-1],reachable)
    assert {'AnswerExecutionBinding','AnswerFactObservation','AnswerPlaybackPermit','ReceiverBootstrapBinding'}<=reachable
    fixtures=load('examples/receiver-protocol.json')
    assert {f['operationId'] for f in fixtures}==ops.keys() and len(fixtures)==len(ops)
    for f in fixtures:
        op=ops[f['operationId']]
        for side in ('request','response'):validate(op[side+'Schema'].split('/')[-1],f[side])
    trace=load('examples/receiver-trace.json')
    assert trace['initialAuthority']==dict(registered=False,generationId=None,guardianIncarnation=None)
    all_ops={**{o['operationId']:o for o in PROTOCOL['operations']},**ops}
    messages=trace['messages'];names=[m['operationId'] for m in messages]
    assert names.index('ReceiverStage')<names.index('RegisterReceiverBootstrap')<names.index('JournalPrepareAnswer')<names.index('AcquireOutputPermit')<names.index('JournalStart')<names.index('CommitReceiverConsume')<names.index('ReceiverConsume')<names.index('ReceiverMedia')<names.index('JournalConfirmAnswerSegment')<names.index('JournalStartAnswerSegment')
    registration=next(m['response']['registration'] for m in messages if m['operationId']=='RegisterReceiverBootstrap')
    assert digest(registration['binding'])==registration['registrationHash']
    stage=next(m for m in messages if m['operationId']=='ReceiverStage');receipt=stage['response']['receipt']
    assert stage['request']['binding']==registration['binding'] and receipt['bindingHash']==registration['registrationHash']
    assert stage['request']['challenge']==receipt['challenge']
    public=Ed25519PublicKey.from_public_bytes(base64.b64decode(trace['trustedPublicKeys'][receipt['keyId']]))
    public.verify(base64.b64decode(receipt['signature']),canonical({k:v for k,v in receipt.items() if k!='signature'}))
    grants={};latched=set()
    for m in messages:
        op=all_ops[m['operationId']]
        for side in ('request','response'):validate(op[side+'Schema'].split('/')[-1],m[side])
        name=m['operationId'];out=m['response'];request=m['request']
        if name in ('JournalStart','JournalStartAnswerSegment'):
            grant=out.get('answerGrant',out.get('grant'));assert out['consumeTicket']
            grants[grant['grantId']]=out['consumeTicket']
        if name=='QueryReceiverAuthority':
            snapshot=out['snapshot'];assert 'consumeTicket' not in snapshot and 'consumeTicket' not in snapshot['grant']
            validate_artifact(snapshot['artifact'])
            assert snapshot['registration']['registrationHash']==registration['registrationHash']
        if name=='CommitReceiverConsume' and out['consumeAuthorized']:
            record=out['consumption'];grant_id=request['references']['grantId']
            assert grant_id not in latched and grants[grant_id]==request['consumeTicket'];latched.add(grant_id)
            verifier=receiver_ticket_verifier(registration,grant_id,request['consumeTicket'])
            identity=digest(dict(domain='receiver-consume-identity-1',guardianPrincipalId=record['guardianPrincipalId'],request={k:v for k,v in request.items() if k not in ('requestId','consumeTicket')},ticketVerifier=verifier))
            assert identity==record['consumeIdentityHash']
    assert len(latched)==2 and names.count('JournalStart')==1
    return dict(privateOperations=len(ops),reachableDefinitions=len(reachable),messages=len(messages))

def check_receiver_stop_trace():
    """Verify typed Stop examples and the local commit order, not live sinks."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    import base64
    trace=load('examples/receiver-stop-trace.json')
    assert trace['contractRevision']==REVISION and trace['receiverRevision']=='receiver-1'
    expected={'A_LOCAL_STOP_BEFORE_BACKEND':('ACTIVE',0),
              'B_STOP_DURING_MEDIA_QUERY':('REVOKED',1),
              'C_STOP_DURING_LAST_CONSUME_QUERY':('REVOKED',1)}
    assert {s['scenario'] for s in trace['scenarios']}==expected.keys() and len(trace['scenarios'])==3
    for row in trace['scenarios']:
        assert row['initialAuthority']==dict(registered=False,generationId=None,guardianIncarnation=None)
        stage,register=row['bootstrapMessages']
        assert stage['operationId']=='ReceiverStage' and register['operationId']=='RegisterReceiverBootstrap'
        for message in (stage,register):
            for side in ('request','response'):validate(message['operationId']+side.title(),message[side])
        registration=register['response']['registration'];binding=registration['binding'];receipt=stage['response']['receipt']
        assert binding==stage['request']['binding'] and digest(binding)==registration['registrationHash']==receipt['bindingHash']
        assert stage['request']['challenge']==receipt['challenge']
        for key,value in row['physicalInstallation'].items():
            if key in binding:assert binding[key]==value
        public=Ed25519PublicKey.from_public_bytes(base64.b64decode(row['trustedPublicKeys'][receipt['keyId']]))
        public.verify(base64.b64decode(receipt['signature']),canonical({k:v for k,v in receipt.items() if k!='signature'}))
        stop,denied=row['operations']
        assert stop['operationId']=='ReceiverStop' and stop['request']['runId']==binding['runId']
        for side in ('request','response'):validate('ReceiverStop'+side.title(),stop[side])
        assert stop['response']['state']=='CLOSED_FENCED'
        validate(denied['operationId']+'Request',denied['request']);validate('ReceiverErrorResponse',denied['error'])
        assert 'response' not in denied and denied['request']['requestId']==denied['error']['requestId']
        assert denied['error']['code'] in ('RUN_STOPPED','CONSUMPTION_UNKNOWN')
        commits=row['linearized'];stop_at=next(i for i,e in enumerate(commits) if e['kind']=='STOP')
        assert not any(e['kind'] in ('MEDIA','RENEW','FINISH','CONSUME_ACK') for e in commits[stop_at+1:])
        assert [e['barrierRevision'] for e in commits]==sorted(e['barrierRevision'] for e in commits)
        out=row['outcome'];state,count=expected[row['scenario']]
        assert out['barrierState']=='FENCED' and out['backendRegistrationState']==state and out['latchCount']==count
        assert out['ttsBefore']==out['ttsAfter'] and out['acceptedMediaBefore']==out['acceptedMediaAfter']==0
        assert out['localAuditStates']==(['UNKNOWN'] if count else [])
        if row['scenario'].startswith('A'):assert out['ttsAfter']==0 and denied['error']['code']=='RUN_STOPPED'
        if row['scenario'].startswith('C'):assert out['ttsAfter']==0 and not any(e['kind']=='CONSUME_ACK' for e in commits)
    return len(trace['scenarios'])

def check_all():
    Draft202012Validator.check_schema(SCHEMA)
    receiver=check_receiver()
    stop_scenarios=check_receiver_stop_trace()
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
        if row['operationId']=='JournalConfirmAnswerSegment':
            assert row['response']['drainIdentityHash']==digest(drain_identity(row['request']))
    for obj in load('examples/objects.json'):
        validate(obj['schemaRef'].split('/')[-1],obj['value'])
        if obj['name'].startswith('AnswerUnit'):validate_artifact(obj['value'])
        if obj['name']=='CommentCommand':validate_command(obj['value'])
    start=load('examples/comment-start.json')
    validate('JournalStartRequest',start['request'])
    for key in ('response','duplicateResponse'):validate('JournalStartResponse',start[key])
    validate_lifecycle_trace(load('examples/grant-renewal-trace.json'))
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
    return dict(stopScenarios=stop_scenarios,definitions=len(SCHEMA['$defs']),privateOperations=receiver['privateOperations'],machines=len(load('state-machines.json')['machines']),operations=len(ops),goldenVectors=len(load('examples/hash-vectors.json')),protectedFiles=len(load('protected-files.json')['files']))

if __name__=='__main__':
    print('PASS '+json.dumps(check_all(),sort_keys=True))
