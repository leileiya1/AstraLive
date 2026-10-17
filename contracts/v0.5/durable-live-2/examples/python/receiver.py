"""Separate-participant CONTRACT MOCK. No sockets, SQL writes, TTS or GPU.

Supervisor/Registrar are trusted deployment/control fixtures. Backend is the
sole durable-authority/latch mock. Guardian has only scoped authority read/consume and historical-metadata RPCs.
Runtime has no reference to Backend storage or control credentials.
"""
import base64
import copy
from collections import namedtuple
import threading
import uuid
import hmac
from datetime import datetime, timezone
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

Peer=namedtuple('Peer','principalId role incarnation channelBinding')

def ident(prefix):return prefix+'_'+uuid.uuid4().hex

def wire(c,**body):return dict(contractRevision='durable-live-2',receiverRevision='receiver-1',requestId=ident('req'),**body)

def stamp(j):return datetime.fromtimestamp(j.now,timezone.utc).isoformat(timespec='milliseconds').replace('+00:00','Z')

class Denied(ValueError):pass

def require(ok,code):
    if not ok:raise Denied(code)

class Deadline:
    """Two local clocks anchored BEFORE RPC; no remote wall-clock subtraction."""
    def __init__(self,timing,sent_mono,sent_suspend,grant=True):
        remaining=min(timing['remainingGrantMs'],timing['remainingProofMs']) if grant else timing['remainingProofMs']
        duration=remaining/1000-.100
        self.mono=sent_mono+duration;self.suspended=sent_suspend+duration
    def check(self,clock,suspend,code='GRANT_EXPIRED'):require(clock()<self.mono and suspend()<self.suspended,code)
    def remaining(self,clock,suspend):return max(0,round(min(self.mono-clock(),self.suspended-suspend())*1000))

class Supervisor:
    """Trusted OS/process-control registry; producer JSON cannot mutate this."""
    def __init__(self,c):
        self.c=c;self.principals={};self.installations={};self.keys={};self.key_owners={};self.next_generation=0;self.current_install={};self.binding_records={}
    def start_peer(self,role,producer=None):
        peer=Peer(ident('principal'),role,ident('process'),self.c.digest(ident('channel')))
        self.principals[peer.principalId]=dict(peer=peer,producer=producer,active=True)
        return peer
    def check(self,peer,role=None):
        row=self.principals.get(peer.principalId)
        require(row is not None and row['active'] and row['peer'].incarnation==peer.incarnation and row['peer'].role==peer.role,'FORBIDDEN')
        require(role is None or peer.role==role,'FORBIDDEN')
        return row
    def retire(self,peer):self.principals[peer.principalId]['active']=False
    def install(self,control,command,runtime,guardian):
        self.check(control,'CONTROL_REGISTRAR');row=self.check(runtime,'REGISTERED_RUNTIME');self.check(guardian,'OUTPUT_GUARDIAN')
        require(row['producer']==command['producerIncarnation'],'FORBIDDEN')
        self.next_generation+=1
        proof=ident('physical_install')
        # Physical adapter is closed; allocation/installation belongs to CONTROL,
        # never to Runtime's question/Artifact/Consume JSON.
        record={k:command[k] for k in ('tenantId','ownerId','runId','runEpoch','sessionId','producerIncarnation','attemptId','commandId','turnId','utteranceId')}
        record.update(runtimeIncarnation=runtime.incarnation,observedByPrincipalId=control.principalId,closedFenceProofRef=ident('closed_fence'),runtimePrincipalId=runtime.principalId,guardianPrincipalId=guardian.principalId,guardianIncarnation=guardian.incarnation,generationId=self.next_generation)
        self.installations[proof]=record;self.current_install[command['sessionId']]=proof
        return proof,copy.deepcopy(record)
    def verify_install(self,binding):
        row=self.installations.get(binding['physicalInstallProofRef'])
        require(row is not None,'BOOTSTRAP_REQUIRED')
        require(self.current_install.get(binding['sessionId'])==binding['physicalInstallProofRef'],'REGISTRATION_REVOKED')
        for key in ('tenantId','ownerId','runId','runEpoch','sessionId','producerIncarnation','attemptId','commandId','turnId','utteranceId','runtimePrincipalId','runtimeIncarnation','guardianIncarnation','generationId'):
            require(row[key]==binding[key],'GENERATION_MISMATCH' if key=='generationId' else 'FORBIDDEN')
        self.check(self.principals[row['runtimePrincipalId']]['peer'],'REGISTERED_RUNTIME')
        guardian=self.principals[row['guardianPrincipalId']]['peer'];self.check(guardian,'OUTPUT_GUARDIAN')
        return guardian

    def seal_binding(self,control,binding):
        self.check(control,'CONTROL_REGISTRAR');self.verify_install(binding)
        self.binding_records[binding['physicalInstallProofRef']]=copy.deepcopy(binding)
    def read_installation(self,peer,q):
        self.c.validate('ReadReceiverPhysicalInstallationRequest',q)
        self.check(peer);require(peer.role in ('CONTROL_REGISTRAR','OUTPUT_GUARDIAN'),'FORBIDDEN')
        b=self.binding_records.get(q['physicalInstallProofRef']);require(b is not None,'BOOTSTRAP_REQUIRED')
        guardian=self.verify_install(b)
        if peer.role=='OUTPUT_GUARDIAN':require(peer.principalId==guardian.principalId,'FORBIDDEN')
        require(self.c.digest(b)==q['expectedBindingHash'],'ANSWER_CONFLICT')
        row=self.installations[q['physicalInstallProofRef']]
        return dict(requestId=q['requestId'],installation=dict(binding=copy.deepcopy(b),installationRevision=1,
                    observedByPrincipalId=row['observedByPrincipalId'],guardianPrincipalId=guardian.principalId,
                    closedFenceProofRef=row['closedFenceProofRef'],state='CLOSED_INSTALLED'))

