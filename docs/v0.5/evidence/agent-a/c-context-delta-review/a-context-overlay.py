import asyncio, unittest
from types import SimpleNamespace
import test_session_binding as fixtures
class AContextTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=fixtures.BindingTests.asyncSetUp
    asyncTearDown=fixtures.BindingTests.asyncTearDown
    create=fixtures.BindingTests.create
    async def test_cancelled_llm_close_retains_retry_context(self):
        await self.create()
        session=self.manager.get_session("session_1")
        session.continuity=SimpleNamespace(fence=lambda reason:None)
        original=self.manager._close_llm
        async def cancelled(session): raise asyncio.CancelledError()
        self.manager._close_llm=cancelled
        with self.assertRaises(asyncio.CancelledError):
            await self.manager.stop_session("session_1","stop")
        self.assertIs(self.manager.sessions["session_1"],session)
        self.assertIn("session_1",self.manager.bound)
        self.assertFalse(self.client.released)
        self.manager._close_llm=original
        await self.manager.stop_session("session_1","stop")
        self.assertNotIn("session_1",self.manager.sessions)
        self.assertNotIn("session_1",self.manager.bound)
