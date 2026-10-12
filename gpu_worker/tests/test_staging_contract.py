import copy
import json
import pathlib
import unittest
from gpu_worker import staging_contract as c


def sample(schema):
    if '$ref' in schema:return sample(c.DEFS[schema['$ref'].split('/')[-1]])
    for k in ('oneOf','anyOf'):
        if k in schema:return sample(schema[k][0])
    if 'const' in schema:return copy.deepcopy(schema['const'])
    if 'enum' in schema:return copy.deepcopy(schema['enum'][0])
    kind=schema.get('type')
    if kind=='integer':return schema['minimum']
    if kind=='boolean':return False
    if kind=='null':return None
    if kind=='string':return 'sha256:'+'a'*64 if schema.get('pattern')==c.HASH_PATTERN else 'x'*max(1,schema.get('minLength',1))
    if kind=='object':return {k:sample(v) for k,v in schema['properties'].items()}
    if kind=='array':return [sample(schema['items']) for _ in range(schema['minItems'])]
    raise ValueError(schema)

def identity():
    value=sample(c.IDENTITY)
    for key in c.IDENTITY_FIELDS:
        if isinstance(value[key],str) and key!='lane':value[key]=key+'_1'
    value['interactionTurnId']=None
    return value

def message(name):
    value=sample(c.MESSAGES[name])
    if name=='Auth':return value
    if name=='GPU_WORKER_READY':value['profile_gate_ref']=None;return value
    if name in ('StageHealth','StageHealthAck'):return value
    ident=identity();value['identity']=ident;value['session_id']=ident['sessionId'];value['worker_epoch']=ident['workerEpoch']
    return value

def begin():
    value=message('StageBegin');value.update(original_samples=640,pad_samples=0,source_samples=640,lease_ms=9000,a_rtt_ms=20,worker_rtt_ms=20,safety_ms=100)
    value['a_grant'].update(sessionId=value['session_id'],runEpoch=1,remainingMs=10000)
    value['request_fingerprint']=c.stage_begin_fingerprint(value)
    return value

def produced():
    value=message('StageProduced');d=value['descriptor'];d.update(identity=value['identity'],original_samples=640,pad_samples=0,source_samples=640,frame_count=1,last_sequence=0,last_pts_us=0)
    d['provenance'].update(workerRef=value['identity']['workerRef'],workerEpoch=value['worker_epoch'],model_source_revision='中文/<>&')
    for key in d['resources']:
        if key.startswith('gpu_'):d['resources'][key]=0
    value['descriptor_sha256']=c.descriptor_hash(d)
    return value

def commit():
    value=message('StageCommit');p=value['commit_proof'];i=value['identity'];a=p['a_installed_ref']
    for key in ('sessionId','runEpoch','timelineEpoch','commandId','segmentId','attemptId','generationId'):a[key]=i[key]
    p['output'].update(sampleRate=48000,startSample=100,endSample=2020,sourceSamples=640,ratioNumerator=3,ratioDenominator=1)
    p['required_sinks']=[{'sinkId':'rtmp1','incarnation':'x'}];p['optional_sinks']=[]
    value['commit_proof_fingerprint']=c.commit_fingerprint(i,p)
    return value

def pose():
    value=message('StagePoseConsumed');p=value['pose_proof'];p.update(latest_consumed_sequence=0,source_end_sample=640,output_end_sample=2020)
    p['required_sink_receipts']=[{'sinkId':'rtmp1','incarnation':'x','evidenceRef':'receipt1','localRevision':1,'startSample':100,'audioEndSample':2020,'videoEndSample':2020,'evidenceType':'sink_consumed'}]
    value['pose_proof_fingerprint']=c.pose_fingerprint(value['identity'],p)
    return value

def renewal(sequence=1):
    value=message('StageRenew');value.update(renewal_sequence=sequence,lease_ms=9000,a_rtt_ms=20,worker_rtt_ms=20,safety_ms=100)
    value['a_grant'].update(sessionId=value['session_id'],runEpoch=1,remainingMs=10000)
    value['renewal_fingerprint']=c.renewal_fingerprint(value);return value

