"""Real loopback SQL/native media. Delay original old media ACK only."""
import asyncio,dataclasses,json,time
from pathlib import Path
import pytest
from output_guardian.model import Closed,clock
OUT=Path('/tmp/agent4-pr11-final-results/stale-real-fresh-output');OUT.mkdir(exist_ok=True)

@pytest.mark.asyncio
@pytest.mark.parametrize('repeat',range(3))
async def test_delayed_old_media_ack_cannot_retire_new_generation(rig,monkeypatch,repeat):
    await rig.activate();g=rig.guardian
    await rig.db.execute("UPDATE dl05_room_outputs SET expires_at=clock_timestamp()+interval '30 seconds' WHERE room_id='room'")
    entered,release=asyncio.Event(),asyncio.Event();original=g.publisher.call;captured=False
    async def delayed(message,*a,**kw):
        nonlocal captured
        result=await original(message,*a,**kw)
        if message.get('op')=='audio' and not captured:
            captured=True;entered.set();await release.wait()
        return result
    monkeypatch.setattr(g.publisher,'call',delayed)
    old=asyncio.create_task(g.media(rig.attempt,{'kind':'audio','sequence':0,'payload':b'\0'*640}))
    record={'repeat':repeat,'realSql':True,'originalMediaAckOnlyDelayed':True,'physicalProductionAcceptance':False}
    try:
        await asyncio.wait_for(entered.wait(),0.5)
        new=dataclasses.replace(rig.attempt,attemptId='new-attempt',utteranceId='new-utterance',commandId='new-command',generation=2)
        # Explicit new-Generation authority fixture, same seven migrated SQL schema.
        await rig.db.execute('      INSERT INTO utterances(id,session_id,source,text,priority,interrupt_policy,trace_id) VALUES (\'new-utterance\',\'session\',\'SCRIPT\',\'test\',1,\'NONE\',\'trace\');\n      INSERT INTO dl05_turns(tenant_id,owner_id,turn_id,run_id,turn_type,priority,state,scheduled_at,input_text,idempotency_key,document)\n       VALUES (\'t\',\'o\',\'new-turn\',\'run\',\'OPERATOR\',1,\'PLAYING\',clock_timestamp(),\'test\',\'new-key\',\'{}\');\n      BEGIN;\n      SET CONSTRAINTS ALL DEFERRED;\n      INSERT INTO dl05_attempts(tenant_id,owner_id,attempt_id,run_id,turn_id,session_id,run_epoch,utterance_id,command_id,attempt_number,executor_incarnation,last_checkpoint,required_sinks,document)\n       VALUES (\'t\',\'o\',\'new-attempt\',\'run\',\'new-turn\',\'session\',1,\'new-utterance\',\'new-command\',1,\'producer\',\'PLAYING\',\'["rtmp"]\',\'{}\');\n      INSERT INTO dl05_outbox(tenant_id,owner_id,intent_id,run_id,session_id,utterance_id,command_id,attempt_id,turn_id,idempotency_key,run_epoch,operation,request_hash,envelope,status)\n       VALUES (\'t\',\'o\',\'new-intent\',\'run\',\'session\',\'new-utterance\',\'new-command\',\'new-attempt\',\'new-turn\',\'new-key\',1,\'EXECUTE_TURN\',repeat(\'a\',64),jsonb_build_object(\'contractRevision\',\'durable-live-1\',\'tenantId\',\'t\',\'ownerId\',\'o\',\'runId\',\'run\',\'commandId\',\'new-command\',\'intentId\',\'new-intent\',\'sessionId\',\'session\',\'operation\',\'EXECUTE_TURN\',\'requestHash\',repeat(\'a\',64),\'runEpoch\',1,\'attemptId\',\'new-attempt\',\'turnId\',\'new-turn\',\'utteranceId\',\'new-utterance\'),\'ACCEPTED\');\n      INSERT INTO dl05_runtime_inbox(tenant_id,owner_id,command_id,run_id,attempt_id,run_epoch,request_hash,status,receipt_id,producer_incarnation,started_at)\n       VALUES (\'t\',\'o\',\'new-command\',\'run\',\'new-attempt\',1,repeat(\'a\',64),\'STARTED\',\'new-receipt\',\'producer\',clock_timestamp());\n      UPDATE dl05_run_slots SET active_attempt_id=\'new-attempt\' WHERE run_id=\'run\';\n      COMMIT;')
        permit=await rig.permit();result=await g.bind(new,permit)
        assert result['state']=='AUTHORIZED'
        life,barrier,child=g._life,g.barrier,g.publisher.process
        record.update(newAuthorized=True,newGeneration=g.generation,newBarrierBefore=barrier,newPublisherPid=child.pid,newPublisherAliveBefore=child.poll() is None,remainingMsBefore=1000*min(g.right.deadline-clock(),g.right.monotonic_deadline-time.monotonic()))
        record['outputRemainingMsBefore']=float(await rig.db.fetchval("SELECT extract(epoch FROM (expires_at-clock_timestamp()))*1000 FROM dl05_room_outputs WHERE room_id='room'"))
        release.set()
        with pytest.raises(Closed):await old
        record.update(newBarrierAfter=g.barrier,newLifePhaseAfter=life.phase,newRightAfter=g.right is not None,newPublisherAliveAfter=child.poll() is None,newPublisherPresentAfter=g.publisher.process is not None,stopRequested=bool(g.stopped))
        assert g._life is life and g.barrier==barrier and g.right is not None and life.phase=='ACTIVE' and child.poll() is None,'Stale old Media ACK retired a newly authorized real Generation/Publisher'
    finally:
        release.set();await asyncio.gather(old,return_exceptions=True)
        (OUT/f'case-{repeat}.json').write_text(json.dumps(record,indent=2)+'\n')
