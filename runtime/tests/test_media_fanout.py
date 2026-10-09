import asyncio
import unittest

from app.media_fanout import FanoutMediaOutput
from app.providers import AudioChunk, MediaDeliveryError, VideoFrame


class FakeSink:
    def __init__(self, block=False, fail_drain=False):
        self.block = block
        self.fail_drain = fail_drain
        self.gate = asyncio.Event()
        self.audio = []
        self.video = []
        self.generation_id = 1
        self.running = False
        self.stops = 0

    def configure_session(self, config): pass
    async def start(self): self.running = True
    async def push_audio(self, chunk):
        if self.block:
            await self.gate.wait()
        self.audio.append(chunk)
    async def push_video(self, frame):
        if self.block:
            await self.gate.wait()
        self.video.append(frame)
    async def drain(self, generation_id):
        if self.fail_drain:
            raise MediaDeliveryError("sink failed")
    async def interrupt(self, generation_id): self.generation_id = generation_id
    async def stop(self): self.running = False; self.stops += 1


class FanoutTests(unittest.IsolatedAsyncioTestCase):
    async def test_slow_sink_does_not_block_healthy_sink(self):
        healthy, slow = FakeSink(), FakeSink(block=True)
        output = FanoutMediaOutput([("webrtc", healthy), ("rtmp", slow)], fps=25)
        await output.start()
        chunk = AudioChunk(1, 0, b"\0" * 640)
        frame = VideoFrame(1, 0, 2, 2, b"\0" * 12)
        await asyncio.wait_for(output.push_audio(chunk), 0.1)
        await asyncio.wait_for(output.push_video(frame), 0.1)
        await asyncio.sleep(0)
        self.assertEqual(healthy.audio, [chunk])
        self.assertEqual(healthy.video, [frame])
        self.assertEqual(slow.audio, [])
        slow.gate.set()
        await output.drain(1)
        await output.stop()

    async def test_one_failed_sink_does_not_fail_generation(self):
        healthy, failed = FakeSink(), FakeSink(fail_drain=True)
        output = FanoutMediaOutput([("webrtc", healthy), ("rtmp", failed)])
        await output.start()
        await output.drain(1)
        warnings = output.pop_warnings()
        self.assertTrue(any(item["code"] == "MEDIA_SINK_DRAIN_FAILED" for item in warnings))
        await output.stop()

    async def test_interrupt_clears_old_generation_from_each_channel(self):
        first, second = FakeSink(block=True), FakeSink(block=True)
        output = FanoutMediaOutput([("first", first), ("second", second)], audio_buffer_ms=40)
        await output.start()
        pushes = asyncio.gather(*(
            output.push_audio(AudioChunk(1, sequence, b"\0" * 640)) for sequence in range(8)
        ))
        await asyncio.sleep(0.02)
        await output.interrupt(2)
        await asyncio.wait_for(pushes, 0.2)
        self.assertTrue(all(channel.audio.empty() for channel in output.channels))
        self.assertEqual(first.generation_id, 2)
        self.assertEqual(second.generation_id, 2)
        first.gate.set(); second.gate.set()
        await output.stop()


if __name__ == "__main__":
    unittest.main()
