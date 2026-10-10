"""Synthetic sink/Worker tests; real output is covered by v0.4 acceptance."""
import asyncio
from types import SimpleNamespace
import unittest
from app.bound_media import BoundConsumptionMediaOutput
from app.config import RTMPSettings
from app.providers import VideoFrame
from app.providers import MediaDeliveryError
from app.rtmp_media import FFmpegRTMPMediaOutput


class BoundMediaTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.sink = FFmpegRTMPMediaOutput(RTMPSettings(enabled=True,
            publish_url='rtmp://localhost/live/synthetic', width=8, height=8))
        self.sink.running = True
        self.sink._process = SimpleNamespace(returncode=None)
        self.credits = []
        async def consumed(packet): self.credits.append(packet['frame_sequence'])
        self.avatar = SimpleNamespace(running=True, generation_id=1,
            link=SimpleNamespace(consumed=consumed), cached_idle=None,
            log=lambda *a, **kw: None, pipeline=None)
        self.output = BoundConsumptionMediaOutput(self.sink, self.avatar)

    async def asyncTearDown(self):
        self.avatar.running = False
        for task in tuple(self.output.acks): task.cancel()
        await asyncio.gather(*tuple(self.output.acks), return_exceptions=True)

    async def enqueue(self):
        frame = VideoFrame(1, 0, 8, 8, bytes(8*8*3))
        self.output.metadata[id(frame)] = dict(source='GPU_INFERENCE',
            activity='TALKING', generation_id=42, frame_sequence=0)
        await self.output.push_video(frame)

    async def test_headless_encoder_admits_idle_but_no_credit_on_enqueue(self):
        self.assertTrue(self.output.has_peer())
        await self.enqueue(); await asyncio.sleep(.02)
        self.assertEqual(self.credits, [])
        self.sink.video_written = 1
        await asyncio.sleep(.02)
        self.assertEqual(self.credits, [0])

    async def test_force_cancels_credit_and_new_epoch_cannot_ack_old_job(self):
        await self.enqueue()
        self.avatar.generation_id = 2
        await self.sink.interrupt(2)
        self.sink.video_written = 5
        await asyncio.sleep(.02)
        self.assertEqual(self.credits, [])

    async def test_failed_encoder_is_not_a_consumer(self):
        self.sink._process.returncode = 1
        self.assertFalse(self.output.has_peer())

    async def test_absent_preview_does_not_warn_or_mask_rtmp_drain_failure(self):
        drained = []
        async def preview_drain(generation): self.fail('absent preview drained')
        async def publish_drain(generation): drained.append(generation)
        web = SimpleNamespace(peers=[], drain=preview_drain)
        self.sink.drain = publish_drain
        channels = [SimpleNamespace(name=name, output=out, audio=asyncio.Queue(), video=asyncio.Queue())
                    for name, out in [('webrtc', web), ('rtmp', self.sink)]]
        self.output = BoundConsumptionMediaOutput(SimpleNamespace(channels=channels), self.avatar)
        await self.output.drain(1)
        self.assertEqual(drained, [1])
        self.sink._process.returncode = 1
        with self.assertRaises(MediaDeliveryError): await self.output.drain(1)

    async def test_connected_preview_keeps_original_fanout_drain(self):
        drained = []
        async def fanout_drain(generation): drained.append(generation)
        channels = [SimpleNamespace(name='webrtc', output=SimpleNamespace(peers=[object()])),
                    SimpleNamespace(name='rtmp', output=self.sink)]
        self.output = BoundConsumptionMediaOutput(SimpleNamespace(channels=channels, drain=fanout_drain), self.avatar)
        await self.output.drain(1)
        self.assertEqual(drained, [1])

    async def test_credit_holds_original_link_across_recovery(self):
        await self.enqueue()
        async def wrong(packet): self.fail('retired packet credited on new Worker epoch')
        self.avatar.link = SimpleNamespace(consumed=wrong)
        self.sink.video_written = 1
        await asyncio.sleep(.02)
        self.assertEqual(self.credits, [0])

    async def test_pipe_write_is_required_and_force_during_write_is_fenced(self):
        self.sink._video_fd = 999
        await self.sink.video_queue.put((1, bytes(8*8*3)))
        entered, release = asyncio.Event(), asyncio.Event()
        async def write(fd, payload): entered.set(); await release.wait()
        self.sink._write_fd = write
        clock = asyncio.create_task(self.sink._video_clock())
        try:
            await asyncio.wait_for(entered.wait(), 1)
            self.assertEqual(self.sink.video_consumed, 1)
            self.assertEqual(self.sink.video_written, 0)
            await self.sink.interrupt(2)
            release.set(); await asyncio.sleep(.02)
            self.assertEqual(self.sink.video_written, 0)
        finally:
            clock.cancel(); await asyncio.gather(clock, return_exceptions=True)

    async def test_broken_pipe_never_credits(self):
        self.sink._video_fd = 999
        await self.sink.video_queue.put((1, bytes(8*8*3)))
        async def write(fd, payload): self.sink.write_failures += 1
        self.sink._write_fd = write
        clock = asyncio.create_task(self.sink._video_clock())
        try:
            await asyncio.sleep(.02)
            self.assertEqual(self.sink.video_written, 0)
        finally:
            clock.cancel(); await asyncio.gather(clock, return_exceptions=True)

    async def test_trace_excludes_idle_and_stale_generation_and_keeps_credit(self):
        from app.interaction_trace import InteractionTrace
        trace = InteractionTrace('t','s','u')
        self.output.set_interaction_trace(trace,1)
        frame = VideoFrame(1,0,8,8,bytes(8*8*3))
        self.output.metadata[id(frame)] = dict(source='GPU_INFERENCE',activity='IDLE',generation_id=42,frame_sequence=0)
        await self.output.push_video(frame)
        self.assertNotIn('avatar_first_generated_frame',trace.points)
        self.assertEqual(self.credits,[])
        self.sink.video_written=1
        await asyncio.sleep(.02)
        await self.enqueue()
        self.assertIn('avatar_first_generated_frame',trace.points)
        self.assertIn('media_first_video',trace.points)
        self.output.set_interaction_trace(trace,2)
        before=trace.summary()
        await self.enqueue()
        self.assertEqual(trace.summary(),before)