class BackendAuthority:
    def __init__(self,journal,c,supervisor):
        self.j=journal;self.c=c;self.supervisor=supervisor;self.lock=journal._lock
        self.registration=None;self.children={};self.latches={};self.consume_keys={};self.run_revision=1;self.stage_challenges={}
        self.events=[]
        self.context=dict(journal.command,producerIncarnation=journal.producer)
        self.room_id=next(x['value']['roomId'] for x in c.common.load('examples/objects.json') if x['name']=='BroadcastRun')
    def validate(self,operation,body):self.c.validate(operation+'Request',body)
    def guard(self,peer,role,binding=None):
        self.supervisor.check(peer,role)
        require(self.registration is not None,'BOOTSTRAP_REQUIRED')
        r=self.registration;b=r['binding'];require(r['state']=='ACTIVE','REGISTRATION_REVOKED')
        self.j.guard(self.context)
        self.supervisor.verify_install(b)
        if role=='OUTPUT_GUARDIAN':
            guardian=self.supervisor.verify_install(b)
            require(peer.principalId==guardian.principalId and peer.incarnation==b['guardianIncarnation'],'GUARDIAN_INCARNATION_MISMATCH')
        if role=='REGISTERED_RUNTIME':require(peer.principalId==b['runtimePrincipalId'],'FORBIDDEN')
        require(self.j.generation_id==b['generationId'],'GENERATION_MISMATCH')
        require(self.j.guardian_incarnation==b['guardianIncarnation'],'GUARDIAN_INCARNATION_MISMATCH')
        return b
    def challenge(self,control,binding):
        self.supervisor.check(control,'CONTROL_REGISTRAR')
        self.supervisor.read_installation(control,wire(self.c,physicalInstallProofRef=binding['physicalInstallProofRef'],expectedBindingHash=self.c.digest(binding)))
        with self.lock:
            require(not self.j.stopped,'RUN_STOPPED');require(binding['runEpoch']==self.j.epoch,'STALE_RUN_EPOCH')
            nonce=ident('challenge');value=dict(bindingHash=self.c.digest(binding),issuedAt=stamp(self.j),expiresAt=datetime.fromtimestamp(self.j.now+1,timezone.utc).isoformat().replace('+00:00','Z'))
            self.stage_challenges[nonce]=value
            return dict(challenge=nonce,challengeIssuedAt=value['issuedAt'],challengeExpiresAt=value['expiresAt'])
    def register(self,control,q):
        self.validate('RegisterReceiverBootstrap',q)
        observed=self.supervisor.read_installation(control,wire(self.c,physicalInstallProofRef=q['binding']['physicalInstallProofRef'],expectedBindingHash=self.c.digest(q['binding'])))['installation']
        with self.lock:
            self.supervisor.check(control,'CONTROL_REGISTRAR');b=q['binding'];receipt=q['receipt']
            require(not self.j.stopped,'RUN_STOPPED');require(b['runEpoch']==self.j.epoch,'STALE_RUN_EPOCH')
            require(q['expectedRunRevision']==self.run_revision,'STATE_CONFLICT')
            require(q['expectedRegistrationRevision']==0,'STATE_CONFLICT')
            require(self.j.lease_until>self.j.now,'LEASE_LOST');require(self.j.binding_until>self.j.now,'BINDING_EXPIRED')
            guardian=self.supervisor.verify_install(b)
            for key in ('tenantId','ownerId','runId','sessionId','producerIncarnation','attemptId','commandId','turnId','utteranceId'):
                require(b[key]==self.context[key],'FORBIDDEN')
            require(b['roomId']==self.room_id and b['outputBindingVersion']==1 and q['expectedLeaseVersion']==self.context['leaseVersion'],'STATE_CONFLICT')
            require(receipt['guardianPrincipalId']==guardian.principalId and receipt['guardianIncarnation']==guardian.incarnation,'GUARDIAN_INCARNATION_MISMATCH')
            require(receipt['bindingHash']==self.c.digest(b),'ANSWER_CONFLICT')
            require(receipt['installationRevision']==observed['installationRevision'],'STATE_CONFLICT')
            challenge=self.stage_challenges.get(receipt['challenge']);require(challenge is not None and challenge==dict(bindingHash=receipt['bindingHash'],issuedAt=receipt['authorityIssuedAt'],expiresAt=receipt['validUntil']),'FORBIDDEN')
            require(self.supervisor.key_owners.get(receipt['keyId'])==guardian.principalId,'FORBIDDEN')
            unsigned={k:v for k,v in receipt.items() if k!='signature'}
            try:self.supervisor.keys[receipt['keyId']].verify(base64.b64decode(receipt['signature']),self.c.canonical(unsigned))
            except Exception:raise Denied('FORBIDDEN') from None
            require(self._time(receipt['authorityIssuedAt'])<=self.j.now<self._time(receipt['validUntil']) and self._time(receipt['validUntil'])-self._time(receipt['authorityIssuedAt'])<=1,'BINDING_EXPIRED')
            if self.registration is not None:
                require(self.registration['registrationHash']==self.c.digest(b) and self.registration['stageReceiptId']==receipt['stageReceiptId'] and self.registration['state']=='ACTIVE','STATE_CONFLICT')
                return dict(requestId=q['requestId'],registration=copy.deepcopy(self.registration))
            self.registration=dict(binding=copy.deepcopy(b),registrationHash=self.c.digest(b),revision=1,state='ACTIVE',registeredAt=stamp(self.j),stageReceiptId=receipt['stageReceiptId'])
            self.j.registration_record=copy.deepcopy(self.registration)
            self.j.registration_id=b['bootstrapId'];self.j.generation_id=b['generationId'];self.j.guardian_incarnation=b['guardianIncarnation']
            return dict(requestId=q['requestId'],registration=copy.deepcopy(self.registration))
    @staticmethod
    def _time(value):
        from datetime import datetime
        return datetime.fromisoformat(value.replace('Z','+00:00')).timestamp()
    def prepare(self,peer,q):
        with self.lock:
            b=self.guard(peer,'REGISTERED_RUNTIME');receipt=self.j.prepare(q);a=q['artifact']
            child=dict(bootstrapId=b['bootstrapId'],answerId=a['answerId'],artifactId=a['artifactId'],artifactHash=a['artifactHash'],bindingHash=self.c.digest(b),sequence=a['sequence'],createdAt=stamp(self.j))
            saved=self.children.setdefault(a['artifactId'],child)
            require(saved['artifactHash']==a['artifactHash'],'ANSWER_CONFLICT')
            return receipt
    def acquire(self,peer,artifact_id,refresh=False):
        with self.lock:
            self.guard(peer,'REGISTERED_RUNTIME');require(artifact_id in self.children,'BOOTSTRAP_REQUIRED')
            if refresh:self.j.refresh_facts(artifact_id)
            return self.j.renew_permit(artifact_id)
    def grant(self,peer,q,continuation=False):
        with self.lock:
            self.guard(peer,'REGISTERED_RUNTIME')
            artifact=q['artifactId'] if continuation else q['answerArtifactId'];require(artifact in self.children,'BOOTSTRAP_REQUIRED')
            return self.j.start_segment(q) if continuation else self.j.start(q)
    def snapshot(self,guardian,q):
        self.validate('QueryReceiverAuthority',q)
        with self.lock:
            b=self.guard(guardian,'OUTPUT_GUARDIAN');refs=q['references'];a=self.j._unit(refs['artifactId'])['artifact']
            require(refs['bootstrapId']==b['bootstrapId'],'BOOTSTRAP_REQUIRED')
            require(a['artifactHash']==refs['artifactHash'],'ANSWER_CONFLICT')
            grant=self.j.grants.get(a['artifactId']);require(grant is not None and grant['grantId']==refs['grantId'],'ANSWER_CONFLICT')
            child=self.children.get(a['artifactId']);require(child is not None,'BOOTSTRAP_REQUIRED')
            permit=self.j._check_permit(a,refs['permitId']);self.j.fresh(a)
            obs=self.j.observations[permit['factObservationId']]
            require(permit['generationId']==b['generationId'] and permit['guardianIncarnation']==b['guardianIncarnation'],'GENERATION_MISMATCH')
            snapshot=dict(registration=copy.deepcopy(self.registration),artifactRegistration=copy.deepcopy(child),artifact=copy.deepcopy(a),grant=copy.deepcopy(grant),grantState=self.j.grant_states[grant['grantId']],permit=copy.deepcopy(permit),observation=copy.deepcopy(obs),consumption=self.summary(grant['grantId']),authorityTime=stamp(self.j),validUntil=permit['expiresAt'],timing=self.j.consume_timing(grant,permit))
            return dict(requestId=q['requestId'],snapshot=snapshot)
    def summary(self,grant_id):
        latch=self.latches.get(grant_id)
        if not latch:return dict(state='UNCONSUMED',receiptId=None)
        artifact=latch['binding']['artifactId'];state=self.j.execution_states.get(artifact,'UNKNOWN')
        return dict(state='CONSUMED' if state=='ACTIVE' else state,receiptId=latch['receiptId'])
    def commit(self,guardian,q):
        self.validate('CommitReceiverConsume',q)
        with self.lock:
            snap=self.snapshot(guardian,wire(self.c,references=q['references']))['snapshot']
            require(q['expectedRegistrationRevision']==self.registration['revision'],'STATE_CONFLICT')
            require(q['runtimePrincipalId']==snap['registration']['binding']['runtimePrincipalId'],'FORBIDDEN')
            require(q['runtimeIncarnation']==snap['registration']['binding']['runtimeIncarnation']==self.supervisor.principals[q['runtimePrincipalId']]['peer'].incarnation,'FORBIDDEN')
            # An authenticated Guardian attests the real IPC peer/channel; Runtime
            # is not permitted to call this RPC or choose either trusted value.
            grant=snap['grant']
            ticket_hash=self.j.ticket_hash(grant,q['consumeTicket'])
            require(hmac.compare_digest(ticket_hash,self.j.ticket_verifiers[grant['grantId']]),'GRANT_TICKET_INVALID')
            key=(q['runtimePrincipalId'],q['consumeRequestId'])
            identity=self.c.digest(dict(domain='receiver-consume-identity-1',guardianPrincipalId=guardian.principalId,request={k:v for k,v in q.items() if k not in ('requestId','consumeTicket')},ticketVerifier=ticket_hash))
            require(key not in self.consume_keys or self.consume_keys[key]==identity,'CONSUMPTION_CONFLICT')
            if grant['grantId'] in self.latches:
                require(self.latches[grant['grantId']]['consumeIdentityHash']==identity,'CONSUMPTION_CONFLICT')
                return dict(requestId=q['requestId'],consumeAuthorized=False,consumption=None,consumeTiming=None,summary=self.summary(grant['grantId']))
            for record in self.latches.values():
                require(self.j.execution_states.get(record['binding']['artifactId'])!='ACTIVE','ACTIVE_UNIT_CONFLICT')
            artifact=snap['artifact']
            if artifact['sequence']>1:
                previous=self.j.units[artifact['sequence']-2]
                require(previous['state']=='DRAINED' and previous['artifact']['artifactId'] in self.j.drains,'ANSWER_GAP')
            require(min(snap['timing']['remainingGrantMs'],snap['timing']['remainingProofMs'])>100,'GRANT_EXPIRED')
            binding=self.j._consume(grant['artifactId'],grant)
            self.consume_keys[key]=identity
            record=dict(runtimeIncarnation=q['runtimeIncarnation'],consumeIdentityHash=identity,receiptId=ident('consume_receipt'),bootstrapId=q['references']['bootstrapId'],consumeRequestId=q['consumeRequestId'],runtimePrincipalId=q['runtimePrincipalId'],guardianPrincipalId=guardian.principalId,channelBinding=q['channelBinding'],registrationHash=self.registration['registrationHash'],registrationRevision=self.registration['revision'],binding=binding)
            self.latches[grant['grantId']]=copy.deepcopy(record)
            return dict(requestId=q['requestId'],consumeAuthorized=True,consumption=copy.deepcopy(record),consumeTiming=self.j.consume_timing(grant,snap['permit']),summary=self.summary(grant['grantId']))
    def consumption_summary(self,guardian,q):
        self.validate('QueryReceiverConsumption',q);self.supervisor.check(guardian,'OUTPUT_GUARDIAN')
        with self.lock:
            require(self.registration is not None and q['bootstrapId']==self.registration['binding']['bootstrapId'],'BOOTSTRAP_REQUIRED')
            summary=self.summary(q['grantId'])
            if summary['state'] not in ('DRAINED','FENCED'):
                b=self.registration['binding']
                if guardian.incarnation!=b['guardianIncarnation'] or self.registration['state']!='ACTIVE':summary=dict(summary,state='UNKNOWN')
            return dict(requestId=q['requestId'],summary=summary)
    def stop(self,control):
        self.supervisor.check(control,'CONTROL_REGISTRAR')
        with self.lock:
            self.j.stopped=True;self.run_revision+=1
            if self.registration:self.registration.update(state='REVOKED',revision=self.registration['revision']+1)
    def revoke(self,control,q):
        self.validate('RevokeReceiverBootstrap',q);self.supervisor.check(control,'CONTROL_REGISTRAR')
        with self.lock:
            require(self.registration and q['bootstrapId']==self.registration['binding']['bootstrapId'],'BOOTSTRAP_REQUIRED')
            require(q['expectedRegistrationRevision']==self.registration['revision'],'STATE_CONFLICT')
            self.registration.update(state='REVOKED',revision=self.registration['revision']+1);self.j.runtime_restart()
            return dict(requestId=q['requestId'],registration=copy.deepcopy(self.registration))

