#!/usr/bin/env python3
"""Generate synthetic Stop contract trace; never production media evidence."""
import copy,json,base64,sys
from cryptography.hazmat.primitives.serialization import Encoding,PublicFormat
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests import test_receiver_contracts as fixtures
rx=fixtures.rx
rows=[]
for scenario in ('A_LOCAL_STOP_BEFORE_BACKEND','B_STOP_DURING_MEDIA_QUERY','C_STOP_DURING_LAST_CONSUME_QUERY'):
    x=fixtures.ReceiverContractTests();x.setUp()
    initial=dict(registered=False,generationId=x.j.generation_id,guardianIncarnation=x.j.guardian_incarnation)
    q,_=x.ready();operations=[]
    def local_stop():
        request=rx.wire(x.c,runId=x.j.command['runId']);out=x.g.stop(x.p.control,request)
        operations.append(dict(operationId='ReceiverStop',request=request,response=out))
    if scenario.startswith('A'):
        local_stop()
        request=q;op='ReceiverConsume';action=lambda:x.consume(q)
    elif scenario.startswith('B'):
        ack=x.consume(q);x.r.accept_ack(q,ack);execution=ack['consumption']['binding']['executionId']
        request=x.r.execution_request(execution,q['references']['permitId'],True);op='ReceiverMedia'
        original=x.b.snapshot
        def stopped(peer,request):
            out=original(peer,request);local_stop();x.b.stop(x.p.control);return out
        x.b.snapshot=stopped
        action=lambda:x.g.media(x.r.peer,request)
    else:
        original=x.b.snapshot;calls=[]
        def stopped(peer,request):
            out=original(peer,request);calls.append(True)
            if len(calls)==3:local_stop();x.b.stop(x.p.control)
            return out
        x.b.snapshot=stopped
        request=q;op='ReceiverConsume';action=lambda:x.consume(q)
    starts,media=x.r.tts_starts,x.g.media_count
    try:action();raise AssertionError('Stop not enforced')
    except rx.Denied as e:
        err=dict(requestId=request['requestId'],code=str(e))
        x.c.validate('ReceiverErrorResponse',err)
        operations.append(dict(operationId=op,request=request,error=err))
    rows.append(dict(scenario=scenario,initialAuthority=initial,bootstrapMessages=copy.deepcopy(x.p.transcript),
        physicalInstallation=copy.deepcopy(x.p.supervisor.installations[x.b.registration['binding']['physicalInstallProofRef']]),
        trustedPublicKeys={x.g.key_id:base64.b64encode(x.g.key.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)).decode()},
        operations=operations,linearized=list(x.g.linearized),outcome=dict(barrierState=x.g.barrier_state,
            backendRegistrationState=x.b.registration['state'],latchCount=len(x.b.latches),
            localAuditStates=[r['state'] for r in x.g.local_audit.values()],ttsBefore=starts,ttsAfter=x.r.tts_starts,
            acceptedMediaBefore=media,acceptedMediaAfter=x.g.media_count)))
trace=dict(contractRevision='durable-live-2',receiverRevision='receiver-1',scenarios=rows,
           note='Typed synthetic errors and local commit ordering from actual registered actor fixtures; not physical IPC/SQL/media acceptance.')
(Path(__file__).resolve().parents[1]/'contracts/v0.5/durable-live-2/examples/receiver-stop-trace.json').write_text(json.dumps(trace,indent=2)+'\n')
print('Stop trace scenarios',len(rows))
