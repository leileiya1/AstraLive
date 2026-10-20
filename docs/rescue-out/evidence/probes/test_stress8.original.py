"""Original RTMP success assertions plus passive ledgers, no timing changes."""
import asyncio,copy,importlib.util,json,os,shutil,time
from pathlib import Path
import pytest
from output_guardian import service
from output_guardian.model import Closed
spec=importlib.util.spec_from_file_location('original_rtmp_case',Path.cwd()/'output_guardian/tests/test_guardian.py')
original=importlib.util.module_from_spec(spec);spec.loader.exec_module(original)
OUT=Path('/tmp/agent4-pr11-final-results/media/stress8-ledgers');OUT.mkdir(exist_ok=True)

@pytest.mark.asyncio
@pytest.mark.parametrize('repeat',range(20))
async def test_original_rtmp_with_passive_diagnostics(rig,monkeypatch,repeat):
    ledger={'repeat':repeat,'snapshots':[],'startMonotonic':time.monotonic(),'physicalAcceptance':False}
    verify=service.verify_combined
    def observed(paths,status,manifest):
        row={'elapsed':time.monotonic()-ledger['startMonotonic'],'observed':copy.deepcopy(status),'expected':copy.deepcopy(manifest),'paths':[str(p)for p in paths]}
        try:
            from output_guardian.observe import decode_recordings
            prefix,samples,frames=decode_recordings(paths)
            row.update(prefix=prefix,prefixSamples=samples,prefixFrames=frames)
        except BaseException as e:row['recordingReadError']=type(e).__name__
        # Still call original verifier unchanged, retain its outcome.
        try:r=verify(paths,status,manifest)
        except BaseException as e:
            row['outcome']=getattr(e,'code',type(e).__name__);raise
        else:row['outcome']='PASS';ledger['evidence']=r;return r
        finally:
            ledger['snapshots'].append(row)
            (OUT/f'ledger-{repeat:02d}.json').write_text(json.dumps(ledger,indent=2)+'\n')
    monkeypatch.setattr(service,'verify_combined',observed)
    ledger['phases']=[]
    def phase(name,**fields):ledger['phases'].append(dict(name=name,elapsed=time.monotonic()-ledger['startMonotonic'],**fields))
    def wrap_async(obj,name,label):
        original=getattr(obj,name)
        async def wrapped(*a,**kw):
            phase(label+'.enter')
            try:r=await original(*a,**kw)
            except BaseException as e:
                phase(label+'.error',type=type(e).__name__,code=getattr(e,'code',None));raise
            else:phase(label+'.return');return r
        monkeypatch.setattr(obj,name,wrapped)
    for obj,name,label in [(rig.guardian.publisher,'abort','publisher.abort'),(rig.guardian.receiver,'abort','receiver.abort'),(rig.guardian.ingest,'isolate','ingest.isolate'),(rig.guardian,'renew','renew'),(rig.guardian,'retire','retire')]:wrap_async(obj,name,label)
    check=rig.guardian.check
    def checked(*a,**kw):
        try:return check(*a,**kw)
        except BaseException as e:
            phase('check.error',type=type(e).__name__,code=getattr(e,'code',None));raise
    monkeypatch.setattr(rig.guardian,'check',checked)
    invalidate=rig.guardian.invalidate
    def invalidated(*a,**kw):phase('invalidate');return invalidate(*a,**kw)
    monkeypatch.setattr(rig.guardian,'invalidate',invalidated)
    try:await original.test_real_rtmp_full_decode_drain_stop(rig)
    except BaseException:
        # Preserve real incoming recorder before dedicated fixture cleans up.
        target=OUT/f'failed-recordings-{repeat:02d}';target.mkdir()
        for i,p in enumerate(sorted(rig.guardian.recording_dir.rglob('*.mp4'))):shutil.copyfile(p,target/f'{i:02d}.mp4')
        ledger['result']='FAIL';raise
    else:ledger['result']='PASS'
    finally:
        ledger['endMonotonic']=time.monotonic()
        ledger['fault']=getattr(rig.guardian,'last_drain_fault',None)
        ledger['controlFault']=getattr(rig.guardian,'last_fault',None)
        ledger['lastStats']=getattr(rig.guardian,'last_drain_stats',None)
        (OUT/f'ledger-{repeat:02d}.json').write_text(json.dumps(ledger,indent=2)+'\n')
