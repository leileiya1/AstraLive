"""Production bound factory/adapter and durable SQLite event spool, CPU only.

Binding release/server authority/providers are explicit doubles. These tests
never prove real GPU/Chrome/RTMP or PostgreSQL authority acceptance.
"""
import asyncio
import copy
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.durability_client import DurableCommands, JournalError, fingerprint
from app.durable_events import DurableEventPublisher
from app.soulx_staging import StagingAvatarEngine, StagingFailure
import test_staging_binding_lifecycle as binding_setup
from test_staging_tcp import SoftwareWorkerWire


class CommandJournal:
    incarnation="runtime_prephysical_test"
    def __init__(self):self.started=set();self.receipts=[];self.events=[];self.fail_receipt=False
    async def accept(self,command):
        return {"execute":command["commandId"] not in self.started,"executionState":"UNKNOWN" if command["commandId"] in self.started else "ACCEPTED","run":{"leaseToken":1,"remainingMs":10000}}
    async def start(self,command,token):
        self.started.add(command["commandId"])
        return {"execute":True,"executionState":"STARTED","attemptId":"attempt-"+command["commandId"],"run":{"remainingMs":10000}}
    async def request(self,method,suffix,body):
        if suffix=="/receipts":
            if self.fail_receipt:raise JournalError()
            self.receipts.append(copy.deepcopy(body))
        elif suffix=="/events":self.events.append(copy.deepcopy(body))
        return {"stored":True}


