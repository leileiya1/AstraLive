"""Operator-only lab launcher. Requires existing private SSH master and pinned install."""
import pathlib,sys,subprocess,json,os
ROOT=pathlib.Path(__file__).resolve().parents[3]
p=ROOT/'astralive-avatar-lab/streaming/integration'/sys.argv[1];remote='/home/sapiece/AstraLive/experiments/real-avatar/'+p.name
for control,target,port in [('/tmp/astralive-gpu-3080-deploy.sock','root@region-41.seetacloud.com','33260'),('/tmp/astralive-3080-media-school.sock','school-linux','22')]:
    subprocess.run(['ssh','-S',control,'-O','check','-p',port,target],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
if (p/'browser-summary.json').exists() or (p/'driver-process.json').exists():raise RuntimeError('run already launched')
cmd=['ssh','-S','/tmp/astralive-gpu-3080-deploy.sock','-o','BatchMode=yes','-p','33260','root@region-41.seetacloud.com']
c=json.loads(subprocess.check_output(cmd+['cat /root/autodl-tmp/astralive-services/soulx-lite-01/config/worker.json']))
token=subprocess.check_output(cmd+['cat '+c['token_file']]);(p/'.private/worker-token').write_bytes(token);os.chmod(p/'.private/worker-token',0o600)
c['state_dir']=remote+'/telemetry';c['token_file']=remote+'/.private/worker-token';c['management_token_file']=remote+'/.private/token';(p/'.private/log-config.json').write_text(json.dumps(c))
scope={'tenantId':'gpu-acceptance-lab','userId':'operator'}
fixture={'binding':{'profiles':[{'kind':'AVATAR','provider':'soulx','profileId':'avatar-lab','config':{'workerProfileId':'worker-lab','avatarRef':c['avatar_ref']}},{'kind':'GPU_WORKER','provider':'soulx','profileId':'worker-lab','config':{'workerRef':c['worker_ref']}}]},'scope':scope}
(p/'.private/binding-fixture.json').write_text(json.dumps(fixture));(p/'.private/registry.json').write_text(json.dumps({'registryVersion':'1.0','workers':{c['worker_ref']:{'port':int(os.environ.get('SOULX_LAB_WORKER_PORT','17087')),'tokenFile':c['token_file'],'avatarRef':c['avatar_ref'],'assetSHA256':c['asset_sha256'],'allowedScopes':[scope]}}}))
subprocess.run(['ssh','-o','BatchMode=yes','school-linux','mkdir -p '+remote],check=True)
subprocess.run(['rsync','-a','--exclude=chrome-profile','--exclude=__pycache__',str(p)+'/', 'school-linux:'+remote+'/'],check=True)
env={**os.environ,'SOULX_GPU_SSH_TARGET':'root@region-41.seetacloud.com','SOULX_GPU_SSH_PORT':'33260','SOULX_GPU_EVIDENCE_DIR':'/root/autodl-tmp/astralive-services/soulx-lite-01','SOULX_SCHOOL_MONITOR_PATH':remote+'/host_monitor.py','SOULX_FINAL_RUN_DIR':p.name,'SOULX_DUAL_SINK':'true'}
# Existing source-private key remains on the application host only.
subprocess.run([str(ROOT/'runtime/.venv/bin/python'),str(p/'start_stack.py')],env=env,check=True)
reader=f'cd "$HOME/AstraLive"; p="{remote}"; setsid nohup runtime/.venv/bin/python "$p/rtmp_reader.py" > "$p/reader-driver.log" 2>&1 < /dev/null & echo $! > "$p/reader-driver.pid"'
subprocess.run(['ssh','-o','BatchMode=yes','school-linux',reader],check=True)
f=subprocess.Popen([str(ROOT/'gpu_worker/.venv-tests/bin/python'),str(p/'browser_final_acceptance.py')],env=env,stdin=subprocess.DEVNULL,stdout=(p/'driver.log').open('w'),stderr=subprocess.STDOUT,start_new_session=True)
if sys.platform=='darwin':
    guard=subprocess.Popen(['caffeinate','-dims','-w',str(f.pid)],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
    (p/'awake-guard.json').write_text(json.dumps({'pid':guard.pid,'driverPid':f.pid,'temporary':True,'requiresOpenLid':True}))
(p/'launcher.json').write_text(json.dumps({'pid':f.pid,'run':p.name,'detached':True}));print('detached driver',f.pid)
