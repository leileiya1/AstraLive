"""CPU integration safeguards. No production Guardian or GPU acceptance."""
import asyncio
import copy
import os
import time
import unittest
from unittest.mock import patch

from app.durable_live_journal import ExecutionInbox, JournalError, OutputGate, Permit, digest, suspend_clock
from test_durable_live_journal import COMMAND, FakeJournal, permit_data


class DurableLiveAdmissionTests(unittest.TestCase):
    def test_production_flag_refuses_unproven_guardian_even_with_registration(self):
        from app.main import create_app
        with patch.dict(os.environ, {"ASTRALIVE_DURABLE_LIVE_ENABLED": "true"}):
            with self.assertRaisesRegex(RuntimeError, "OUTPUT_FENCE_UNPROVEN"):
                create_app(durable_registration=object())

    def test_misspelled_flag_is_not_silently_legacy(self):
        from app.main import create_app
        with patch.dict(os.environ, {"ASTRALIVE_DURABLE_LIVE_ENABLED": "yes"}):
            with self.assertRaisesRegex(RuntimeError, "INVALID_ARGUMENT"):
                create_app()


class LocalOwnershipTests(unittest.IsolatedAsyncioTestCase):
    async def test_expiry_fences_inflight_renewal_and_attempt(self):
        async def close(): pass
        gate = OutputGate(close)
        await gate.install("room", COMMAND["runId"], COMMAND["runEpoch"], 1, COMMAND["sessionId"], "producer")
        original_barrier = gate.barrier
        gate.set_permit(Permit.received(permit_data(150), time.monotonic(), suspend_clock()), COMMAND["runId"])
        gate.bind_attempt(COMMAND, 1)
        await asyncio.sleep(.09)
        self.assertGreater(gate.barrier, original_barrier)
        with self.assertRaises(JournalError):
            gate.set_permit(Permit.received(permit_data(), time.monotonic(), suspend_clock()), COMMAND["runId"], original_barrier)
        await gate.close()

    async def test_sql_receipt_remains_dedup_authority_after_local_task_release(self):
        calls = []
        async def close(): pass
        async def ready(command): pass
        async def effect(command, gate): calls.append(command["commandId"])
        journal = FakeJournal()
        gate = OutputGate(close)
        await gate.install("room", COMMAND["runId"], COMMAND["runEpoch"], 1, COMMAND["sessionId"], journal.producer)
        inbox = ExecutionInbox(journal, gate, effect, guardian_id="guardian", readiness=ready, capacity=1)
        await inbox.accept(copy.deepcopy(COMMAND))
        await asyncio.sleep(.03)
        self.assertEqual(len(inbox._commands), 0)
        self.assertEqual(len(inbox._tasks), 0)
        await inbox.accept(copy.deepcopy(COMMAND))
        await asyncio.sleep(.03)
        self.assertEqual(calls, [COMMAND["commandId"]])
        self.assertEqual(journal.starts, 1)
        await inbox.close()