# Reuse setup only, not inherited lifecycle test methods.
class PrephysicalStopTests(unittest.IsolatedAsyncioTestCase):
    setup_manager=binding_setup.BoundStagingLifecycleTests.setup_manager

    async def setup_commands(self,wire=None):
        manager,client,oldpub,request,wire=await self.setup_manager(wire)
        directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup)
        journal=CommandJournal();publisher=DurableEventPublisher(journal,directory.name)
        self.addAsyncCleanup(publisher.close)
        manager.publisher=publisher
        begin={"schemaVersion":"0.5","commandId":"begin","sessionId":"s","runEpoch":1,"traceId":request.traceId,"commandType":"BEGIN_RUN","commandSeq":1,"payload":{"expectedPreviousEpoch":0,"featureFlags":manager.staging_settings.capture(),"createSession":request.model_dump()}}
        stop={**begin,"commandId":"stop","traceId":"trace-stop","commandType":"STOP_SESSION","commandSeq":2,"payload":{}}
        commands=DurableCommands(journal,publisher,manager)
        return manager,client,journal,publisher,request,wire,begin,stop,commands

    async def fail_configuration(self,client_fail=False):
        manager,client,journal,publisher,request,wire,begin,stop,commands=await self.setup_commands()
        client.fail_release=client_fail
        begin["payload"]["createSession"]["config"]["fps"]=30
        begin["requestFingerprint"]=fingerprint(begin);stop["requestFingerprint"]=fingerprint(stop)
        with self.assertRaises(StagingFailure):await commands.execute(begin)
        self.assertIsNone(wire.socket)
        self.assertFalse(manager.sessions)
        self.assertIn("begin",journal.started)
        self.assertFalse(journal.receipts)
        return manager,client,journal,publisher,wire,begin,stop,commands

    async def test_exact_prephysical_failed_create_stop_real_spool_and_ack_order(self):
        manager,client,journal,publisher,wire,begin,stop,commands=await self.fail_configuration()
        marker=copy.deepcopy(manager.failed_create_cleanup["s"])
        self.assertTrue(marker["bindingReleaseACK"]);self.assertEqual(client.released,["s"])
        await commands.execute(stop)
        self.assertFalse(manager.failed_create_cleanup)
        self.assertEqual([(x["commandId"],x["state"],x["evidenceType"]) for x in journal.receipts],[("stop","completed","control_cleanup")])
        self.assertEqual(publisher.db.execute("SELECT count(*) FROM pending").fetchone()[0],1)
        await publisher.flush_once()
        self.assertEqual(journal.events[0]["eventType"],"SESSION_ENDED")
        self.assertEqual(journal.events[0]["commandId"],"stop")
        self.assertTrue(commands.runs["s"]["sealed"])
        await commands.execute(begin);await commands.execute(stop)
        self.assertEqual(len(journal.receipts),1)
        self.assertEqual(len(journal.events),1)
        self.assertIsNone(wire.socket)  # No BEGIN replay/native generation.

    async def test_no_binding_ack_retains_unknown_without_ended_or_receipt(self):
        manager,client,journal,publisher,wire,begin,stop,commands=await self.fail_configuration(client_fail=True)
        self.assertFalse(manager.failed_create_cleanup["s"]["bindingReleaseACK"])
        with self.assertRaises(JournalError):await commands.execute(stop)
        self.assertIn("stop",journal.started);self.assertFalse(journal.receipts)
        self.assertEqual(publisher.db.execute("SELECT count(*) FROM pending").fetchone()[0],0)
        client.fail_release=False

    async def test_wrong_original_identity_incarnation_epoch_and_reservations_unknown(self):
        for mutation in ("incarnation","epoch","beginCommand","beginHash","noRun","bound","pending","ackRequired","releasing","restart"):
            with self.subTest(mutation=mutation):
                manager,client,journal,publisher,wire,begin,stop,commands=await self.fail_configuration()
                if mutation=="incarnation":journal.incarnation="different_runtime"
                elif mutation=="epoch":manager.failed_create_cleanup["s"]["runEpoch"]=2
                elif mutation=="beginCommand":publisher.run_commands[("s","BEGIN_RUN")]["commandId"]="different_begin"
                elif mutation=="beginHash":publisher.run_commands[("s","BEGIN_RUN")]["requestFingerprint"]="sha256:"+"b"*64
                elif mutation=="noRun":commands.runs.clear()
                elif mutation=="bound":manager.bound["s"]={"bindingId":"unproved"}
                elif mutation=="pending":manager.release_pending.add("s")
                elif mutation=="ackRequired":manager.release_requires_ack.add("s")
                elif mutation=="releasing":manager.releasing.add("s")
                elif mutation=="restart":manager.failed_create_cleanup.clear()
                with self.assertRaises(JournalError):await commands.execute(stop)
                self.assertFalse(journal.receipts)
                self.assertEqual(publisher.db.execute("SELECT count(*) FROM pending").fetchone()[0],0)
                manager.bound.clear();manager.release_pending.clear();manager.release_requires_ack.clear();manager.releasing.clear()

    async def test_receipt_outage_does_not_consume_marker_or_retry_started_stop(self):
        manager,client,journal,publisher,wire,begin,stop,commands=await self.fail_configuration()
        journal.fail_receipt=True
        with self.assertRaises(JournalError):await commands.execute(stop)
        self.assertIn("s",manager.failed_create_cleanup)
        self.assertEqual(publisher.db.execute("SELECT count(*) FROM pending").fetchone()[0],1)
        journal.fail_receipt=False
        self.assertFalse((await commands.execute(stop))["execute"])
        self.assertFalse(journal.receipts);self.assertIn("s",manager.failed_create_cleanup)

    async def test_any_prepare_or_connection_attempt_excludes_configuration_proof(self):
        original=StagingAvatarEngine.configure_session
        for marker in ("preparation_started","connection_started"):
            with self.subTest(marker=marker):
                def touched(avatar,config):
                    if marker=="preparation_started":avatar.preparation_started=True
                    else:avatar.link.connection_started=True
                    return original(avatar,config)
                with patch.object(StagingAvatarEngine,"configure_session",touched):
                    manager,client,journal,publisher,wire,begin,stop,commands=await self.fail_configuration()
                self.assertFalse(manager.failed_create_cleanup)
                with self.assertRaises(JournalError):await commands.execute(stop)
                self.assertFalse(journal.receipts)

    async def test_postconfigure_media_factory_failure_and_prepare_failure_unknown(self):
        for phase in ("mediaFactory","prepare"):
            with self.subTest(phase=phase):
                manager,client,journal,publisher,request,wire,begin,stop,commands=await self.setup_commands(SoftwareWorkerWire(simulation=True))
                if phase=="mediaFactory":
                    def failed_media():raise RuntimeError("software media side effect failure")
                    manager.media_factory=failed_media
                begin["requestFingerprint"]=fingerprint(begin);stop["requestFingerprint"]=fingerprint(stop)
                if phase=="mediaFactory":
                    with self.assertRaises(RuntimeError):await commands.execute(begin)
                else:
                    await commands.execute(begin)
                    # BEGIN admission control receipt is not audible completion.
                    journal.receipts.clear()
                    for _ in range(100):
                        if client.released:break
                        await asyncio.sleep(.01)
                self.assertFalse(manager.failed_create_cleanup)
                with self.assertRaises(JournalError):await commands.execute(stop)
                self.assertFalse(journal.receipts)

    async def test_flags_off_and_legacy_fence_only_preserve_existing_control_receipt(self):
        for captured,deployment in ((False,True),(False,False),(None,False)):
            with self.subTest(captured=captured,deployment=deployment):
                manager,client,journal,publisher,request,wire,begin,stop,commands=await self.setup_commands()
                manager.staging_settings=SimpleNamespace(enabled=deployment)
                if captured is None:begin["payload"]={"fenceOnly":True}
                else:begin["payload"]["featureFlags"]["soulxStagingEnabled"]=captured
                publisher.bind(begin)
                stop["requestFingerprint"]=fingerprint(stop)
                await commands.execute(stop)
                self.assertEqual(len(journal.receipts),1)
                self.assertEqual(publisher.db.execute("SELECT count(*) FROM pending").fetchone()[0],0)
                self.assertFalse(manager.failed_create_cleanup)

    async def test_enabled_deployment_unknown_capture_after_restart_remains_unknown(self):
        manager,client,journal,publisher,request,wire,begin,stop,commands=await self.setup_commands()
        stop["requestFingerprint"]=fingerprint(stop)
        with self.assertRaises(JournalError):await commands.execute(stop)
        self.assertFalse(journal.receipts)
        self.assertFalse(publisher.run_commands.get(("s","BEGIN_RUN")))
        self.assertEqual(publisher.db.execute("SELECT count(*) FROM pending").fetchone()[0],0)
