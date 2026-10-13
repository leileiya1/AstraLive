from pathlib import Path
import json,subprocess,importlib.util,sys,tempfile,hashlib,collections
root=Path('/private/tmp/astralive-f-real-golden-pilot-tcp-9');d=json.loads((root/'media/sql-proof.json').read_text());out=Path(tempfile.mkdtemp(prefix='astralive-a-tcp9-sql-review-',dir='/private/tmp'));module=out/'staging_contract.py'
module.write_bytes(subprocess.check_output(['git','show','4f61a97d8cf5642f0d94b409e91277a000fb5936:gpu_worker/staging_contract.py']))
spec=importlib.util.spec_from_file_location('a_pinned_staging',module);c=importlib.util.module_from_spec(spec);sys.modules[spec.name]=c;spec.loader.exec_module(c)
checks=[]
def check(name,value):checks.append({'name':name,'passed':bool(value)})
sid=d['sessions'][0]['id'];r=d['runs'][0];doc=d['narrations'][0]['document_json'];attempts={a['command_id']:a for a in d['attempts']};obs={(o['command_id'],o['operation']):o for o in d['observations']};rs={(x['command_id'],x['receipt_seq']):x for x in d['receipts']}
check('all owner-scoped rows',all(x.get('session_id')==sid and x.get('tenant_id')==r['tenant_id'] and x.get('user_id')==r['user_id'] for k in ['runs','attempts','commits','receipts','narrations','segments','turns'] for x in d[k]))
summary=[]
for commit in sorted(d['commits'],key=lambda x:x['start_sample']):
 cid=commit['command_id'];a=attempts[cid];dd=a['descriptor_json'];st=dd['stagingDescriptor'];ident=st['identity'];entry=next(x for x in d['commandIdentities'] if x['commandId']==cid);installed=obs[(cid,'COMMIT_INSTALLED')];ack=installed['response_json'];receipt=rs[(cid,ack['receiptSeq'])]
 check(cid+': immutable descriptor hash',c.descriptor_hash(st)==dd['stagingDescriptorHash'])
 check(cid+': H264/sourcePCM hash domains',dd['videoHash']==st['video_stream_sha256'] and dd['contentHash']==st['pcm_sha256'])
 check(cid+': identical SQL commit descriptor',commit['descriptor_json']==dd)
 check(cid+': command identity',all(entry[k]==ident[k] for k in entry if k in ident))
 check(cid+': attempt epoch domains',a['run_epoch']==ident['runEpoch']==1 and a['timeline_epoch']==ident['timelineEpoch'] and a['generation_id']==ident['generationId'] and a['worker_generation_id']==ident['workerGenerationId'] and a['worker_epoch']==ident['workerEpoch'])
 check(cid+': A durable installed exact ref',ack['durable'] is True and ack['state']=='committed' and ack['observationHash']==installed['observation_hash']==receipt['observation_hash'] and ack['producerIncarnation']==receipt['producer_incarnation'])
 check(cid+': fixed sink binding',commit['required_sinks']==doc['plan']['requiredSinks']==dd['requiredSinks'])
 if commit['play_state']=='COMPLETED':
  completed=obs[(cid,'SEGMENT_COMPLETED')];check(cid+': exact completion hash',commit['completion_hash']==completed['observation_hash'])
  receipts=commit['sink_receipts'];check(cid+': required AV contiguous terminal ranges',len(receipts)==len(commit['required_sinks'])*2 and all(x['evidenceType']=='sink_consumed' and x['finalMarker'] is True and x['startSample']==commit['start_sample'] and x['endSample']==commit['end_sample'] and x['identity']==commit['identity_json'] for x in receipts) and {(x['sinkId'],x['media']) for x in receipts}=={(s,m) for s in commit['required_sinks'] for m in ['audio','video']})
 summary.append({'commandId':cid,'lane':ident['lane'],'generationId':ident['generationId'],'workerGenerationId':ident['workerGenerationId'],'timelineEpoch':ident['timelineEpoch'],'startSample':commit['start_sample'],'endSample':commit['end_sample'],'playState':commit['play_state'],'facts':dd['factIds']})
check('committed PTS contiguous across epochs',all(a['endSample']==b['startSample'] for a,b in zip(summary,summary[1:])))
check('semantic cursor has only proved completed authored segments',set(doc['cursor']['completedSegmentIds'])=={s['segment_id'] for s in d['segments'] if s['status']=='COMPLETED' and s['segment_ordinal']<1000000})
check('Stop state sealed and binding released',d['sessions'][0]['status']=='ENDED' and r['status']=='SEALED' and doc['state']=='STOPPED' and doc['stopBarrier'] is True and d['bindingRelease'][0]['released'] is True)
check('Stop terminal control cleanup recorded',any(x['state']=='completed' and x['evidence_type']=='control_cleanup' and x['command_id']=='cmd_ad4b4a286d7d033d24f4e9d2b25e06ad' for x in d['receipts']))
report={'source':'4f61a97d8cf5642f0d94b409e91277a000fb5936','sqlEvidenceSHA256':hashlib.sha256((root/'media/sql-proof.json').read_bytes()).hexdigest(),'checks':checks,'segments':summary,'summary':{'checks':len(checks),'failed':sum(not x['passed'] for x in checks),'installed':len(summary),'completed':sum(x['playState']=='COMPLETED' for x in summary),'unknownStopTail':sum(x['playState']=='UNKNOWN' for x in summary),'spokenBridgeCommits':sum(x['lane']=='RESUME_BRIDGE' for x in summary),'nextOrdinal':doc['cursor']['nextOrdinal'],'completedFacts':doc['cursor']['completedFactIds']},'audienceAudible':False,'realCrashRecovery':'NOT TESTED'}
(out/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps(report['summary']));print('failures',json.dumps([x for x in checks if not x['passed']]));print(out)
