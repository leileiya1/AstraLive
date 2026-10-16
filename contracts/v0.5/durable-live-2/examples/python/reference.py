"""Executable contract oracle, NOT a Store/DB fallback or production executor.

All tests use synthetic authority, clock and drain proofs. Agent2 must implement
and test the transaction/constraints on real PostgreSQL after owner approval.
"""
import copy
import importlib.util
from pathlib import Path
import threading
from datetime import datetime

ROOT=Path(__file__).resolve().parents[5]
spec=importlib.util.spec_from_file_location('answer_contract',ROOT/'scripts/validate-answer-contract.py')
c=importlib.util.module_from_spec(spec);spec.loader.exec_module(c)

class Rejected(ValueError):
    pass

def fail(code):
    raise Rejected(code)

def timestamp(value):
    return datetime.fromisoformat(value.replace('Z','+00:00')).timestamp()

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

    def fresh(self,a,permit=False):
        if a['productSnapshotVersion']!=self.snapshot:fail('PLAN_CHANGED')
        for fact in a['factDependencies']:
            if self.facts.get(fact['kind'])!=(fact['sourceVersion'],fact['valueHash']):fail('PLAN_CHANGED')
            if self.now-self.fact_verified>=2 or self.fact_verified>self.now:fail('FACT_EXPIRED')
        if permit and self.now>=self.permit_until:fail('LEASE_LOST')

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
                    return copy.deepcopy(receipt)
            if self.sealed:fail('ANSWER_CLOSED')
            if self.state!=('ACCEPTED' if not self.units else 'STARTED'):fail('STATE_CONFLICT')
            if q['expectedInboxRevision']!=self.inbox_revision or q['expectedAnswerRevision']!=self.answer_revision:fail('STATE_CONFLICT')
            if a['sequence']!=len(self.units)+1 or a['previousArtifactHash']!=(self.units[-1]['artifact']['artifactHash'] if self.units else None):fail('ANSWER_GAP')
            if self.answer_id and a['answerId']!=self.answer_id:fail('ANSWER_CONFLICT')
            if sum(u['state']!='DRAINED' for u in self.units)>=2:fail('ANSWER_WINDOW_FULL')
            if self.units and self.units[-1]['state']!='STARTED':fail('ANSWER_GAP')
            if len(self.units)>=32 or sum(len(u['artifact']['answerText']) for u in self.units)+len(a['answerText'])>2000:fail('ANSWER_LIMIT_EXCEEDED')
            # A real Store commits all descriptor/fact/hash fields + receipt in
            # one SQL transaction. The oracle publishes a copy only after checks.
            if not self.units:self.inbox_revision+=1
            self.answer_id=a['answerId'];self.answer_revision+=1
            self.units.append(dict(artifact=copy.deepcopy(a),state='PREPARED'))
            receipt=dict(prepared=True,artifactId=a['artifactId'],artifactHash=a['artifactHash'],inboxRevision=self.inbox_revision,answerRevision=self.answer_revision)
            self.prepare_receipts[key]=(copy.deepcopy(a),copy.deepcopy(receipt))
            return receipt

    def _unit(self,artifact_id):
        for unit in self.units:
            if unit['artifact']['artifactId']==artifact_id:return unit
        fail('ANSWER_NOT_PREPARED')

    def _grant(self,u):
        self.fresh(u['artifact'],permit=True)
        u['state']='STARTED';self.answer_revision+=1
        grant='grant_'+str(len(self.grants)+1)
        self.grants[u['artifact']['artifactId']]=grant
        return grant

    def start(self,q):
        c.validate('JournalStartRequest',q)
        with self._lock:
            self.guard(q)
            if self.state!='ACCEPTED':return dict(startAuthorized=False,answerGrant=None,revision=self.inbox_revision)
            if not self.units:fail('ANSWER_NOT_PREPARED')
            u=self.units[0];a=u['artifact']
            if q['answerArtifactId']!=a['artifactId'] or q['answerArtifactHash']!=a['artifactHash']:fail('ANSWER_CONFLICT')
            if q['expectedInboxRevision']!=self.inbox_revision or q['expectedAnswerRevision']!=self.answer_revision:fail('STATE_CONFLICT')
            grant=self._grant(u)
            self.state='STARTED';self.inbox_revision+=1;self.command_start_count+=1
            return dict(startAuthorized=True,answerGrant=grant,revision=self.inbox_revision)

    def start_segment(self,q):
        c.validate('JournalStartAnswerSegmentRequest',q)
        with self._lock:
            self.guard(q)
            u=self._unit(q['artifactId']);a=u['artifact']
            if q['artifactHash']!=a['artifactHash'] or q['answerId']!=a['answerId']:fail('ANSWER_CONFLICT')
            if u['state']!='PREPARED':return dict(segmentStartAuthorized=False,grant=None)
            if self.state!='STARTED' or a['sequence']==1:fail('STATE_CONFLICT')
            if self.units[a['sequence']-2]['state']!='DRAINED':fail('ANSWER_GAP')
            if q['expectedAnswerRevision']!=self.answer_revision:fail('STATE_CONFLICT')
            return dict(segmentStartAuthorized=True,grant=self._grant(u))

    def begin_tts(self,artifact_id,grant):
        with self._lock:
            text=self.handoff(artifact_id,grant)
            if artifact_id in self.tts_started:fail('RECOVERY_UNKNOWN')
            self.tts_started.add(artifact_id)
            return text

    def handoff(self,artifact_id,grant):
        # Models the last local gate only; no actual GPU/media is produced.
        with self._lock:
            a=self._unit(artifact_id)
            self.guard(a['artifact']);self.fresh(a['artifact'],permit=True)
            if a['state']!='STARTED' or self.grants.get(artifact_id)!=grant:fail('STATE_CONFLICT')
            return a['artifact']['answerText']

    def drain(self,q):
        c.validate('JournalConfirmAnswerSegmentRequest',q)
        with self._lock:
            self.guard(q)
            # Reuse v1 range validator only for arithmetic, never trust a PCM flag.
            cp=copy.deepcopy(next(x['value'] for x in c.common.load('examples/objects.json') if x['name']=='PlaybackCheckpoint'))
            cp['evidence']=q['evidence'];c.common.validate_checkpoint(cp)
            u=self._unit(q['artifactId'])
            if u['artifact']['artifactHash']!=q['artifactHash']:fail('ANSWER_CONFLICT')
            key=q['idempotencyKey']
            if key in self.drain_receipts:
                saved,receipt=self.drain_receipts[key]
                if saved!=q['evidence']:fail('ANSWER_CONFLICT')
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
            receipt=dict(state='DRAINED',answerRevision=self.answer_revision)
            self.drain_receipts[key]=(copy.deepcopy(q['evidence']),copy.deepcopy(receipt))
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
