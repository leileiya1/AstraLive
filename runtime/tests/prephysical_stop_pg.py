"""Actual Go journal/Binding DELETE HTTP + PG, captured provider packet fixture.
No GPU/LLM/TTS/media instance is created in the exact configure-failure phase.
"""
import asyncio
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

from app.config import Settings
from app.durable_events import DurableEventPublisher
from app.durability_client import DurabilityClient, DurableCommands, JournalError
from app.models import CreateSession
from app.providers import MockLLMProvider, MockTTSProvider, MockAvatarEngine, MockMediaOutput
from app.session_binding import BindingClient, BoundSessionManager
from app.soulx_staging import StagingFailure
from app.staging_settings import StagingSettings
from test_session_binding import packet


class CapturedClient(BindingClient):
    async def resolve(self,sid):
        data=packet();data["binding"]["bindingId"]="binding"
        base=data["binding"]["profiles"][0]
        data["binding"]["profiles"] += [
            {**base,"profileId":"tts","kind":"TTS","provider":"xiaoya","config":{"voiceId":"xiao_ya","speed":1,"modelRef":"xiaoya-default"}},
            {**base,"profileId":"avatar","kind":"AVATAR","provider":"soulx","config":{"avatarRef":"captured-fixture","workerProfileId":"gpu"}}]
        return data
    # Inherited release executes actual authenticated Go HTTP + SQL transaction.


async def main():
    base,journal_file,binding_file,command_file,scenario=sys.argv[1:]
    begin=json.loads(Path(command_file).read_text())
    journal=DurabilityClient(base,journal_file)
    directory=tempfile.TemporaryDirectory()
    publisher=DurableEventPublisher(journal,directory.name)
    manager=BoundSessionManager(Settings(),publisher,MockLLMProvider,MockTTSProvider,MockAvatarEngine,MockMediaOutput,
        binding_client=CapturedClient(base,binding_file))
    manager.staging_settings=StagingSettings(True,"staging-short-1")
    commands=DurableCommands(journal,publisher,manager)
    def unexpected_media():raise AssertionError("media factory must not be entered")
    manager.media_factory=unexpected_media
    env={"GPU_WORKER_INFERENCE_REGISTRY_FILE":"captured-fixture-not-read","SESSION_PROVIDER_STATE_DIR":directory.name,"TTS_MODEL_DIR":"never-constructed"}
    try:
        with patch.dict(os.environ,env),patch("gpu_worker.client.resolve_binding",return_value={"port":1,"assetSHA256":"a"*64,"tokenFile":"never-read"}):
            try:await commands.execute(begin)
            except StagingFailure:pass
            else:raise AssertionError("configuration failure not exercised")
        assert not manager.sessions
        marker=manager.failed_create_cleanup["s"]
        assert marker["bindingReleaseACK"]==(scenario=="success")
        response=await journal.http.post(base+"/fixture/admit-stop",headers={"Authorization":"Bearer "+Path(journal_file).read_text().strip()})
        assert response.status_code==200,"actual Go Stop admission failed"
        stop=response.json()
        try:
            await commands.execute(stop)
            assert scenario=="success","missing Binding ACK allowed completion"
        except JournalError:
            assert scenario=="delete_failure"
        if scenario=="success":
            assert not manager.failed_create_cleanup
            assert await publisher.flush_once()
            assert publisher.db.execute("SELECT count(*) FROM pending").fetchone()[0]==0
        else:
            assert manager.failed_create_cleanup["s"]["bindingReleaseACK"] is False
            assert publisher.db.execute("SELECT count(*) FROM pending").fetchone()[0]==0
        # Original BEGIN is also retired by Stop barrier/released binding; the
        # real journal may fence it before returning prior STARTED state.
        try:
            assert not (await commands.execute(begin))["execute"]
        except JournalError as exc:
            assert exc.code in {"LEASE_LOST","RUN_SEALED"}
        assert not (await commands.execute(stop))["execute"]
        print(json.dumps({"scope":"REAL_GO_HTTP_POSTGRES_EXACT_PREPHYSICAL_CAPTURED_PROVIDER_FIXTURE",
            "scenario":scenario,"bindingReleaseACK":scenario=="success","gpu":"NOT_TESTED",
            "originalBeginReplay":False,"stagingMediaCreated":False}))
    finally:
        await publisher.close();await journal.close();directory.cleanup()


if __name__=="__main__":asyncio.run(main())
