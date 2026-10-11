import asyncio
import json
import tempfile
import time
import unittest
from pathlib import Path
from app.durability_client import canonical, fingerprint, JournalError, DurableCommands
from app.durable_events import DurableEventPublisher
from app.events import envelope


class Journal:
    def __init__(self):
        self.incarnation = "runtime_test"
        self.events = []
        self.offline = False
        self.receipt = {"accepted": True, "operationId": "op", "execute": True, "executionState": "ACCEPTED", "run": {"leaseToken": 1, "remainingMs": 10000}}
        self.started = False

    async def request(self, method, suffix, body=None):
        if self.offline:
            raise JournalError()
        if suffix == "/events":
            self.events.append(body)
        return {"stored": True}

    async def accept(self, command):
        if self.offline:
            raise JournalError()
        return dict(self.receipt, execute=not self.started)

    async def start(self, command, token):
        if self.started:
            return dict(self.receipt, execute=False)
        self.started = True
        return dict(self.receipt, executionState="STARTED")

    async def lookup(self, sid, cid):
        return {"executionState": "STARTED", "executorIncarnation": "previous_runtime"}


def command():
    c = {"schemaVersion": "0.5", "commandId": "cmd", "sessionId": "s", "runEpoch": 1, "traceId": "t", "commandType": "SPEAK", "commandSeq": 1, "createdAt": "2026-10-11T00:00:00Z", "idempotencyKey": "u", "payload": {"utteranceId": "u", "commandId": "legacy", "traceId": "t", "text": "你好", "priority": 40, "interruptPolicy": "NONE", "source": "OPERATOR", "voice": {"voiceId": "v"}}}
    c["requestFingerprint"] = fingerprint(c)
    return c


class DurableTests(unittest.IsolatedAsyncioTestCase):
    async def test_spool_survives_restart_and_backend_outage(self):
        j = Journal()
        with tempfile.TemporaryDirectory() as directory:
            p = DurableEventPublisher(j, directory)
            p.bind(command())
            event = envelope("UTTERANCE_COMPLETED", "s", "t", "u")
            await p.publish(event)
            j.offline = True
            self.assertFalse(await p.flush_once())
            await p.close()
            # New publisher has no in-memory command mapping; pending envelope already carries durable identity.
            p = DurableEventPublisher(j, directory)
            self.assertEqual(p.db.execute("SELECT count(*) FROM pending").fetchone()[0], 1)
            j.offline = False
            p.db.execute("UPDATE pending SET next_at=0")
            p.db.commit()
            self.assertTrue(await p.flush_once())
            self.assertEqual(j.events[0]["eventId"], event["eventId"])
            self.assertEqual(p.db.execute("SELECT count(*) FROM pending").fetchone()[0], 0)
            await p.close()

    async def test_duplicate_durable_accept_never_reexecutes(self):
        j = Journal()
        class Manager:
            def __init__(self):
                self.sessions = {}
                self.count = 0
            async def speak(self, sid, item):
                self.count += 1
        class Publisher:
            def bind(self, c, receipt=None):
                pass
        m = Manager()
        commands = DurableCommands(j, Publisher(), m)
        commands.runs["s"] = {"epoch": 1, "deadline": time.monotonic() + 10, "sealed": False}
        await commands.execute(command())
        await commands.execute(command())
        self.assertEqual(m.count, 1)
        state = await commands.receipt("s", "cmd")
        self.assertEqual(state["executionState"], "UNKNOWN")

    async def test_journal_failure_prevents_effect_and_stale_lease(self):
        j = Journal()
        class Manager:
            sessions = {}
            async def speak(self, sid, item):
                raise AssertionError("side effect during journal failure")
        commands = DurableCommands(j, None, Manager())
        commands.runs["s"] = {"epoch": 1, "deadline": time.monotonic() - 1, "sealed": False}
        from app.session import RuntimeFailure
        with self.assertRaises(RuntimeFailure):
            await commands.execute(command())
        j.offline = True
        with self.assertRaises(JournalError):
            await commands.execute(command())

    async def test_spool_bound_and_identity_mapping(self):
        with tempfile.TemporaryDirectory() as directory:
            p = DurableEventPublisher(Journal(), directory, max_pending=1)
            with self.assertRaises(JournalError):
                await p.publish(envelope("SESSION_READY", "unmapped", "t"))
            p.bind(command())
            await p.publish(envelope("UTTERANCE_QUEUED", "s", "t", "u"))
            with self.assertRaises(JournalError):
                await p.publish(envelope("UTTERANCE_GENERATING", "s", "t", "u"))
            await p.close()

    async def test_duplicate_spool_identity_and_body_conflict(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = Journal()
            publisher = DurableEventPublisher(journal, directory)
            publisher.bind(command())
            event = envelope("UTTERANCE_QUEUED", "s", "t", "u")
            await publisher.publish(event)
            await publisher.publish(event)
            self.assertEqual(publisher.db.execute("SELECT count(*) FROM pending").fetchone()[0], 1)
            self.assertTrue(await publisher.flush_once())
            await publisher.publish(event)
            self.assertEqual(publisher.db.execute("SELECT count(*) FROM pending").fetchone()[0], 0)
            event["payload"] = {"changed": True}
            with self.assertRaises(JournalError):
                await publisher.publish(event)
            await publisher.close()

    def test_shared_fingerprint_vectors(self):
        root = Path(__file__).resolve().parents[2]
        for v in json.loads((root / "backend/internal/durability/testdata/fingerprint-v05.json").read_text()):
            self.assertEqual(fingerprint(v["command"]), v["fingerprint"])
        with self.assertRaises(ValueError):
            canonical({"float": 1.0})
