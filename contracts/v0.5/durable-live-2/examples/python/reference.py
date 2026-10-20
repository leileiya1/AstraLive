"""Executable contract oracle, NOT a Store/DB fallback or production executor.

All tests use synthetic authority, clock and drain proofs. Agent2 must implement
and test the transaction/constraints on real PostgreSQL after owner approval.
"""
import copy
import importlib.util
from pathlib import Path
import threading
import secrets
from datetime import datetime, timezone

ROOT=Path(__file__).resolve().parents[5]
spec=importlib.util.spec_from_file_location('answer_contract',ROOT/'scripts/validate-answer-contract.py')
c=importlib.util.module_from_spec(spec);spec.loader.exec_module(c)

class Rejected(ValueError):
    pass

def fail(code):
    raise Rejected(code)

def timestamp(value):
    return datetime.fromisoformat(value.replace('Z','+00:00')).timestamp()

def stamp(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat(timespec='milliseconds').replace('+00:00','Z')

def drain_identity(request):
    """Only correlation and optimistic read revision are retry metadata."""
    return {'operation':'JournalConfirmAnswerSegment', **{
        k:copy.deepcopy(v) for k,v in request.items()
        if k not in ('requestId','expectedAnswerRevision')}}

class JournalOracle:
    def __init__(self, command, artifacts):
        c.validate_command(command)
        self.command=copy.deepcopy(command)
        self._lock=threading.RLock()
        self.now=timestamp(command['createdAt'])
        self.binding_until=self.now+3600
        self.lease_until=self.now+15
        self.permit_until=self.now+.8
        self.fact_verified=self.now
        self.facts={f['kind']:(f['sourceVersion'],f['valueHash']) for a in artifacts for f in a['factDependencies']}
        self.snapshot=artifacts[0]['productSnapshotVersion']
        self.epoch=command['runEpoch']
        self.producer=artifacts[0]['producerIncarnation']
        self.stopped=False
        self.role='RUNTIME_JOURNAL'
        self.state='ACCEPTED';self.inbox_revision=1;self.answer_revision=0
        self.units=[];self.prepare_receipts={};self.drain_receipts={};self.seal_receipt=None
        self.drains={};self.tts_started=set()
        self.answer_id=None;self.sealed=False;self.grants={};self.command_start_count=0
        self.grant_states={};self.executions={};self.execution_states={}
        self.observations={};self.current_observations={}
        self.permits={};self.current_permits={}
        self.generation_id=None;self.guardian_incarnation=None
        self.registration_record=None;self.ticket_verifiers={}
        self.registration_id=None  # populated only by trusted CONTROL stage/register
        self.runtime_alive=True

    def guard(self,q):
        if self.role!='RUNTIME_JOURNAL':fail('FORBIDDEN')
        if q.get('contractRevision')!='durable-live-2':fail('CONTRACT_REVISION_MISMATCH')
        for key in ('tenantId','ownerId','runId','commandId','attemptId','sessionId','requestHash'):
            if q[key]!=self.command[key]:fail('FORBIDDEN' if key in ('tenantId','ownerId') else 'COMMAND_CONFLICT')
        if q['runEpoch']!=self.epoch:fail('STALE_RUN_EPOCH')
        if q['producerIncarnation']!=self.producer:fail('FORBIDDEN')
        if self.stopped:fail('RUN_STOPPED')
        if self.binding_until<=self.now:fail('BINDING_EXPIRED')
        if self.lease_until<=self.now:fail('LEASE_LOST')
        if timestamp(self.command['payload']['expiresAt'])<=self.now:fail('COMMAND_EXPIRED')
        if self.units and self.units[0]['artifact']['productSnapshotVersion']!=self.snapshot:fail('PLAN_CHANGED')
        if self.registration_id is None:fail('BOOTSTRAP_REQUIRED')

    def _identity(self,a):
        return {k:a[k] for k in ('tenantId','ownerId','runId','commandId','attemptId',
                                'sessionId','runEpoch','producerIncarnation',
                                'answerId','artifactId','artifactHash')}

    def _check_record(self,record,a):
        if any(record.get(k)!=v for k,v in self._identity(a).items()):fail('ANSWER_CONFLICT')
        if record.get('generationId')!=self.generation_id:fail('EVIDENCE_CONFLICT')

    def _new_observation(self,a,at):
        return dict(**self._identity(a),observationId='observation_'+str(len(self.observations)+1),
                    generationId=self.generation_id,productSnapshotVersion=a['productSnapshotVersion'],
                    factSetHash=c.digest(a['factDependencies']),verifiedAt=stamp(at),
                    validUntil=stamp(at+2),authorityRevision='authority_demo')

    def _observation(self,a):
        observation_id=self.current_observations.get(a['artifactId'])
        if observation_id is None:
            # Request-local preflight before a successful prepare; no failed
            # prepare publishes an Artifact or a key/receipt binding.
            return self._new_observation(a,self.fact_verified)
        return self.observations[observation_id]

    def _check_facts(self,a):
        if a['productSnapshotVersion']!=self.snapshot:fail('PLAN_CHANGED')
        for fact in a['factDependencies']:
            if self.facts.get(fact['kind'])!=(fact['sourceVersion'],fact['valueHash']):fail('PLAN_CHANGED')

    def _live_execution(self,a):
        if not self.runtime_alive or self.state=='UNKNOWN':fail('RECOVERY_UNKNOWN')
        if self.state not in ('ACCEPTED','STARTED'):fail('STATE_CONFLICT')
        if self._unit(a['artifactId'])['state'] not in ('PREPARED','STARTED'):fail('RECOVERY_UNKNOWN')

    def refresh_facts(self,artifact_id,*,grant=None,epoch=None,producer=None,
                      generation_id=None,attempt_id=None):
        """Synthetic trusted authority verification, never Runtime self-approval."""
        with self._lock:
            a=self._unit(artifact_id)['artifact'];self.guard(a);self._live_execution(a)
            self._renewal_identity(a,grant,epoch,producer,generation_id,attempt_id)
            self._check_facts(a)
            observation=self._new_observation(a,self.now)
            self.observations[observation['observationId']]=copy.deepcopy(observation)
            self.current_observations[artifact_id]=observation['observationId']
            # Retained as a legacy synthetic authority-failure injection knob.
            self.fact_verified=self.now
            return copy.deepcopy(observation)

    def _resolve_grant(self,a,grant):
        stored=self.grants.get(a['artifactId'])
        if not isinstance(grant,dict) or stored!=grant:fail('ANSWER_CONFLICT')
        return stored

    def _renewal_identity(self,a,grant,epoch,producer,generation_id,attempt_id):
        if epoch is not None and epoch!=a['runEpoch']:fail('STALE_RUN_EPOCH')
        if producer is not None and producer!=a['producerIncarnation']:fail('FORBIDDEN')
        if attempt_id is not None and attempt_id!=a['attemptId']:fail('COMMAND_CONFLICT')
        if generation_id is not None and generation_id!=self.generation_id:fail('EVIDENCE_CONFLICT')
        if grant is not None:self._resolve_grant(a,grant)
        execution=self.executions.get(a['artifactId'])
        if execution is not None:
            self._check_record(execution,a)
            if execution['guardianIncarnation']!=self.guardian_incarnation:fail('RECOVERY_UNKNOWN')
            if self.execution_states.get(a['artifactId'])!='ACTIVE':fail('RECOVERY_UNKNOWN')

    def _issue_permit(self,a,permit_id):
        self.fresh(a)
        observation=self._observation(a)
        expiry=min(self.now+.8,timestamp(observation['validUntil']),self.binding_until,
                   self.lease_until,timestamp(self.command['payload']['expiresAt']))
        if expiry<=self.now:fail('LEASE_LOST')
        permit=dict(**self._identity(a),permitId=permit_id,generationId=self.generation_id,
                    guardianIncarnation=self.guardian_incarnation,
                    factObservationId=observation['observationId'],issuedAt=stamp(self.now),
                    expiresAt=stamp(expiry))
        self.permits[permit_id]=copy.deepcopy(permit)
        self.current_permits[a['artifactId']]=permit_id
        self.permit_until=max(self.permit_until,expiry)
        return copy.deepcopy(permit)

    def renew_permit(self,artifact_id,*,grant=None,epoch=None,producer=None,
                     generation_id=None,attempt_id=None):
        with self._lock:
            a=self._unit(artifact_id)['artifact'];self.guard(a);self._live_execution(a)
            self._renewal_identity(a,grant,epoch,producer,generation_id,attempt_id)
            return self._issue_permit(a,'renewed_permit_'+str(len(self.permits)+1))

    def _check_permit(self,a,permit_id=None):
        permit_id=permit_id or self.current_permits.get(a['artifactId'])
        permit=self.permits.get(permit_id)
        if permit is None:fail('OUTPUT_FENCE_UNPROVEN')
        self._check_record(permit,a)
        if permit['guardianIncarnation']!=self.guardian_incarnation:fail('RECOVERY_UNKNOWN')
        observation=self.observations.get(permit['factObservationId'])
        if observation is None:fail('FACT_EXPIRED')
        self._check_record(observation,a)
        if self.now>=timestamp(observation['validUntil']):fail('FACT_EXPIRED')
        if self.now>=min(timestamp(permit['expiresAt']),self.permit_until):fail('LEASE_LOST')
        return permit

    def fresh(self,a,permit=False):
        self._check_facts(a)
        for fact in a['factDependencies']:
            if self.now-self.fact_verified>=2 or self.fact_verified>self.now:fail('FACT_EXPIRED')
        observation=self._observation(a);self._check_record(observation,a)
        if self.now>=timestamp(observation['validUntil']):fail('FACT_EXPIRED')
        if permit:self._check_permit(a)

    def prepare(self,q):
        c.validate('JournalPrepareAnswerRequest',q)
        with self._lock:
            self.guard(q)
            a=q['artifact'];c.validate_artifact(a);self.guard(a);self.fresh(a)
            key=q['idempotencyKey']
            if key in self.prepare_receipts:
                saved,receipt=self.prepare_receipts[key]
                if saved!=a:fail('ANSWER_CONFLICT')
                return copy.deepcopy(receipt)
            for saved, receipt in self.prepare_receipts.values():
                if saved['artifactId']==a['artifactId'] or saved['sequence']==a['sequence']:
                    if saved!=a:fail('ANSWER_CONFLICT')
                    # The successful alias readback reserves the key in the
                    # same critical section as descriptor/receipt verification.
                    self.prepare_receipts[key]=(copy.deepcopy(a),copy.deepcopy(receipt))
                    return copy.deepcopy(receipt)
            if self.sealed:fail('ANSWER_CLOSED')
            if self.state!=('ACCEPTED' if not self.units else 'STARTED'):fail('STATE_CONFLICT')
            if q['expectedInboxRevision']!=self.inbox_revision or q['expectedAnswerRevision']!=self.answer_revision:fail('STATE_CONFLICT')
            if a['sequence']!=len(self.units)+1 or a['previousArtifactHash']!=(self.units[-1]['artifact']['artifactHash'] if self.units else None):fail('ANSWER_GAP')
            if self.answer_id and a['answerId']!=self.answer_id:fail('ANSWER_CONFLICT')
            if sum(u['state']!='DRAINED' for u in self.units)>=2:fail('ANSWER_WINDOW_FULL')
            if self.units and self.units[-1]['state'] not in ('STARTED','DRAINED'):fail('ANSWER_GAP')
            if self.units and self.units[-1]['state']=='DRAINED' and self.units[-1]['artifact']['artifactId'] not in self.drains:fail('EVIDENCE_CONFLICT')
            if len(self.units)>=32 or sum(len(u['artifact']['answerText']) for u in self.units)+len(a['answerText'])>2000:fail('ANSWER_LIMIT_EXCEEDED')
            # A real Store commits all descriptor/fact/hash fields + receipt in
            # one SQL transaction. The oracle publishes a copy only after checks.
            if not self.units:self.inbox_revision+=1
            self.answer_id=a['answerId'];self.answer_revision+=1
            self.units.append(dict(artifact=copy.deepcopy(a),state='PREPARED'))
            observation=self._new_observation(a,self.fact_verified)
            self.observations[observation['observationId']]=copy.deepcopy(observation)
            self.current_observations[a['artifactId']]=observation['observationId']
            # Fixture bootstrap permits represent the existing pre-START
            # acquisition. They never authorize TTS by themselves.
            self._issue_permit(a,'permit_answer' if a['sequence']==1 else 'permit_answer_'+str(a['sequence']))
            receipt=dict(prepared=True,artifactId=a['artifactId'],artifactHash=a['artifactHash'],inboxRevision=self.inbox_revision,answerRevision=self.answer_revision)
            self.prepare_receipts[key]=(copy.deepcopy(a),copy.deepcopy(receipt))
            return receipt

    def _unit(self,artifact_id):
        for unit in self.units:
            if unit['artifact']['artifactId']==artifact_id:return unit
        fail('ANSWER_NOT_PREPARED')

    def _grant(self,u,permit_id):
        a=u['artifact'];self.fresh(a)
        permit=self._check_permit(a,permit_id)
        u['state']='STARTED';self.answer_revision+=1
        grant=dict(grantId='grant_'+str(len(self.grants)+1),commandId=a['commandId'],
                   attemptId=a['attemptId'],sessionId=a['sessionId'],runEpoch=a['runEpoch'],
                   producerIncarnation=a['producerIncarnation'],answerId=a['answerId'],
                   artifactId=a['artifactId'],artifactHash=a['artifactHash'],sequence=a['sequence'],
                   permitId=permit_id,factObservationId=permit['factObservationId'],
                   factValidUntil=self._observation(a)['validUntil'],issuedAt=stamp(self.now),
                   expiresAt=permit['expiresAt'],authorizationScope='UNIT_START_ONCE')
        self.grants[a['artifactId']]=copy.deepcopy(grant)
        self.grant_states[grant['grantId']]='ISSUED'
        return copy.deepcopy(grant)

    def consume_timing(self,grant,permit):
        proof_end=min(timestamp(permit['expiresAt']),self.binding_until,self.lease_until,
                      timestamp(self.command['payload']['expiresAt']))
        return dict(remainingGrantMs=max(0,min(1000,round((timestamp(grant['expiresAt'])-self.now)*1000))),
                    remainingProofMs=max(0,min(1000,round((proof_end-self.now)*1000))),safetyMarginMs=100)

    def ticket_hash(self,grant,ticket):
        b=self.registration_record
        return c.digest(dict(domain='receiver-consume-ticket-1',contractRevision='durable-live-2',
                             receiverRevision='receiver-1',grantId=grant['grantId'],
                             registrationHash=b['registrationHash'],
                             runtimePrincipalId=b['binding']['runtimePrincipalId'],ticket=ticket))

    def mint_ticket(self,grant):
        ticket=secrets.token_urlsafe(32)
        self.ticket_verifiers[grant['grantId']]=self.ticket_hash(grant,ticket)
        return ticket

    def start(self,q):
        c.validate('JournalStartRequest',q)
        with self._lock:
            self.guard(q)
            if self.state!='ACCEPTED':return dict(startAuthorized=False,answerGrant=None,consumeTicket=None,consumeTiming=None,revision=self.inbox_revision)
            if not self.units:fail('ANSWER_NOT_PREPARED')
            u=self.units[0];a=u['artifact']
            if q['answerArtifactId']!=a['artifactId'] or q['answerArtifactHash']!=a['artifactHash']:fail('ANSWER_CONFLICT')
            if q['expectedInboxRevision']!=self.inbox_revision or q['expectedAnswerRevision']!=self.answer_revision:fail('STATE_CONFLICT')
            grant=self._grant(u,q['permitId'])
            self.state='STARTED';self.inbox_revision+=1;self.command_start_count+=1
            return dict(startAuthorized=True,answerGrant=grant,consumeTicket=self.mint_ticket(grant),consumeTiming=self.consume_timing(grant,self.permits[grant['permitId']]),revision=self.inbox_revision)

    def start_segment(self,q):
        c.validate('JournalStartAnswerSegmentRequest',q)
        with self._lock:
            self.guard(q)
            u=self._unit(q['artifactId']);a=u['artifact']
            if q['artifactHash']!=a['artifactHash'] or q['answerId']!=a['answerId']:fail('ANSWER_CONFLICT')
            if u['state']!='PREPARED':return dict(segmentStartAuthorized=False,grant=None,consumeTicket=None,consumeTiming=None)
            if self.state!='STARTED' or a['sequence']==1:fail('STATE_CONFLICT')
            if self.units[a['sequence']-2]['state']!='DRAINED':fail('ANSWER_GAP')
            if self.units[a['sequence']-2]['artifact']['artifactId'] not in self.drains:fail('EVIDENCE_CONFLICT')
            if q['expectedAnswerRevision']!=self.answer_revision:fail('STATE_CONFLICT')
            grant=self._grant(u,q['permitId'])
            return dict(segmentStartAuthorized=True,grant=grant,consumeTicket=self.mint_ticket(grant),consumeTiming=self.consume_timing(grant,self.permits[grant['permitId']]))

    def _consume(self,artifact_id,grant):
        u=self._unit(artifact_id);a=u['artifact'];self.guard(a);self._live_execution(a)
        stored=self._resolve_grant(a,grant)
        if self.grant_states[stored['grantId']]!='ISSUED':fail('RECOVERY_UNKNOWN')
        if self.now>=timestamp(stored['expiresAt']):
            self.grant_states[stored['grantId']]='EXPIRED'
            u['state']='UNKNOWN';self.state='UNKNOWN'
            fail('GRANT_EXPIRED')
        # The original proof pins the pre-consumption Generation as well as
        # the once-only deadline. A new proof cannot rebind an unused grant.
        self._check_permit(a,stored['permitId'])
        self.fresh(a,permit=True)
        if u['state']!='STARTED':fail('STATE_CONFLICT')
        binding=dict(**self._identity(a),executionId='execution_'+stored['grantId'],
                     grantId=stored['grantId'],generationId=self.generation_id,
                     guardianIncarnation=self.guardian_incarnation,consumedAt=stamp(self.now))
        self.executions[artifact_id]=copy.deepcopy(binding)
        self.execution_states[artifact_id]='ACTIVE'
        self.grant_states[stored['grantId']]='CONSUMED'
        return binding

    def begin_tts(self,artifact_id,grant):
        with self._lock:
            if artifact_id in self.tts_started:fail('RECOVERY_UNKNOWN')
            self._consume(artifact_id,grant)
            self.tts_started.add(artifact_id)
            return self.handoff(artifact_id,grant)

    def handoff(self,artifact_id,grant):
        # Models the last local gate only; no actual GPU/media is produced.
        with self._lock:
            a=self._unit(artifact_id)
            self.guard(a['artifact']);self.fresh(a['artifact'],permit=True)
            self._resolve_grant(a['artifact'],grant)
            # Legacy guard-only fixtures model consumption at first handoff;
            # the normative Runtime consumes before TTS as begin_tts does.
            if artifact_id not in self.executions:self._consume(artifact_id,grant)
            self._renewal_identity(a['artifact'],grant,None,None,None,None)
            if a['state']!='STARTED':fail('STATE_CONFLICT')
            return a['artifact']['answerText']

    def runtime_restart(self):
        with self._lock:
            self.runtime_alive=False;self.state='UNKNOWN'
            for unit in self.units:
                if unit['state']=='STARTED':unit['state']='UNKNOWN'
                grant=self.grants.get(unit['artifact']['artifactId'])
                if grant and self.grant_states[grant['grantId']]=='ISSUED':self.grant_states[grant['grantId']]='UNKNOWN'
            for artifact_id in self.execution_states:self.execution_states[artifact_id]='UNKNOWN'

    def mark_unknown(self,artifact_id):
        with self._lock:
            self._unit(artifact_id)['state']='UNKNOWN';self.state='UNKNOWN'
            grant=self.grants.get(artifact_id)
            if grant and self.grant_states[grant['grantId']]=='ISSUED':self.grant_states[grant['grantId']]='UNKNOWN'
            if artifact_id in self.execution_states:self.execution_states[artifact_id]='UNKNOWN'

    def drain(self,q):
        c.validate('JournalConfirmAnswerSegmentRequest',q)
        with self._lock:
            self.guard(q)
            # Reuse v1 range validator only for arithmetic, never trust a PCM flag.
            cp=copy.deepcopy(next(x['value'] for x in c.common.load('examples/objects.json') if x['name']=='PlaybackCheckpoint'))
            cp['evidence']=q['evidence'];c.common.validate_checkpoint(cp)
            u=self._unit(q['artifactId'])
            if u['artifact']['artifactHash']!=q['artifactHash'] or u['artifact']['answerId']!=q['answerId']:fail('ANSWER_CONFLICT')
            key=q['idempotencyKey']
            stable=drain_identity(q)
            if key in self.drain_receipts:
                saved,receipt=self.drain_receipts[key]
                if saved!=stable:fail('ANSWER_CONFLICT')
                return copy.deepcopy(receipt)
            if u['state']!='STARTED' or q['expectedAnswerRevision']!=self.answer_revision:fail('STATE_CONFLICT')
            if u['artifact']['sequence']>1:
                previous=self.units[u['artifact']['sequence']-2]
                prior=self.drains[previous['artifact']['artifactId']]
                by_sink={p['sinkId']:p for p in prior['sinkProofs']}
                for proof in q['evidence']['sinkProofs']:
                    old=by_sink.get(proof['sinkId'])
                    if old is None or proof['firstAudioSample']!=old['finalAudioSampleExclusive'] or proof['finalVideoFrame']<old['finalVideoFrame']:fail('EVIDENCE_CONFLICT')
            self.drains[q['artifactId']]=copy.deepcopy(q['evidence'])
            u['state']='DRAINED';self.answer_revision+=1
            grant=self.grants.get(q['artifactId'])
            if grant and self.grant_states[grant['grantId']]=='ISSUED':self.grant_states[grant['grantId']]='CONSUMED'
            if q['artifactId'] in self.execution_states:self.execution_states[q['artifactId']]='DRAINED'
            receipt=dict(state='DRAINED',answerId=q['answerId'],artifactId=q['artifactId'],
                         artifactHash=q['artifactHash'],drainIdentityHash=c.digest(stable),
                         answerRevision=self.answer_revision)
            self.drain_receipts[key]=(copy.deepcopy(stable),copy.deepcopy(receipt))
            return receipt

    def seal(self,q):
        c.validate('JournalSealAnswerRequest',q)
        with self._lock:
            self.guard(q)
            manifest=[{k:u['artifact'][k] for k in ('artifactId','sequence','artifactHash')} for u in self.units]
            actual=dict(sequenceCount=len(self.units),manifestHash=c.digest(manifest),finalAnswerTextHash=c.text_hash(''.join(u['artifact']['answerText'] for u in self.units)))
            if q['answerId']!=self.answer_id or any(q[k]!=v for k,v in actual.items()):fail('ANSWER_CONFLICT')
            if self.sealed:return copy.deepcopy(self.seal_receipt)
            if q['expectedAnswerRevision']!=self.answer_revision:fail('STATE_CONFLICT')
            self.sealed=True;self.answer_revision+=1
            self.seal_receipt=dict(state='SEALED',answerRevision=self.answer_revision,**actual)
            return copy.deepcopy(self.seal_receipt)

    def complete(self):
        with self._lock:
            if not self.sealed or any(u['state']!='DRAINED' for u in self.units):fail('STATE_CONFLICT')
            self.state='TERMINAL'