class GuardianReceiver:
    """Local lock serializes ONLY bounded state commits, never RPC/fsync/observer.

    Returning an ACK / incrementing media_count models nonblocking enqueue at
    that locked linearization point, not delivery over a real transport.
    """
    def __init__(self,authority,c,supervisor,clock):
        self.clock=clock;self.suspend_clock=clock;self.authority=authority;self.c=c;self.supervisor=supervisor;self.peer=supervisor.start_peer('OUTPUT_GUARDIAN')
        self.key=Ed25519PrivateKey.generate();self.key_id=ident('key');supervisor.keys[self.key_id]=self.key.public_key();supervisor.key_owners[self.key_id]=self.peer.principalId
        self.lock=threading.Lock();self.barrier=0;self.staged=None;self.local={};self.local_audit={};self.proof_refs={}
        self.observer_fixture=None;self.before_fsync=None;self.after_commit=None
        self.before_consume_ack=None;self.before_handoff=None;self.before_renew_commit=None;self.before_finish_commit=None
        self.media_count=0;self.unit_media={};self.active_execution_id=None;self.barrier_state='FENCED';self.stops=set();self.finished_units=set();self.last_media_sequence=-1
        self.linearized=[]

    def _event(self,kind,execution=None):
        # Called only under self.lock; a bounded mock of the handoff/audit edge.
        self.linearized.append(dict(kind=kind,barrierRevision=self.barrier,
                                    runId=self.staged['runId'] if self.staged else None,executionId=execution))

    def _admit(self,runtime,barrier=None):
        # A captured barrier is invalid after Stop, Finish, Stage or Restart.
        if barrier is not None:require(barrier==self.barrier,'CONSUMPTION_UNKNOWN')
        require(self.staged is not None,'BOOTSTRAP_REQUIRED')
        require(self.staged['runId'] not in self.stops,'RUN_STOPPED')
        require(self.barrier_state in ('STAGED_CLOSED','ACTIVE_UNIT'),'CONSUMPTION_UNKNOWN')
        self.supervisor.check(self.peer,'OUTPUT_GUARDIAN');self.supervisor.check(runtime,'REGISTERED_RUNTIME')
        b=self.staged
        require(runtime.principalId==b['runtimePrincipalId'] and runtime.incarnation==b['runtimeIncarnation'],'FORBIDDEN')
        require(self.peer.incarnation==b['guardianIncarnation'],'GUARDIAN_INCARNATION_MISMATCH')
        return b

    def _consume_admission(self,runtime,q,barrier=None):
        b=self._admit(runtime,barrier)
        require(q['references']['bootstrapId']==b['bootstrapId'],'BOOTSTRAP_REQUIRED')
        require(q['expectedGenerationId']==b['generationId'],'GENERATION_MISMATCH')
        require(q['expectedGuardianIncarnation']==b['guardianIncarnation'],'GUARDIAN_INCARNATION_MISMATCH')
        if self.barrier_state=='ACTIVE_UNIT':
            record=self.local.get(self.active_execution_id);require(record is not None,'CONSUMPTION_UNKNOWN')
            require(record['binding']['grantId']==q['references']['grantId'],'ACTIVE_UNIT_CONFLICT')
        return b

    def _execution_request(self,runtime,q,barrier=None):
        self._admit(runtime,barrier)
        record=self.local.get(q['executionId']);require(record is not None,'CONSUMPTION_UNKNOWN')
        require(q['executionId']==self.active_execution_id and q['executionId'] not in self.finished_units,'STALE_EXECUTION')
        require(self.barrier_state=='ACTIVE_UNIT','STALE_EXECUTION')
        require(q['artifactId']==record['binding']['artifactId'] and q['artifactHash']==record['binding']['artifactHash'],'ANSWER_CONFLICT')
        require(record['runtimePrincipalId']==runtime.principalId and record['runtimeIncarnation']==runtime.incarnation and record['channelBinding']==runtime.channelBinding,'FORBIDDEN')
        require(record['registrationHash']==self.c.digest(self.staged),'CONSUMPTION_UNKNOWN')
        return record

    def _check_snapshot(self,snap,refs,revision,record=None):
        # Authority transport supplies this document, never Runtime JSON. Pure
        # comparisons only: safe to repeat at each local final commit boundary.
        r=snap['registration'];b=r['binding']
        require(r['state']=='ACTIVE' and b==self.staged and r['registrationHash']==self.c.digest(b),'REGISTRATION_REVOKED')
        require(r['revision']==revision,'STATE_CONFLICT')
        require(refs['bootstrapId']==b['bootstrapId'],'BOOTSTRAP_REQUIRED')
        for key in ('artifactId','artifactHash'):
            require(snap['artifact'][key]==refs[key] and snap['artifactRegistration'][key]==refs[key],'ANSWER_CONFLICT')
        require(snap['artifactRegistration']['bindingHash']==r['registrationHash'],'ANSWER_CONFLICT')
        require(snap['grant']['grantId']==refs['grantId'] and snap['permit']['permitId']==refs['permitId'],'ANSWER_CONFLICT')
        for row in (snap['artifact'],snap['grant'],snap['permit'],snap['observation']):
            for key,value in b.items():
                if key in row:require(row[key]==value,'GENERATION_MISMATCH' if key=='generationId' else 'ANSWER_CONFLICT')
        if record is not None:
            require(snap['consumption']==dict(state='CONSUMED',receiptId=record['receiptId']),'CONSUMPTION_UNKNOWN')
            for key,value in record['binding'].items():
                for row in (snap['grant'],snap['permit'],snap['observation']):
                    if key in row:require(row[key]==value,'ANSWER_CONFLICT')

    def stage(self,control,q):
        self.c.validate('ReceiverStageRequest',q);self.supervisor.check(control,'CONTROL_REGISTRAR');b=q['binding']
        with self.lock:barrier=self.barrier;guardian=self.peer
        observed=self.supervisor.read_installation(guardian,wire(self.c,physicalInstallProofRef=b['physicalInstallProofRef'],expectedBindingHash=self.c.digest(b)))['installation']
        with self.lock:
            require(barrier==self.barrier and guardian==self.peer,'CONSUMPTION_UNKNOWN')
            require(observed['guardianPrincipalId']==self.peer.principalId,'GUARDIAN_INCARNATION_MISMATCH')
            require(b['runId'] not in self.stops,'RUN_STOPPED')
            require(not self.local and self.barrier_state in ('FENCED','STAGED_CLOSED'),'STATE_CONFLICT')
            if self.staged is not None:
                require(self.barrier_state=='STAGED_CLOSED' and self.staged==b,'STATE_CONFLICT')
            self.barrier+=1;self.barrier_state='STAGED_CLOSED'
            self.staged=copy.deepcopy(b);self.audit_runtime_principal=b['runtimePrincipalId']
            receipt=dict(contractRevision='durable-live-2',receiverRevision='receiver-1',installationRevision=observed['installationRevision'],stageReceiptId=ident('stage'),challenge=q['challenge'],guardianPrincipalId=self.peer.principalId,guardianIncarnation=self.peer.incarnation,keyId=self.key_id,bindingHash=self.c.digest(b),authorityIssuedAt=q['challengeIssuedAt'],validUntil=q['challengeExpiresAt'],state='CLOSED_STAGED')
            receipt['signature']=base64.b64encode(self.key.sign(self.c.canonical(receipt))).decode()
            return dict(requestId=q['requestId'],receipt=receipt)

    def consume(self,runtime,q):
        self.c.validate('ReceiverConsumeRequest',q)
        with self.lock:
            self._consume_admission(runtime,q);barrier=self.barrier;guardian=self.peer
        snap=self.authority.snapshot(guardian,wire(self.c,references=q['references']))['snapshot']
        with self.lock:
            self._consume_admission(runtime,q,barrier)
            self._check_snapshot(snap,q['references'],q['expectedRegistrationRevision'])
        sent_mono,sent_suspend=self.clock(),self.suspend_clock()
        out=self.authority.commit(guardian,wire(self.c,consumeTicket=q['consumeTicket'],references=q['references'],consumeRequestId=q['consumeRequestId'],runtimeIncarnation=runtime.incarnation,runtimePrincipalId=runtime.principalId,channelBinding=runtime.channelBinding,expectedRegistrationRevision=q['expectedRegistrationRevision']))
        if not out['consumeAuthorized']:
            with self.lock:
                self._consume_admission(runtime,q,barrier)
                return dict(out,requestId=q['requestId'])
        record=out['consumption'];execution=record['binding']['executionId'];grant=record['binding']['grantId']
        # Keep audit even if Stop won during Commit. This never arms execution,
        # deletes Backend's latch or stores the plaintext consumeTicket.
        with self.lock:
            self.local_audit[grant]=dict(consumption=copy.deepcopy(record),state='UNKNOWN',fsynced=False)
            self._consume_admission(runtime,q,barrier)
        deadline=Deadline(out['consumeTiming'],sent_mono,sent_suspend);deadline.check(self.clock,self.suspend_clock)
        if self.before_fsync:self.before_fsync()  # external/fsync phase: no local lock
        with self.lock:
            self.local_audit[grant]['fsynced']=True
            self._consume_admission(runtime,q,barrier)
        if self.after_commit:self.after_commit()
        with self.lock:self._consume_admission(runtime,q,barrier)
        sent=self.clock(),self.suspend_clock()
        final=self.authority.snapshot(guardian,wire(self.c,references=q['references']))['snapshot']
        proof=Deadline(final['timing'],*sent,grant=False)
        if self.before_consume_ack:self.before_consume_ack()
        with self.lock:
            self._consume_admission(runtime,q,barrier)
            self._check_snapshot(final,q['references'],q['expectedRegistrationRevision'],record)
            require(self.barrier_state=='STAGED_CLOSED' and self.active_execution_id is None,'ACTIVE_UNIT_CONFLICT')
            deadline.check(self.clock,self.suspend_clock);proof.check(self.clock,self.suspend_clock,'LEASE_LOST')
            self.local[execution]=copy.deepcopy(record);self.proof_refs[execution]=copy.deepcopy(q['references'])
            self.active_execution_id=execution;self.barrier_state='ACTIVE_UNIT';self.local_audit[grant]['state']='CONSUMED'
            remaining=min(deadline.remaining(self.clock,self.suspend_clock),proof.remaining(self.clock,self.suspend_clock))
            self._event('CONSUME_ACK',execution)
            return dict(out,requestId=q['requestId'],consumeTiming=dict(remainingGrantMs=remaining,remainingProofMs=remaining,safetyMarginMs=100))

    def _ongoing_proof(self,runtime,q):
        with self.lock:
            record=copy.deepcopy(self._execution_request(runtime,q));barrier=self.barrier;guardian=self.peer
        a=record['binding'];refs=dict(bootstrapId=record['bootstrapId'],artifactId=a['artifactId'],artifactHash=a['artifactHash'],grantId=a['grantId'],permitId=q['permitId'])
        sent=self.clock(),self.suspend_clock()
        snap=self.authority.snapshot(guardian,wire(self.c,references=refs))['snapshot']
        proof=Deadline(snap['timing'],*sent,grant=False)
        with self.lock:self._final_execution(runtime,q,barrier,record,refs,snap,proof)
        return barrier,record,refs,snap,proof

    def _final_execution(self,runtime,q,barrier,record,refs,snap,proof):
        require(self._execution_request(runtime,q,barrier)==record,'CONSUMPTION_UNKNOWN')
        self._check_snapshot(snap,refs,record['registrationRevision'],record)
        proof.check(self.clock,self.suspend_clock,'LEASE_LOST')

    def renewal(self,runtime,execution_id,permit_id):
        with self.lock:
            record=self.local.get(execution_id);require(record is not None,'CONSUMPTION_UNKNOWN')
            q=wire(self.c,executionId=execution_id,artifactId=record['binding']['artifactId'],artifactHash=record['binding']['artifactHash'],permitId=permit_id)
        return self.renew(runtime,q)

    def renew(self,runtime,q):
        self.c.validate('ReceiverRenewRequest',q)
        barrier,record,refs,snap,proof=self._ongoing_proof(runtime,q)
        if self.before_renew_commit:self.before_renew_commit()
        with self.lock:
            self._final_execution(runtime,q,barrier,record,refs,snap,proof)
            self.proof_refs[q['executionId']]=copy.deepcopy(refs);self._event('RENEW',q['executionId'])
            return dict(requestId=q['requestId'],state='PROOF_UPDATED',permit=snap['permit'],observation=snap['observation'],timing=dict(remainingGrantMs=0,remainingProofMs=proof.remaining(self.clock,self.suspend_clock),safetyMarginMs=100))

    def media(self,runtime,q):
        self.c.validate('ReceiverMediaRequest',q)
        barrier,record,refs,snap,proof=self._ongoing_proof(runtime,q)
        if self.before_handoff:self.before_handoff()
        with self.lock:
            self._final_execution(runtime,q,barrier,record,refs,snap,proof)
            require(q['sequence']==self.last_media_sequence+1,'BOUNDARY_CONFLICT')
            # Nonblocking bounded handoff COMMIT is inside this same lock. A
            # real sink waits/decodes outside it and rechecks at its own edge.
            self.media_count+=1;self.unit_media[q['executionId']]=self.unit_media.get(q['executionId'],0)+1
            self.last_media_sequence=q['sequence'];self.proof_refs[q['executionId']]=copy.deepcopy(refs)
            self._event('MEDIA',q['executionId'])
            return dict(requestId=q['requestId'],accepted=True)

    def finish_unit(self,runtime,q):
        self.c.validate('ReceiverFinishUnitRequest',q)
        with self.lock:
            record=copy.deepcopy(self._execution_request(runtime,q))
            refs=self.proof_refs[q['executionId']];proof_q=dict(q,permitId=refs['permitId'])
        barrier,record,refs,snap,proof=self._ongoing_proof(runtime,proof_q)
        with self.lock:
            self._final_execution(runtime,proof_q,barrier,record,refs,snap,proof)
            require(self.unit_media.get(q['executionId'],0)>0,'CONSUMPTION_UNKNOWN');observer=self.observer_fixture
            require(observer is not None,'CONSUMPTION_UNKNOWN')
        evidence=observer(copy.deepcopy(record['binding']))  # trusted callback, outside lock
        require(evidence is not None,'CONSUMPTION_UNKNOWN')
        if self.before_finish_commit:self.before_finish_commit()
        with self.lock:
            self._final_execution(runtime,proof_q,barrier,record,refs,snap,proof)
            self.finished_units.add(q['executionId']);self.active_execution_id=None
            self.barrier+=1;self.barrier_state='STAGED_CLOSED'
            self.local_audit[record['binding']['grantId']]['state']='DRAINED';self._event('FINISH',q['executionId'])
            return dict(requestId=q['requestId'],state='LOCAL_MEDIA_DRAINED',executionId=q['executionId'],artifactId=record['binding']['artifactId'],artifactHash=record['binding']['artifactHash'],evidence=evidence)

    def query_consumption(self,runtime,q):
        self.c.validate('ReceiverQueryConsumptionRequest',q);self.supervisor.check(runtime,'REGISTERED_RUNTIME')
        require(runtime.principalId==getattr(self,'audit_runtime_principal',None),'FORBIDDEN')
        out=self.authority.consumption_summary(self.peer,wire(self.c,bootstrapId=q['bootstrapId'],grantId=q['grantId']))
        with self.lock:
            if out['summary']['state']=='CONSUMED' and not any(r['binding']['grantId']==q['grantId'] for r in self.local.values()):out['summary']['state']='UNKNOWN'
            return dict(out,requestId=q['requestId'])

    def stop(self,control,q):
        self.c.validate('ReceiverStopRequest',q);self.supervisor.check(control,'CONTROL_REGISTRAR')
        with self.lock:
            self.stops.add(q['runId'])  # irreversible for this Run, even before Backend Stop
            if self.staged is None or q['runId']==self.staged['runId']:
                self.barrier+=1;self.barrier_state='CLOSING'
                for row in self.local_audit.values():
                    if row['state']!='DRAINED':row['state']='UNKNOWN'
                self.local.clear();self.proof_refs.clear();self.active_execution_id=None
                self.barrier_state='FENCED';self._event('STOP')
            return dict(requestId=q['requestId'],state='CLOSED_FENCED',runId=q['runId'])

    def restart(self):
        with self.lock:
            self.barrier+=1;self.local.clear();self.proof_refs.clear();self.active_execution_id=None;self.barrier_state='FENCED'
            for row in self.local_audit.values():
                if row['state']!='DRAINED':row['state']='UNKNOWN'
            self._event('RESTART');self.staged=None;self.supervisor.retire(self.peer)
            self.peer=self.supervisor.start_peer('OUTPUT_GUARDIAN')

