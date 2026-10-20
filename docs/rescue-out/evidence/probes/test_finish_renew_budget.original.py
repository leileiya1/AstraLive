"""Schedule legitimate renewed control during actual owned Publisher teardown.
No wire/PTS/Credit/expiry/tolerance changes; no production modifications.
"""
import asyncio,importlib.util,json,time
from pathlib import Path
import pytest
from output_guardian.model import Closed,clock
from output_guardian import service
spec=importlib.util.spec_from_file_location('original',Path.cwd()/'output_guardian/tests/test_guardian.py');original=importlib.util.module_from_spec(spec);spec.loader.exec_module(original)
OUT=Path('/tmp/agent4-pr11-final-results/media/test_finish_renew_budget-ledgers');OUT.mkdir(exist_ok=True)

@pytest.mark.asyncio
@pytest.mark.parametrize('repeat',range(3))
async def test_valid_renew_during_normal_finish_must_not_destroy_proven_drain(rig,monkeypatch,repeat):
    await rig.activate(); renewal=asyncio.create_task(rig.renew_forever())
    paused,released=asyncio.Event(),asyncio.Event();proof=[];injected=False
    verify=service.verify_combined
    def verified(*a):
        result=verify(*a);proof.append(result);return result
    monkeypatch.setattr(service,'verify_combined',verified)
    abort=rig.guardian.publisher.abort
    async def paused_abort(*a,**kw):
        nonlocal injected
        result=await abort(*a,**kw)
        if proof and not injected:
            injected=True;paused.set();await asyncio.wait_for(released.wait(),0.5)
        return result
    monkeypatch.setattr(rig.guardian.publisher,'abort',paused_abort)
    record={'repeat':repeat,'realSql':True,'actualOwnedMediaProcesses':True,'physicalProductionAcceptance':False,'stopRequested':False,'grantLifetimeChanged':False}
    finish=None
    try:
        await original.synthetic(rig,count=100)
        finish=asyncio.create_task(rig.guardian.finish(rig.attempt))
        await asyncio.wait_for(paused.wait(),0.8)
        record['trustedDrainPassedBeforeRenew']=bool(proof)
        record['publisherAtRenew']=rig.guardian.publisher.process is None
        permit=await rig.permit()
        old_right=rig.guardian.right
        record['oldRightRemainingMsBeforeRenew']=1000*min(old_right.deadline-clock(),old_right.monotonic_deadline-time.monotonic())
        record['newSqlPermitRemainingMs']=float(await rig.db.fetchval("SELECT extract(epoch from (expires_at-clock_timestamp()))*1000 FROM dl05_output_permits WHERE permit_id=$1",permit))
        record['run']=dict(await rig.db.fetchrow("SELECT status,desired_state FROM dl05_runs WHERE run_id='run'"))
        try:await rig.guardian.renew(rig.attempt,permit)
        except Closed as e:record['renewError']=e.code
        else:record['renewResult']='AUTHORIZED'
        record['oldRightRemainingMsAfterRenew']=1000*min(old_right.deadline-clock(),old_right.monotonic_deadline-time.monotonic())
        released.set()
        try:result=await finish
        except Closed as e:
            record['finishError']=e.code;raise
        assert result['state']=='LOCAL_MEDIA_DRAINED'
    finally:
        released.set();renewal.cancel();await asyncio.gather(renewal,return_exceptions=True)
        if finish is not None:await asyncio.gather(finish,return_exceptions=True)
        record['lastDrainDiagnostic']=getattr(rig.guardian,'last_drain_fault',None)
        record['observedProofCount']=len(proof)
        (OUT/f'case-{repeat}.json').write_text(json.dumps(record,indent=2)+'\n')
