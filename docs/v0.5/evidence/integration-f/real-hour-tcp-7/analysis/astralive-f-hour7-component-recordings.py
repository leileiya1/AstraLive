import hashlib,json,sys,time
from pathlib import Path
sys.path.insert(0,str(Path('/Users/sapiece/innovationProject/AstraLive-agent-f/integration/v0.5')))
from real_golden_audit import Auditor
root=Path('/private/tmp/astralive-f-real-hour-tcp-7')
output=Path('/private/tmp/astralive-f-hour7-component-av.json')
gate=json.loads((root/'result.json').read_text())
assert gate['status']!='RUNNING'
a=Auditor(root,Path('/Users/sapiece/innovationProject/AstraLive-agent-f/integration/v0.5/fixtures/real_golden_hour.json'),True)
a.index_path=root/'media/staged-observer/refs.json'
a.index=json.loads(a.index_path.read_text())
a.commits=json.loads((root/'media/sql-proof.json').read_text())['commits']
a.refs={r['identity']['attemptId']:json.loads((a.index_path.parent/r['reference']).read_text()) for r in a.index}
a.report.update(scope='FAILED_GATE_CLOSED_RECORDING_COMPONENT_ONLY',originalGateStatus=gate['status'],originalSource=gate['source'],overallAcceptance='UNCHANGED_FAIL',humanNaturalness='NOT_TESTED',audienceAudible=False)
a.check('same_recording_actual_waveform_and_barcode',a.correlate_recordings)
a.report['toolSources']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path(__file__),Path('/Users/sapiece/innovationProject/AstraLive-agent-f/integration/v0.5/real_golden_audit.py'),Path('/Users/sapiece/innovationProject/AstraLive-agent-f/integration/v0.5/observer_audit.py')]}
output.write_text(json.dumps(a.report,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'checks':a.report['checks'],'recordings':[{k:r[k] for k in ['recording','statusCounts','speechPrefixOnsetAbsoluteAudioVideoMs']} for r in a.report.get('recordedAV',[])]}),flush=True)
