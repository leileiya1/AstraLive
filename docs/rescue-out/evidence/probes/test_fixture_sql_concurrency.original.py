"""New lifecycle tests' shared DB setup can collide with renewal fixture writes."""
import asyncio,json
from pathlib import Path
import pytest

@pytest.mark.asyncio
@pytest.mark.parametrize('repeat',range(3))
async def test_fixture_permit_writes_need_separate_connection_or_serialization(rig,repeat):
    await rig.activate()
    results=await asyncio.gather(rig.permit(),rig.permit(),return_exceptions=True)
    errors=[type(x).__name__ for x in results if isinstance(x,BaseException)]
    out=Path('/tmp/agent4-pr11-final-results/fixture-concurrency');out.mkdir(exist_ok=True)
    (out/f'case-{repeat}.json').write_text(json.dumps(dict(errors=errors,realPrivatePostgres=True,fixtureOnly=True,productionAuthorityUsesItsOwnLock=True),indent=2)+'\n')
    assert not errors,'Shared test-only Rig.db used concurrently without serialization'
