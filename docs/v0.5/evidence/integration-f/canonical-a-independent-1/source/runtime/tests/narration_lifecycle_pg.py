"""Real Go journal/binding HTTP + PG; captured packet/providers are labelled fixtures."""
import asyncio
import json
import sys
import tempfile
import time

from app.config import Settings
from app.durability_client import DurabilityClient
from app.durable_events import DurableEventPublisher
from app.events import MemoryEventPublisher
from app.models import CreateSession
from app.narration import NarrationCommands
from app.narration_segments import SegmentExecutor
from app.providers import MockLLMProvider, MockTTSProvider, MockAvatarEngine, MockMediaOutput
from app.session import RuntimeFailure
from app.session_binding import BindingClient, BoundSessionManager
from test_session_binding import CREATE, packet


class CapturedFixtureClient(BindingClient):
    # DELETE uses the actual authenticated Go binding route and SQL Release.
    # GET is an explicit captured-packet fixture, not a real provider registry.
    async def resolve(self, sid):
        return packet()


class LifecycleMedia(MockMediaOutput):
    fail_cleanup = False
    def bind_timeline(self, timeline):
        self.timeline = timeline
    async def stop(self):
        if self.fail_cleanup:
            raise ConnectionError("injected native cleanup failure")
        await super().stop()


async def main():
    base, journal_file, binding_file, command_file, scenario = sys.argv[1:]
    command = json.loads(open(command_file).read())
    journal = DurabilityClient(base, journal_file)
    directory = tempfile.TemporaryDirectory()
    publisher = DurableEventPublisher(journal, directory.name)
    manager = BoundSessionManager(Settings(), MemoryEventPublisher(), MockLLMProvider,
        MockTTSProvider, MockAvatarEngine, LifecycleMedia,
        binding_client=CapturedFixtureClient(base, binding_file),
        bundle_builder=lambda *args: (MockLLMProvider, MockTTSProvider, MockAvatarEngine, LifecycleMedia))
    await manager.create_session(CreateSession(**{**CREATE, "sessionId": "s"}))
    while manager.get_session("s").state != "READY":
        await asyncio.sleep(.01)
    session = manager.get_session("s")
    session.publisher = publisher
    adapter = NarrationCommands(journal, publisher, manager)
    adapter.runs["s"] = {"epoch": 1, "deadline": time.monotonic()+60, "sealed": False, "barrier": 0}
    session.continuity = SegmentExecutor(session, 1, journal, lambda: adapter.check("s", 1))
    session.media_output.fail_cleanup = scenario == "cleanup_failure"
    publisher.start()
    try:
        await adapter.execute(command)
        assert scenario != "cleanup_failure", "failed native cleanup returned success"
        assert "s" not in manager.sessions and "s" not in manager.bound
        assert session.continuity.closed and session.state == "ENDED"
        for _ in range(500):
            if publisher.db.execute("SELECT count(*) FROM pending").fetchone()[0] == 0:
                break
            await asyncio.sleep(.01)
        else:
            raise AssertionError("durable event spool did not flush")
        await manager.create_session(CreateSession(**{**CREATE, "sessionId": "s2"}))
        while manager.get_session("s2").state != "READY":
            await asyncio.sleep(.01)
        assert manager.bound["s2"]["workerRef"] == "physical-1"
    except RuntimeFailure:
        assert scenario == "cleanup_failure"
        assert session.state == "STOPPING" and session.continuity.closed
        assert "s" in manager.bound and "s" in manager.sessions
        assert publisher.db.execute("SELECT count(*) FROM pending WHERE envelope LIKE '%SESSION_ENDED%'").fetchone()[0] == 0
        try:
            await manager.create_session(CreateSession(**{**CREATE, "sessionId": "s2"}))
        except RuntimeFailure as exc:
            assert exc.code == "RUNTIME_OVERLOADED"
        else:
            raise AssertionError("failed Stop allowed Worker reuse")
    # No generation is invoked. Failed native cleanup is left UNKNOWN and
    # binding-retained; this fixture does not add replay/finalizer authority.
    print(json.dumps({"scope": "REAL_POSTGRES_AUTH_HTTP_CAPTURED_PROVIDER_FIXTURES",
        "scenario": scenario, "state": session.state, "fenced": session.continuity.closed,
        "reservationRetained": "s" in manager.bound, "gpu": "NOT_TESTED"}))
    await publisher.close()
    await journal.close()
    directory.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