class RuntimeActor:
    def __init__(self,c,supervisor,guardian,producer,clock,peer=None):
        self.clock=clock;self.suspend_clock=clock;self.c=c;self.supervisor=supervisor;self.guardian=guardian;self.peer=peer or supervisor.start_peer('REGISTERED_RUNTIME',producer)
        self.pending={};self.executions={};self.tts_starts=0;self.grants={};self.artifacts={};self.tickets={};self.start_deadlines={};self.consume_sent={};self.next_media_sequence=0
    def remember_start(self,grant,response,sent):
        self.grants[grant['grantId']]=copy.deepcopy(grant)
        require(response['consumeTicket'] is not None,'GRANT_TICKET_INVALID')
        self.tickets[grant['grantId']]=response['consumeTicket']
        self.start_deadlines[grant['grantId']]=Deadline(response['consumeTiming'],*sent)
    def execution_request(self,execution_id,permit_id=None,media=False):
        b=self.executions[execution_id]['binding'];body=dict(executionId=execution_id,artifactId=b['artifactId'],artifactHash=b['artifactHash'])
        if permit_id is not None:body['permitId']=permit_id
        if media:body.update(kind='audio',sequence=self.next_media_sequence,ptsUs=None,payload=base64.b64encode(bytes(640)).decode())
        return wire(self.c,**body)
    def push_media(self,execution_id,permit_id):
        out=self.guardian.media(self.peer,self.execution_request(execution_id,permit_id,True));self.next_media_sequence+=1;return out
    def renew(self,execution_id,permit_id):return self.guardian.renew(self.peer,self.execution_request(execution_id,permit_id))
    def request(self,registration,refs):
        b=registration['binding'];require(refs['grantId'] in self.tickets,'GRANT_TICKET_INVALID')
        q=wire(self.c,references=copy.deepcopy(refs),consumeTicket=self.tickets[refs['grantId']],consumeRequestId=ident('consume'),expectedGenerationId=b['generationId'],expectedGuardianIncarnation=b['guardianIncarnation'],expectedRegistrationRevision=registration['revision']);self.pending[q['consumeRequestId']]=q;self.consume_sent[q['consumeRequestId']]=(self.clock(),self.suspend_clock());return q
    def accept_ack(self,q,ack):
        require(q['consumeRequestId'] in self.pending,'CONSUMPTION_UNKNOWN')
        if not ack['consumeAuthorized']:
            self.lose_ack(q);return False
        record=ack['consumption'];require(record['consumeRequestId']==q['consumeRequestId'] and record['channelBinding']==self.peer.channelBinding,'CONSUMPTION_CONFLICT')
        self.supervisor.check(self.peer,'REGISTERED_RUNTIME')
        grant=self.grants[q['references']['grantId']]
        self.start_deadlines[grant['grantId']].check(self.clock,self.suspend_clock)
        Deadline(ack['consumeTiming'],*self.consume_sent[q['consumeRequestId']]).check(self.clock,self.suspend_clock)
        artifact=self.artifacts[q['references']['artifactId']]
        self.c.validate_artifact(artifact)
        require(artifact['artifactHash']==record['binding']['artifactHash'],'ANSWER_CONFLICT')
        execution=record['binding']['executionId'];require(execution not in self.executions,'CONSUMPTION_UNKNOWN')
        sent=self.clock(),self.suspend_clock()
        proof=self.guardian.renew(self.peer,wire(self.c,executionId=execution,artifactId=record['binding']['artifactId'],artifactHash=record['binding']['artifactHash'],permitId=q['references']['permitId']))
        Deadline(proof['timing'],*sent,grant=False).check(self.clock,self.suspend_clock,'LEASE_LOST')
        self.start_deadlines[grant['grantId']].check(self.clock,self.suspend_clock)
        Deadline(ack['consumeTiming'],*self.consume_sent[q['consumeRequestId']]).check(self.clock,self.suspend_clock)
        self.executions[execution]=copy.deepcopy(record);self.pending.pop(q['consumeRequestId']);self.tickets.pop(grant['grantId'],None);self.tts_starts+=1
        return True
    def lose_ack(self,q):
        self.pending.pop(q['consumeRequestId'],None);self.tickets.pop(q['references']['grantId'],None)
    def restart(self):
        self.pending.clear();self.executions.clear();self.grants.clear();self.artifacts.clear();self.tickets.clear();self.start_deadlines.clear();self.supervisor.retire(self.peer)
        self.peer=self.supervisor.start_peer('REGISTERED_RUNTIME',self.supervisor.principals[self.peer.principalId]['producer'])

