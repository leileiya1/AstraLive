"""Dedicated test peer. FD3 deployment bootstrap, never production enrollment.
Physical closed-output adapter and CONTROL Peer here are explicit fixtures.
The official codec, process auth, real SQL transport, and PR11 receiver are real.
No TTS/media methods are invoked.
"""
import asyncio,base64,json,os,sys,socket
from pathlib import Path
from runtime.app.receiver1.transport import AuthorityTransport, InstallationReader, Credential, ProcessIdentity, identity, TransportFailure
from runtime.app.receiver1.wire import GuardianWire
from astralive_contracts import durable_live_v2 as dto

from runtime.app.receiver1.deployment import load_inherited
# Role is a trusted launcher argument, never request JSON. The Backend still
# authenticates its independently provisioned native process pin.
deployment=load_inherited(sys.argv[1])
wire=GuardianWire()
class ClosedOutputsFixture:
    async def close(self): return True
    async def observe(self,*_): raise RuntimeError('OUTPUT_FENCE_UNPROVEN')

async def main():
    receiver=None;ipc=None
    while line:=await asyncio.to_thread(sys.stdin.readline):
        q=json.loads(line)
        try:
            if q['action']=='configure':
                backend=ProcessIdentity(q['backend']['PID'],q['backend']['UID'],q['backend']['Birth'])
                credential=Credential(deployment.credential._raw)
                if backend!=deployment.parent:raise TransportFailure('UNAUTHENTICATED')
                _,transport,reader=deployment.guardian_ports(q['socket'])
                import output_guardian
                output_guardian.__path__.append(str(Path(q['guardianSource'])/'output_guardian'))
                from output_guardian.v2.receiver import Receiver
                from output_guardian.v2.ipc import Peer, ProcessPin, PrivateIPC
                from output_guardian.v2.journal import DenyJournal
                from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
                b=q['binding'];scope=tuple(b[k] for k in ('tenantId','ownerId','roomId'))
                receiver=Receiver(wire,transport,reader,ClosedOutputsFixture(),DenyJournal(q['journal']),guardian_principal=deployment.principal_id,guardian_incarnation=deployment.incarnation,signing_key=deployment.signing_key,key_id=deployment.key_id,scope=scope,required_sinks={'sink'})
                import psutil
                pin=deployment.control_pin(ProcessPin)
                pins=[pin]
                # This test-only private parent pipe supplies the same trusted
                # deployment metadata that a locked host launcher must install.
                # It is not a public/Runtime enrollment request.
                for cp in q.get('producers',[]):
                    actual=identity(cp['identity']['PID'])
                    if actual!=ProcessIdentity(cp['identity']['PID'],cp['identity']['UID'],cp['identity']['Birth']) or tuple(cp['scope'])!=scope or cp['role']!='REGISTERED_RUNTIME':raise TransportFailure('UNAUTHENTICATED')
                    pins.append(ProcessPin(cp['principalId'],cp['role'],cp['incarnation'],scope,actual.pid,actual.uid,psutil.Process(actual.pid).create_time(),bytes.fromhex(cp['credentialHash'])))
                ipc=PrivateIPC(receiver,q['guardianIPC'],pins);await ipc.start()
                control=Peer(q['registrar']['ID'],'CONTROL_REGISTRAR',q['registrar']['Incarnation'],scope,'control_fixture_channel')
                runtime=Peer(b['runtimePrincipalId'],'REGISTERED_RUNTIME',b['runtimeIncarnation'],scope,q['runtimeChannel'])
                result={'configured':True,'ownProcess':os.getpid()}
            elif q['action']=='identity':result={'pid':os.getpid(),'identity':identity(os.getpid()).__dict__}
            elif q['action']=='environment':
                result={'sqlOrProviderCredentialsPresent':any(any(word in k.upper() for word in ('DATABASE','POSTGRES','PGPASS','SECRET','TOKEN','RTMP','API_KEY')) for k in os.environ)}
            elif q['action']=='runtime_consume_ipc':
                op=dto.OPERATIONS['ReceiverConsume']
                obj=dto.decode(op.request_schema,dto.canonical_json(q['document']))
                body=dto.encode_request(op.id,obj,role='REGISTERED_RUNTIME',target=op.target,method=op.method,route_template=op.path)
                sock=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);sock.settimeout(0.5);sock.connect(q['socket'])
                # Native Guardian identity comes from the trusted root fixture;
                # credential is the Runtime's own FD3 capability, never Guardian's.
                expected=ProcessIdentity(q['guardian']['PID'],q['guardian']['UID'],q['guardian']['Birth'])
                probe=AuthorityTransport(q['socket'],expected,Credential(deployment.credential._raw))
                probe._peer(sock)
                sock.sendall(b'POST '+op.path.encode()+b' HTTP/1.1\r\nHost: private\r\nAuthorization: Bearer '+deployment.credential._raw+b'\r\nContent-Type: application/json\r\nContent-Length: '+str(len(body)).encode()+b'\r\n\r\n'+body)
                stream=sock.makefile('rb');status=int(stream.readline().split()[1]);headers={}
                while (line:=stream.readline())!=b'\r\n':
                    k,v=line.split(b':',1);headers[k.lower()]=v.strip()
                raw=stream.read(int(headers[b'content-length']))
                out=dto.decode_response(op.id,raw,status=status)
                # Keep the authenticated channel alive; no TTS/media is started.
                held=(sock,stream)
                result=wire.decode(op.response_schema if status==200 else op.error_schema,raw)
            elif q['action']=='runtime_client_flow':
                # Production Runtime client (runtime_client.py), not a raw
                # request. TTS is a counting stand-in; the START anchor is
                # moved back by the root's measured elapsed time (never later).
                import time
                from runtime.app.receiver1.runtime_client import GuardianChannel,ReceiverRuntime,ReceiverRefused,ReceiverUnknown
                from runtime.app.receiver1.transport import continuous
                guardian=ProcessIdentity(q['guardian']['PID'],q['guardian']['UID'],q['guardian']['Birth'])
                own=Credential(deployment.credential._raw)
                rt=ReceiverRuntime(lambda:GuardianChannel(q['socket'],guardian,own),wire,sequence_origin=q['sequenceOrigin'])
                back=q['startElapsedMs']/1000
                rt.remember_start(q['grant'],q['start'],(time.monotonic()-back,continuous()-back))
                spoken=[]
                async def synthesize(text):spoken.append(len(text));return [bytes(640)]
                outcome={}
                try:
                    execution=await rt.consume(q['registration'],q['references'],q['artifact'])
                    outcome['executionId']=execution.lineage.execution_id
                    outcome['channelBinding']=execution.consumption['channelBinding']
                    await rt.speak_once(execution,q['artifact'],synthesize)
                    lineage=rt.submit(execution)
                    outcome['mediaAccepted']=(await rt.media(lineage,q['references']['permitId'],'audio',bytes(640)))['accepted']
                    try:
                        await rt.speak_once(execution,q['artifact'],synthesize)
                    except ReceiverRefused as e:outcome['secondTTS']=e.code
                    try:
                        await rt.finish(lineage);outcome['finish']='DRAINED'
                    except (ReceiverRefused,ReceiverUnknown) as e:outcome['finish']=e.code
                except (ReceiverRefused,ReceiverUnknown) as e:outcome['consumeError']=e.code
                outcome.update(ttsInvocations=rt.tts_invocations,spoken=len(spoken),ticketsLeft=len(rt._tickets),nextSequence=rt.next_sequence,knowledge=rt.knowledge.get(q['references']['grantId']))
                await rt.close()
                result=outcome
            elif q['action']=='runtime_journal_flow':
                # Runtime-owned v2 flow (option 1): this process calls the real
                # Backend Journal with its own RUNTIME_JOURNAL credential, gets
                # the one-time ticket itself, then consumes at Guardian.
                import copy
                from runtime.app.receiver1.journal_client import JournalClient,JournalRefused,JournalUnknown
                from runtime.app.receiver1.runtime_client import GuardianChannel,ReceiverRuntime,ReceiverRefused,ReceiverUnknown
                backend_id=ProcessIdentity(q['backend']['PID'],q['backend']['UID'],q['backend']['Birth'])
                journal=JournalClient(q['journalSocket'],backend_id,Credential(q['journalCredential'].encode()))
                guardian=ProcessIdentity(q['guardian']['PID'],q['guardian']['UID'],q['guardian']['Birth'])
                own=Credential(deployment.credential._raw)
                rt=ReceiverRuntime(lambda:GuardianChannel(q['socket'],guardian,own),wire,sequence_origin=0)
                spoken=[]
                async def synthesize(text):spoken.append(len(text));return [bytes(640)]
                outcome={}
                try:
                    await journal.call('JournalPrepareAnswer',q['prepare'])
                    permit,_=await journal.call('AcquireOutputPermit',q['permit'])
                    start_q=copy.deepcopy(q['start']);start_q['permitId']=permit['permitId']
                    start,sent=await journal.call('JournalStart',start_q)
                    outcome['ticketReturned']=start.get('consumeTicket') is not None
                    grant=start['answerGrant']
                    rt.remember_start(grant,start,sent)
                    refs={'bootstrapId':q['bootstrapId'],'artifactId':q['artifact']['artifactId'],'artifactHash':q['artifact']['artifactHash'],'grantId':grant['grantId'],'permitId':permit['permitId']}
                    execution=await rt.consume(q['registration'],refs,q['artifact'])
                    outcome['executionId']=execution.lineage.execution_id
                    await rt.speak_once(execution,q['artifact'],synthesize)
                    outcome['mediaAccepted']=(await rt.media(rt.submit(execution),permit['permitId'],'audio',bytes(640)))['accepted']
                    try:
                        again=copy.deepcopy(start_q);again['requestId']=q['retryRequestId']
                        dup,_=await journal.call('JournalStart',again)
                        outcome['duplicateStartTicket']=dup.get('consumeTicket') is not None
                    except (JournalRefused,JournalUnknown) as e:outcome['duplicateStart']=e.code
                except (JournalRefused,JournalUnknown,ReceiverRefused,ReceiverUnknown) as e:outcome['error']=type(e).__name__+':'+e.code
                outcome.update(ttsInvocations=rt.tts_invocations,ticketsLeft=len(rt._tickets))
                await rt.close()
                result=outcome
            elif q['action']=='raw':
                body=base64.b64decode(q['body'])
                with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as sock:
                    sock.settimeout(0.5);sock.connect(transport.path);transport._peer(sock)
                    sock.sendall(b'POST '+q['path'].encode()+b' HTTP/1.1\r\nHost: private\r\nAuthorization: Bearer '+credential._raw+b'\r\nContent-Type: application/json\r\nContent-Length: '+str(len(body)).encode()+b'\r\n\r\n'+body)
                    header=b''
                    while not header.endswith(b'\r\n'):header+=sock.recv(1)
                result={'status':int(header.split(b' ')[1])}
            elif q['action']=='call':
                if q['operation'] not in ('QueryReceiverAuthority','CommitReceiverConsume','QueryReceiverConsumption','ReadReceiverPhysicalInstallation'):raise TransportFailure('FORBIDDEN')
                result=await asyncio.to_thread(transport._call,q['operation'],q['document'])
            elif q['action']=='wrong_process':
                # A genuinely different PID inherits the actual credential,
                # not a fabricated token; kernel peer pins must still deny it.
                r,w=os.pipe();pid=os.fork()
                if pid==0:
                    os.close(r)
                    try:
                        transport._call(q['operation'],q['document']);code='UNEXPECTED_AUTHORIZATION'
                    except TransportFailure as e:code=str(e)
                    os.write(w,code.encode());os.close(w);os._exit(0)
                os.close(w);code=os.read(r,256).decode();os.close(r);os.waitpid(pid,0)
                result={'code':code}
            elif q['action']=='drop_commit_reply':
                op=dto.OPERATIONS['CommitReceiverConsume'];body=dto.canonical_json(q['document'])
                # Send the real Commit, then deliberately lose the reply. Root
                # checks durable SQL before any later metadata/duplicate read.
                with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as sock:
                    sock.connect(transport.path);transport._peer(sock)
                    sock.sendall(b'POST '+op.path.encode()+b' HTTP/1.1\r\nHost: private\r\nAuthorization: Bearer '+credential._raw+b'\r\nContent-Type: application/json\r\nContent-Length: '+str(len(body)).encode()+b'\r\n\r\n'+body)
                    await asyncio.sleep(0.05)
                result={'responseDiscarded':True}
            elif q['action']=='mixed_authority':
                calls=[('QueryReceiverAuthority',q['query']),('CommitReceiverConsume',q['consume'])]*2
                replies=await asyncio.gather(*(asyncio.to_thread(transport._call,op,doc) for op,doc in calls),return_exceptions=True)
                result={'positiveResponses':sum(isinstance(v,dict) for v in replies),'true':sum(isinstance(v,dict) and v.get('consumeAuthorized') is True for v in replies),'errors':sum(isinstance(v,BaseException) for v in replies)}
            elif q['action']=='concurrent':
                replies=await asyncio.gather(*(asyncio.to_thread(transport._call,'CommitReceiverConsume',q['document']) for _ in range(4)),return_exceptions=True)
                result={'true':sum(isinstance(v,dict) and v.get('consumeAuthorized') is True for v in replies),'false':sum(isinstance(v,dict) and v.get('consumeAuthorized') is False for v in replies),'errors':sum(isinstance(v,BaseException) for v in replies)}
            elif q['action']=='stage':result=await receiver.stage(control,q['document'])
            elif q['action']=='consume':
                request=wire.decode('ReceiverConsumeRequest',dto.canonical_json(q['document']))
                result=await receiver.consume(runtime,request)
            elif q['action']=='stop':result=await receiver.stop(control,q['document'])
            elif q['action']=='metadata':result={'state':receiver.gate.state,'acks':len(receiver.gate.acks),'active':receiver.gate.active is not None}
            else:raise TransportFailure('INVALID_ARGUMENT')
            print(dto.canonical_json({'ok':True,'result':result}).decode(),flush=True)
        except Exception as e:
            code=str(e)
            # Never print arbitrary exception messages or original payloads.
            codes={'FORBIDDEN','UNAUTHENTICATED','DEPENDENCY_UNAVAILABLE','INVALID_ARGUMENT','OUTPUT_FENCE_UNPROVEN','CONSUMPTION_UNKNOWN','CONSUMPTION_CONFLICT','RUN_STOPPED','BOOTSTRAP_REQUIRED','REGISTRATION_REVOKED','STALE_RUN_EPOCH','STATE_CONFLICT','GRANT_EXPIRED','FACT_EXPIRED','BINDING_EXPIRED','RECOVERY_UNKNOWN','GENERATION_MISMATCH','GUARDIAN_INCARNATION_MISMATCH','LEASE_LOST'}
            print(json.dumps({'ok':False,'code':code if code in codes else type(e).__name__,'diagnosticType':getattr(e,'cause_type',''),'osErrno':getattr(e,'os_errno',None)}),flush=True)
    if receiver is not None:
        if ipc is not None: await ipc.close()
        receiver.journal.close()
asyncio.run(main())
