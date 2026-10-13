"""Deterministic drain regressions; require the real media dependencies."""
import asyncio
import time
import unittest

from app.providers import AudioChunk, VideoFrame, MediaDeliveryError

try:
    from app.webrtc_media import WebRTCMediaOutput, _AudioTrack, _VideoTrack, _Peer
except ImportError:
    WebRTCMediaOutput = None


class FakeConnection:
    connectionState = "connected"
    iceConnectionState = "connected"

    def __init__(self, delay=0):
        self.delay = delay
        self.closed = False

    async def close(self):
        await asyncio.sleep(self.delay)
        self.closed = True
        self.connectionState = "closed"


@unittest.skipIf(WebRTCMediaOutput is None, "Install runtime/requirements-real-media.txt")
class WebRTCDrainRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.output = WebRTCMediaOutput()
        self.output.stale_window = 0.08
        self.output.drain_timeout = 0.3
        await self.output.start()

    async def asyncTearDown(self):
        await self.output.stop()

    def peer(self, name, connection=None):
        peer = _Peer(name, connection or FakeConnection(), _AudioTrack(), _VideoTrack())
        self.output.peers.add(peer)
        return peer

    async def send(self, generation=1):
        await self.output.push_audio(AudioChunk(generation, 0, b"\x01\x00" * 960, 48000, 1))
        await self.output.push_video(VideoFrame(generation, 0, 2, 2, bytes([255, 0, 0]) * 4))

    async def consume(self, peer, audio=True, video=True):
        if audio:
            peer.audio.next_at = time.monotonic() - 1
            await peer.audio.recv()
        if video:
            peer.video.next_at = time.monotonic() - 1
            await peer.video.recv()

    async def test_a_normal_consumer_completes(self):
        peer = self.peer("healthy")
        await self.send()
        await self.consume(peer)
        await self.output.drain(1)
        self.assertEqual((peer.audio.enqueued, peer.audio.consumed, peer.video.enqueued, peer.video.consumed), (1, 1, 1, 1))

    async def test_b_audio_consumer_stops(self):
        peer = self.peer("audio-stalled")
        await self.send()
        await self.consume(peer, audio=False)
        with self.assertRaises(MediaDeliveryError):
            await asyncio.wait_for(self.output.drain(1), 1)
        self.assertNotIn(peer, self.output.peers)

    async def test_c_video_consumer_stops(self):
        peer = self.peer("video-stalled")
        await self.send()
        await self.consume(peer, video=False)
        with self.assertRaises(MediaDeliveryError):
            await asyncio.wait_for(self.output.drain(1), 1)
        self.assertNotIn(peer, self.output.peers)

    async def test_d_healthy_peer_survives_stalled_peer(self):
        healthy = self.peer("healthy")
        stalled = self.peer("stalled")
        await self.send()
        await self.consume(healthy)
        # The previous queue.empty() rule still sees B's queued frames and times out.
        async def legacy_queue_empty_drain():
            deadline = time.monotonic() + 0.04
            while any(not p.audio.queue.empty() or not p.video.queue.empty() for p in (healthy, stalled)):
                if time.monotonic() >= deadline:
                    raise RuntimeError("WebRTC playback drain timed out")
                await asyncio.sleep(0.005)

        with self.assertRaisesRegex(RuntimeError, "drain timed out"):
            await legacy_queue_empty_drain()
        await asyncio.wait_for(self.output.drain(1), 1)
        self.assertIn(healthy, self.output.peers)
        self.assertNotIn(stalled, self.output.peers)
        self.assertEqual(self.output.pop_warnings()[0]["peer"]["peerId"], "stalled")

    async def test_e_interrupt_invalidates_pending_drain(self):
        peer = self.peer("interrupted")
        await self.send()
        draining = asyncio.create_task(self.output.drain(1))
        await asyncio.sleep(0)
        await self.output.interrupt(2)
        await asyncio.wait_for(draining, 0.2)
        self.assertEqual((peer.audio.enqueued, peer.audio.consumed, peer.video.enqueued, peer.video.consumed), (0, 0, 0, 0))
        self.assertTrue(peer.audio.queue.empty() and peer.video.queue.empty())

    async def test_f_stop_after_media_failure_ends_session(self):
        from app.config import Settings
        from app.events import MemoryEventPublisher
        from app.models import CreateSession, Utterance
        from app.providers import MockAvatarEngine, MockLLMProvider, MockTTSProvider
        from app.session import SessionManager
        publisher = MemoryEventPublisher()
        manager = SessionManager(Settings(), publisher, MockLLMProvider, MockTTSProvider, MockAvatarEngine, WebRTCMediaOutput)
        request = CreateSession(**{"commandId": "cmd_1", "traceId": "trace_1", "sessionId": "session_stale", "avatar": {"avatarId": "avatar_1", "engine": "MOCK"}, "voice": {"voiceId": "voice_1", "provider": "MOCK"}, "config": {"fps": 25, "preview": {"type": "WEBRTC"}}, "context": {"roomId": "room_1", "systemPrompt": "test"}})
        await manager.create_session(request)
        for _ in range(100):
            if manager.get_session("session_stale").state == "READY":
                break
            await asyncio.sleep(0.01)
        await manager.start_session("session_stale", "trace_1")
        session = manager.get_session("session_stale")
        session.media_output.stale_window = 0.08
        session.media_output.peers.add(_Peer("stalled", FakeConnection(), _AudioTrack(), _VideoTrack()))
        item = Utterance(commandId="cmd_speak", traceId="trace_1", utteranceId="utt_stale", text="hello", priority=40, interruptPolicy="NONE", source="OPERATOR", voice={"voiceId": "voice_1"})
        await manager.speak("session_stale", item)
        for _ in range(100):
            if any(e["eventType"] == "UTTERANCE_FAILED" for e in publisher.events):
                break
            await asyncio.sleep(0.01)
        self.assertIn("MEDIA_FAILED", [e["eventType"] for e in publisher.events])
        await asyncio.wait_for(manager.stop_session("session_stale", "trace_stop"), 3)
        self.assertIn("SESSION_ENDED", [e["eventType"] for e in publisher.events])
        self.assertNotIn("session_stale", manager.sessions)

    async def test_g_300_short_utterances_do_not_accumulate(self):
        peer = self.peer("loop")
        for _ in range(300):
            await self.send()
            await self.consume(peer)
            await self.output.drain(1)
            self.assertEqual((peer.audio.queue.qsize(), peer.video.queue.qsize()), (0, 0))
        self.assertEqual((peer.audio.enqueued, peer.audio.consumed), (300, 300))
        self.assertEqual((peer.video.enqueued, peer.video.consumed), (300, 300))

    async def test_h_stalled_peer_close_is_bounded(self):
        peer = self.peer("close-hangs", FakeConnection(delay=5))
        self.output.peer_close_timeout = 0.05
        await asyncio.wait_for(self.output.stop(), 0.3)
        self.assertEqual(len(self.output.peers), 0)
        self.assertEqual(peer.audio.readyState, "ended")
        self.assertEqual(peer.video.readyState, "ended")

    async def test_i_blocked_old_audio_enqueue_cannot_poison_new_generation(self):
        peer = self.peer("generation-race")
        peer.audio.queue = asyncio.Queue(maxsize=1)
        chunk = AudioChunk(1, 0, b"\x01\x00" * 1920, 48000, 1)
        producer = asyncio.create_task(self.output.push_audio(chunk))
        await asyncio.sleep(0)
        self.assertFalse(producer.done())
        await self.output.interrupt(2)
        await asyncio.wait_for(producer, 0.5)
        self.assertEqual((peer.audio.enqueued, peer.audio.consumed), (0, 0))
        await self.output.push_audio(AudioChunk(2, 0, b"\x02\x00" * 960, 48000, 1))
        await self.consume(peer, video=False)
        await self.output.drain(2)
        self.assertEqual((peer.audio.enqueued, peer.audio.consumed), (1, 1))

    async def test_j_video_buffer_is_time_based_for_supported_target_fps(self):
        for fps, expected in ((20, 8), (25, 10), (30, 12)):
            with self.subTest(fps=fps):
                track = _VideoTrack(fps=fps, buffer_ms=400, max_buffer_ms=1000)
                self.assertEqual(track.queue.maxsize, expected)
                track.stop()

    async def test_k_fast_producer_healthy_consumer_gets_backpressure_not_eviction(self):
        peer = self.peer("paced")
        peer.video.queue = asyncio.Queue(maxsize=2)
        consumed = asyncio.Event()

        async def consumer():
            for _ in range(20):
                await peer.video.recv()
            consumed.set()

        task = asyncio.create_task(consumer())
        try:
            for index in range(20):
                await self.output.push_video(VideoFrame(1, index * 40000, 2, 2, bytes([1, 2, 3]) * 4))
            await asyncio.wait_for(consumed.wait(), 2)
            self.assertIn(peer, self.output.peers)
            self.assertLessEqual(peer.video.queue.qsize(), 2)
            self.assertGreater(peer.video.backpressure_events, 0)
            self.assertGreater(peer.video.backpressure_wait_ms, 0)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def test_l_truly_stalled_full_queue_is_evicted(self):
        peer = self.peer("full-stalled")
        peer.video.queue = asyncio.Queue(maxsize=1)
        frame = VideoFrame(1, 0, 2, 2, bytes([1, 2, 3]) * 4)
        await self.output.push_video(frame)
        with self.assertRaises(MediaDeliveryError):
            await asyncio.wait_for(self.output.push_video(frame), 1)
        self.assertNotIn(peer, self.output.peers)
        self.assertEqual(self.output.peer_stall_events, 1)

    async def test_m_healthy_peer_survives_stalled_peer_during_backpressure(self):
        healthy = self.peer("healthy-backpressure")
        stalled = self.peer("stalled-backpressure")
        healthy.video.queue = asyncio.Queue(maxsize=1)
        stalled.video.queue = asyncio.Queue(maxsize=1)
        frame = VideoFrame(1, 0, 2, 2, bytes([1, 2, 3]) * 4)
        await self.output.push_video(frame)

        async def consume_healthy():
            for _ in range(3):
                healthy.video.next_at = time.monotonic() - 1
                await healthy.video.recv()
                await asyncio.sleep(0.01)

        task = asyncio.create_task(consume_healthy())
        await self.output.push_video(frame)
        await asyncio.wait_for(task, 1)
        self.assertIn(healthy, self.output.peers)
        self.assertNotIn(stalled, self.output.peers)

    async def test_n_interrupt_while_video_backpressured_has_no_generation_leak(self):
        peer = self.peer("video-generation-race")
        peer.video.queue = asyncio.Queue(maxsize=1)
        old = VideoFrame(1, 0, 2, 2, bytes([1, 2, 3]) * 4)
        await self.output.push_video(old)
        producer = asyncio.create_task(self.output.push_video(old))
        await asyncio.sleep(0.02)
        self.assertFalse(producer.done())
        await self.output.interrupt(2)
        await asyncio.wait_for(producer, 0.5)
        self.assertTrue(peer.video.queue.empty())
        self.assertEqual(peer.video.enqueued, 0)

    async def test_o_stop_while_backpressured_is_bounded(self):
        peer = self.peer("stop-backpressure")
        peer.video.queue = asyncio.Queue(maxsize=1)
        frame = VideoFrame(1, 0, 2, 2, bytes([1, 2, 3]) * 4)
        await self.output.push_video(frame)
        producer = asyncio.create_task(self.output.push_video(frame))
        await asyncio.sleep(0.02)
        await asyncio.wait_for(self.output.stop(), 0.5)
        await asyncio.wait_for(producer, 0.5)
        self.assertEqual(len(self.output.peers), 0)

    async def test_p_producer_slower_than_target_does_not_accumulate(self):
        peer = self.peer("slow-producer")
        for index in range(12):
            await self.output.push_video(VideoFrame(1, index * 50000, 2, 2, bytes([1, 2, 3]) * 4))
            peer.video.next_at = time.monotonic() - 1
            await peer.video.recv()
            await asyncio.sleep(0)
        self.assertEqual(peer.video.queue.qsize(), 0)
        self.assertEqual(peer.video.backpressure_events, 0)