class Participants:
    """Fixtures start unregistered: bootstrap() must execute stage+register."""
    def __init__(self,journal,c):
        self.c=c;self.j=journal;self.supervisor=Supervisor(c);self.control=self.supervisor.start_peer('CONTROL_REGISTRAR')
        self.backend=BackendAuthority(journal,c,self.supervisor);self.guardian=GuardianReceiver(self.backend,c,self.supervisor,lambda:journal.now)
        self.runtime=RuntimeActor(c,self.supervisor,self.guardian,journal.producer,lambda:journal.now);self.transcript=[]
    def stop(self):
        # CONTROL orchestrates separate Guardian and Backend operations. The
        # Guardian has no Backend Stop/CONTROL mutation permission.
        self.guardian.stop(self.control,wire(self.c,runId=self.j.command['runId']))
        self.backend.stop(self.control)
    def bootstrap(self):
        proof,installed=self.supervisor.install(self.control,self.backend.context,self.runtime.peer,self.guardian.peer)
        cmd=self.backend.context;b={k:cmd[k] for k in ('tenantId','ownerId','runId','sessionId','producerIncarnation','attemptId','commandId','turnId','utteranceId','runEpoch')}
        b.update(contractRevision='durable-live-2',receiverRevision='receiver-1',bootstrapId=ident('bootstrap'),roomId=self.backend.room_id,guardianId='guardian_demo',guardianIncarnation=installed['guardianIncarnation'],runtimePrincipalId=self.runtime.peer.principalId,runtimeIncarnation=self.runtime.peer.incarnation,physicalInstallProofRef=proof,generationId=installed['generationId'],outputBindingVersion=1)
        self.supervisor.seal_binding(self.control,b)
        challenge=self.backend.challenge(self.control,b)
        stage=wire(self.c,binding=b,**challenge);reply=self.guardian.stage(self.control,stage);self.transcript.append(dict(fromActor='CONTROL_REGISTRAR',toActor='GUARDIAN',operationId='ReceiverStage',request=stage,response=reply))
        q=wire(self.c,binding=b,receipt=reply['receipt'],expectedRegistrationRevision=0,expectedRunRevision=1,expectedLeaseVersion=cmd['leaseVersion']);out=self.backend.register(self.control,q);self.transcript.append(dict(fromActor='CONTROL_REGISTRAR',toActor='BACKEND',operationId='RegisterReceiverBootstrap',request=q,response=out));return out['registration']
