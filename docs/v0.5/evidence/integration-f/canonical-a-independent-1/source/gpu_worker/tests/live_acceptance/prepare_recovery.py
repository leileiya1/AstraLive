"""Explicit fault injection in a separate acceptance session, never in the healthy soak."""
import pathlib,sys
root=pathlib.Path(__file__).resolve().parents[3]
run=sys.argv[1] if len(sys.argv)>1 else 'soulx-product-3080-recovery-20261010'
mode=sys.argv[2] if len(sys.argv)>2 else 'crash'
if not run.startswith('soulx-product-3080-') or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789-' for c in run):raise ValueError('invalid owned run')
if mode not in {'crash','network'}:raise ValueError('invalid fault mode')
p=root/'astralive-avatar-lab/streaming/integration'/run
if (p/'launcher.json').exists():raise RuntimeError('cannot modify a launched run')
f=p/'runtime-experiment/app/main.py';s=f.read_text();s=s.replace('"workerEpoch":avatar.link.epoch if avatar.link else None,','"workerEpoch":avatar.link.epoch if avatar.link else None,"recoveryReady":bool(avatar.recovery_candidate),"recoveryCandidateEpoch":avatar.recovery_candidate.epoch if avatar.recovery_candidate else None,');f.write_text(s)
f=p/'browser_final_acceptance.html';s=f.read_text().replace("if(expected?.degraded)monitorError='GPU degraded during formal session'","/* controlled degradation is the subject of this separate test */")
a=s.index(' const passed=new Set();');b=s.index('\n}catch(e)',a)
s=s[:a]+''' const oldEpoch=expected.workerEpoch;let baseline=await stats();let faultUtterance=await utterance('请用八句话解释怎样搭配舒适的日常衣服。');await until(()=>expected?.speaking);await sleep(1000);const faultStart=performance.now()/1000;let fault=await api('/inject-owned-worker-crash',{});log('OwnedWorkerCrashInjected',fault);
 await until(()=>expected?.degraded,30000);log('DegradationDetected',{delaySeconds:performance.now()/1000-faultStart,sessionId:sid,workerEpoch:expected.workerEpoch});await done(faultUtterance);
 await until(async()=>{await diag();return expected?.recoveryReady},180000);const recoveredCandidate=expected.recoveryCandidateEpoch;const reconnectTime=performance.now()/1000-faultStart;if(recoveredCandidate===oldEpoch)throw Error('epoch not replaced after crash');
 await done(await utterance('请用两句话介绍恢复后的数字人直播。','FORCE',100));await until(async()=>{await diag();return !expected.degraded&&expected.workerEpoch===recoveredCandidate&&expected.lastFrame?.source==='GPU_INFERENCE'},45000);
 await sleep(3000);let final=await stats();let lightweight=batch.filter(x=>x.event==='BrowserFrameDisplayed'&&x.source==='LIGHTWEIGHT_AVATAR').length;
 const evidence=await api('/recovery-evidence');if(evidence.lightweightDisplayed<1)throw Error('no actual displayed lightweight frame');if(final.connection!=='connected'||expected.state!=='LIVE')throw Error('business session or peer did not survive');if(final.audioPackets<=baseline.audioPackets||final.videoFrames<=baseline.videoFrames)throw Error('media counters did not advance');
 result={...result,status:'RECOVERY_COMPLETED',actualDurationSeconds:performance.now()/1000-begin,oldEpoch,recoveredEpoch:expected.workerEpoch,reconnectSeconds:reconnectTime,lightweightDisplayed:evidence.lightweightDisplayed,finalStats:final,formalForceCount:forceCount-1,displayedFrames:displayed,gpuDisplayedFrames:gpuDisplayed,sessionStayedLive:true,samePeer:true};
''' + s[b:]
if mode=='network':
 s=s.replace("log('OwnedWorkerCrashInjected',fault)","log('OwnedInferenceTunnelDisconnected',fault)")
 s=s.replace('await done(faultUtterance);','await done(faultUtterance);await api(\'/restore-owned-worker-tunnel\',{});')
 s=s.replace("if(recoveredCandidate===oldEpoch)throw Error('epoch not replaced after crash')","if(recoveredCandidate!==oldEpoch)throw Error('worker unexpectedly restarted during tunnel fault')")
 s=s.replace("status:'RECOVERY_COMPLETED'","status:'NETWORK_RECOVERY_COMPLETED'")
f.write_text(s)
f=p/'browser_final_acceptance.py';s=f.read_text();needle="  elif self.path=='/monitor':";s=s.replace(needle,"  elif self.path=='/recovery-evidence':\n   rows=[json.loads(x) for x in (OUT/'browser-events.jsonl').read_text().splitlines()]\n   self.send(200,json.dumps({'lightweightDisplayed':sum(x['event']=='BrowserFrameDisplayed' and x.get('source')=='LIGHTWEIGHT_AVATAR' for x in rows)}).encode())\n"+needle)
needle="  elif self.path=='/ready':";branch="""  elif self.path=='/inject-owned-worker-crash':
   command=\"/root/miniconda3/bin/python /root/autodl-tmp/astralive-owned-crash-20261010.py\"
   r=subprocess.run(['ssh','-S','/tmp/astralive-gpu-3080-deploy.sock','-o','BatchMode=yes','-p',GPU_PORT,GPU_TARGET,command],capture_output=True,text=True,timeout=10)
   if r.returncode:self.send(500,json.dumps({'error':'owned crash rejected'}).encode())
   else:
    j=json.loads(r.stdout);dump('fault-injection.json',j);self.send(200,json.dumps(j).encode())
"""
if mode=='network':
 branch="""  elif self.path=='/inject-owned-worker-crash':
   if (OUT/'fault-injection.json').exists():self.send(409,b'{"error":"owned fault already injected"}');return
   command=['ssh','-S','/tmp/astralive-3080-fault-tunnel.sock','-O','exit','school-linux']
   r=subprocess.run(command,capture_output=True,text=True,timeout=10)
   if r.returncode:self.send(500,json.dumps({'error':'owned tunnel disconnect rejected'}).encode())
   else:
    j={'injected':True,'kind':'owned-inference-tunnel','workerPort':17089};dump('fault-injection.json',j);self.send(200,json.dumps(j).encode())
  elif self.path=='/restore-owned-worker-tunnel':
   if not (OUT/'fault-injection.json').exists():self.send(409,b'{"error":"no owned fault"}');return
   command=['ssh','-M','-S','/tmp/astralive-3080-fault-tunnel.sock','-o','BatchMode=yes','-o','ControlPersist=600','-o','StrictHostKeyChecking=yes','-o','ExitOnForwardFailure=yes','-o','ServerAliveInterval=15','-o','ServerAliveCountMax=3','-fN','-R','127.0.0.1:17089:127.0.0.1:17087','school-linux']
   r=subprocess.run(command,capture_output=True,text=True,timeout=15)
   if r.returncode:self.send(500,b'{"error":"owned tunnel restore failed"}')
   else:dump('tunnel-restored.json',{'restored':True});self.send(200,b'{"restored":true}')
"""
s=s.replace(needle,branch+needle);f.write_text(s)
print('Recovery-only harness prepared: '+mode+'; healthy soak unchanged')
