"""Continuity Stop lifecycle fault tests; providers/sinks are explicit doubles."""
import asyncio
import unittest
from types import SimpleNamespace

import test_session_binding as fixtures
from app.models import CreateSession
from app.session import RuntimeFailure


class ContinuityLifecycleTests(unittest.IsolatedAsyncioTestCase):
    # Reuse construction, not inherited acceptance cases.
    asyncSetUp = fixtures.BindingTests.asyncSetUp
    asyncTearDown = fixtures.BindingTests.asyncTearDown
    create = fixtures.BindingTests.create
    async def test_continuity_cleanup_failure_retains_binding_and_blocks_worker_reuse(self):
        await self.create()
        session = self.manager.get_session("session_1")
        session.continuity = SimpleNamespace(fence=lambda reason: None)
        original_stop = session.media_output.stop
        async def unavailable():
            raise ConnectionError("synthetic native cleanup unavailable")
        session.media_output.stop = unavailable
        with self.assertRaises(RuntimeFailure):
            await self.manager.stop_session("session_1", "stop")
        self.assertEqual(session.state, "STOPPING")
        self.assertIn("session_1", self.manager.sessions)
        self.assertIn("session_1", self.manager.bound)
        self.assertFalse(self.client.released)
        self.assertNotIn("SESSION_ENDED", [e["eventType"] for e in self.publisher.events])
        with self.assertRaises(RuntimeFailure):
            await self.manager.create_session(CreateSession(**{**fixtures.CREATE, "sessionId": "session_2"}))
        # This is explicit idempotent native cleanup retry; no command replay,
        # provider generation, narration resume, or failed fact completion.
        session.media_output.stop = original_stop
        await self.manager.stop_session("session_1", "stop")
        self.assertEqual(session.state, "ENDED")
        self.assertNotIn("session_1", self.manager.bound)
        self.assertEqual(self.client.released.count("session_1"), 1)

    async def test_continuity_release_failure_retains_worker_reservation(self):
        await self.create()
        session = self.manager.get_session("session_1")
        session.continuity = SimpleNamespace(fence=lambda reason: None)
        self.client.fail_release = True
        with self.assertRaises(RuntimeFailure):
            await self.manager.stop_session("session_1", "stop")
        self.assertIn("session_1", self.manager.release_pending)
        self.assertIn("session_1", self.manager.bound)
        with self.assertRaises(RuntimeFailure):
            await self.manager.create_session(CreateSession(**{**fixtures.CREATE, "sessionId": "session_2"}))
        self.client.fail_release = False
        await self.manager._release("session_1")
        self.assertNotIn("session_1", self.manager.release_pending)
        self.assertNotIn("session_1", self.manager.bound)

