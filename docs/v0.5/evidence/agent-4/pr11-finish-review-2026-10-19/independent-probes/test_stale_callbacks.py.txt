"""Independent stale-life probes using explicit local mock transport only."""
import asyncio,dataclasses
import pytest
from output_guardian.model import Closed
from output_guardian.tests.lifecycle.test_finish_renew import local

@pytest.mark.asyncio
async def test_old_media_failure_cannot_retire_new_generation(local):
    g,a=local.g,local.a
    entered,release=asyncio.Event(),asyncio.Event()
    original=g.publisher.call
    async def delayed(message,**kwargs):
        if message['op']=='audio':
            entered.set();await release.wait();raise Closed('MEDIA_DELIVERY_FAILED')
        return await original(message,**kwargs)
    g.publisher.call=delayed
    media=asyncio.create_task(g.media(a,{'kind':'audio','sequence':0,'payload':b'\0'*640}))
    await entered.wait()
    replacement=dataclasses.replace(a,attemptId='new-attempt',utteranceId='new-utterance',generation=2,commandId='new-command')
    try:
        result=await g.bind(replacement,'new-permit')
        assert result['state']=='AUTHORIZED'
        life,barrier=g._life,g.barrier
        release.set()
        with pytest.raises(Closed):await media
        assert g._life is life and g.barrier==barrier and g.right is not None and g._life.phase=='ACTIVE', 'Old media callback retired newly authorized Generation'
    finally:
        release.set();await asyncio.gather(media,return_exceptions=True)