class StagingContractTests(unittest.TestCase):
    def test_schema_source_equal(self):
        root=pathlib.Path(__file__).resolve().parents[2]
        self.assertEqual(json.loads((root/'docs/v0.5/staging-protocol.schema.json').read_text()),c.SCHEMA)
    def test_core_hash_vectors(self):
        root=pathlib.Path(__file__).resolve().parents[2]
        for vector in json.loads((root/'docs/v0.5/staging-canonical-vectors.json').read_text()):
            self.assertEqual(c.canonical_bytes(vector['projection']).decode(),vector['canonical'])
            self.assertEqual(c.digest(vector['projection']),vector['sha256'])
    def test_valid_core(self):
        for value in (begin(),produced(),commit(),pose(),renewal()):c.validate_message(value)
    def test_unknown_float_bool_integer_and_duplicate_reject(self):
        b=begin();b['unexpected']=None
        with self.assertRaises(c.ContractError):c.validate_message(b)
        for n in (True,1.0,c.MAX_INTEGER+1):
            b=begin();b['identity']['runEpoch']=n
            with self.assertRaises(c.ContractError):c.validate_message(b)
        for raw in (b'{"x":1,"x":2}',b'{"x":1.0}',b'[]'):
            with self.assertRaises(c.ContractError):c.decode_header(raw)
    def test_content_mutation_hash_rejected(self):
        b=begin();b['pcm_sha256']='sha256:'+'b'*64
        with self.assertRaises(c.ContractError):c.validate_message(b)
        d=produced();d['descriptor']['provenance']['workerEpoch']='foreign';d['descriptor_sha256']=c.descriptor_hash(d['descriptor'])
        with self.assertRaises(c.ContractError):c.validate_message(d)
    def test_simulation_metrics_are_null(self):
        d=produced();d['descriptor']['provenance']['source']='CPU_SIMULATION'
        for key in d['descriptor']['resources']:
            if key.startswith('gpu_'):d['descriptor']['resources'][key]=None
        d['descriptor_sha256']=c.descriptor_hash(d['descriptor']);c.validate_message(d)
        d['descriptor']['resources']['gpu_baseline_allocated_bytes']=0;d['descriptor_sha256']=c.descriptor_hash(d['descriptor'])
        with self.assertRaises(c.ContractError):c.validate_message(d)
    def test_installed_reference_and_all_required_pose(self):
        cm=commit();ack={'durable':True,'state':'committed','receiptSeq':4,'revision':1,'observationHash':'sha256:'+'a'*64,'producerIncarnation':'x'}
        self.assertEqual(c.installed_reference(cm['identity'],ack)['receiptSeq'],4)
        del ack['observationHash']
        with self.assertRaises(c.ContractError):c.installed_reference(cm['identity'],ack)
        p=pose();p['pose_proof']['commit_proof_fingerprint']=cm['commit_proof_fingerprint'];p['pose_proof_fingerprint']=c.pose_fingerprint(p['identity'],p['pose_proof']);c.validate_pose_consumed(p,cm)
        p['pose_proof']['required_sink_receipts'][0]['audioEndSample']=2019;p['pose_proof_fingerprint']=c.pose_fingerprint(p['identity'],p['pose_proof'])
        with self.assertRaises(c.ContractError):c.validate_pose_consumed(p,cm)
    def test_wire_content_integrity(self):
        a=message('StageAudio');payload=b'\0\0';a['chunk_sha256']=c.bytes_digest(payload);c.validate_message(a,payload)
        with self.assertRaises(c.ContractError):c.validate_message(a,b'\0')
        v=message('StageVideo');v.update(sample_end=640,payload_sha256=c.bytes_digest(b'h264'));c.validate_message(v,b'h264')
        v['sample_end']=639
        with self.assertRaises(c.ContractError):c.validate_message(v,b'h264')
    def test_profile_and_legacy_watermark(self):
        self.assertEqual(c.negotiation_watermark(-1),0)
        self.assertEqual(c.negotiation_watermark(c.MAX_INTEGER),c.MAX_INTEGER)
        with self.assertRaises(c.ContractError):c.negotiation_watermark(2**63-1)
        with self.assertRaises(c.ContractError):c.profile('staging-segment-8s-1')
        self.assertEqual(c.profile('staging-segment-8s-1',short_gpu_gate=True)['max_source_samples'],128000)
    def test_strict_prebegin_health_no_reservation(self):
        for name in ('StageHealth','StageHealthAck'):
            v=message(name);c.validate_message(v)
            v['identity']=identity()
            with self.assertRaises(c.ContractError):c.validate_message(v)
        with self.assertRaises(c.ContractError):c.validate_message({'type':'Health'})
    def test_reduced_mapping_required(self):
        cm=commit();cm['commit_proof']['output'].update(ratioNumerator=6,ratioDenominator=2)
        cm['commit_proof_fingerprint']=c.commit_fingerprint(cm['identity'],cm['commit_proof'])
        with self.assertRaises(c.ContractError):c.validate_message(cm)
    def test_pose_rounding_absolute_and_optional_not_counted(self):
        p=commit()['commit_proof']
        self.assertEqual(c.pose_prefix(p,100),-1);self.assertEqual(c.pose_prefix(p,2019),-1);self.assertEqual(c.pose_prefix(p,2020),0)
        with self.assertRaises(c.ContractError):c.pose_prefix(p,2021)
    def test_precommit_release_and_unknown(self):
        v=message('StageRelease');v.update(reason='CANCELLED',descriptor_sha256=None,commit_proof_fingerprint=None,pose_proof_fingerprint=None,latest_consumed_sequence=-1);c.validate_message(v)
        v['latest_consumed_sequence']=0
        with self.assertRaises(c.ContractError):c.validate_message(v)
        v=message('StageReleased');v.update(terminal_disposition='UNKNOWN',reusable=True)
        with self.assertRaises(c.ContractError):c.validate_message(v)
    def test_renewal_duplicates_expiry_fence_total_bound(self):
        lease=c.LeaseBudget(begin(),0);r=renewal();ack=lease.renew(r,8000);deadline=lease.deadline
        self.assertEqual(lease.renew(r,8500),ack);self.assertEqual(lease.deadline,deadline)
        bad=copy.deepcopy(r);bad['lease_ms']=8000;bad['renewal_fingerprint']=c.renewal_fingerprint(bad)
        with self.assertRaises(c.ContractError):lease.renew(bad,8500)
        lease.fence()
        with self.assertRaises(c.ContractError):lease.renew(renewal(2),9000)
        lease=c.LeaseBudget(begin(),0)
        with self.assertRaises(c.ContractError):lease.renew(renewal(),9000)
        lease=c.LeaseBudget(begin(),0)
        for seq,now in enumerate(range(8000,60000,8000),1):lease.renew(renewal(seq),now)
        self.assertLessEqual(lease.deadline,60000)
        with self.assertRaises(c.ContractError):lease.renew(renewal(8),60000)
    def test_capture_profile_gate_and_negotiation(self):
        c.validate_capture({'soulxStagingEnabled':False,'soulxStagingLimitsRevision':None,'soulxStagingShortGateSHA256':None})
        with self.assertRaises(c.ContractError):c.validate_capture({'soulxStagingEnabled':True,'soulxStagingLimitsRevision':'staging-segment-8s-1','soulxStagingShortGateSHA256':None})
        a=message('Auth');r=message('GPU_WORKER_READY');r['session_id']=a['session_id'];c.validate_negotiation(a,r)
        a['requested_limits_revision']='staging-segment-8s-1';r['selected_limits']=c.profile(a['requested_limits_revision'],short_gpu_gate=True)
        with self.assertRaises(c.ContractError):c.validate_negotiation(a,r)
        r['profile_gate_ref']='sha256:'+'a'*64;c.validate_negotiation(a,r)
