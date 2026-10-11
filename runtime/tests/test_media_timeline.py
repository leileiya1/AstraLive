"""V2 local determinism/fault tests. Journal/Worker doubles are not real A/GPU."""
import asyncio
import gc
import weakref
from dataclasses import replace
import os
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from app.media_timeline import (MediaTimeline, TimelinePosition, MediaIdentity, Lane,
    BufferPolicy, AudioMasterClock, AdaptiveBuffer, RationalResampler, samples_to_pts,
    enabled, split_audio, TimedAudioChunk, TimedVideoFrame, SpeculativeMediaBuffer, FrameDispositions)
from app.providers import AudioChunk, VideoFrame, MediaDeliveryError
from app.webrtc_media import _TimelineAudioTrack, _TimelineVideoTrack, WebRTCMediaOutput, _Peer
from app.rtmp_media import FFmpegRTMPMediaOutput
from app.config import RTMPSettings
from app.media_fanout import FanoutMediaOutput
from app.bound_media import BoundConsumptionMediaOutput


class TestJournal:
    __test__ = False
    def __init__(self):
        self.operations = []
        self.pause = None
        self.fail = None
    async def record(self, operation, command, proof):
        self.operations.append((operation, command, proof))
        if self.pause:
            await self.pause.wait()
        if operation == self.fail:
            raise ConnectionError("injected journal ACK loss")
        return {"durable": True, "testDouble": True}


def command(operation="COMMIT_SEGMENT", epoch=1, segment="s1", key="c1", lane="NARRATION"):
    return {"commandId": key, "commandType": operation, "sessionId": "session",
            "runEpoch": 1, "timelineEpoch": epoch, "segmentId": segment, "lane": lane}


def descriptor(count=640):
    return {"sampleCount": count, "contentHash": "sha256:" + "a" * 64,
            "utteranceId": "u1", "finalMarker": True, "requiredSinks": ["preview"],
            "videoTiming": {"fps": 25}, "factVersion": "fixture-v1"}


class MappingTests(unittest.TestCase):
    def test_disposition_requires_same_live_frame_and_does_not_retain_rgb(self):
        observations = FrameDispositions(limit=3)
        old = VideoFrame(1, 0, 1, 1, b"123")
        new = VideoFrame(1, 40000, 1, 1, b"456")
        observations.record(old, "consumed")
        # Deterministically inject the state a reused CPython address left behind.
        observations.entries[id(new)] = observations.entries[id(old)]
        self.assertIsNone(observations.get(new))
        old_ref = weakref.ref(old)
        del old
        gc.collect()
        self.assertIsNone(old_ref())
        self.assertIsNone(observations.get(new))
        frames = [VideoFrame(1, i * 40000, 1, 1, b"789") for i in range(8)]
        for frame in frames:
            observations.record(frame, "dropped")
        self.assertEqual(len(observations.entries), 3)
        self.assertIsNone(observations.get(frames[0]))
        self.assertEqual(observations.get(frames[-1]), "dropped")

    def test_audio_video_clock_rates_and_long_fractional_positions(self):
        self.assertEqual(samples_to_pts(640, 16000, 48000), 1920)
        self.assertEqual(samples_to_pts(640, 16000, 90000), 3600)
        for rate in (16000, 22050, 44100, 48000):
            previous = 0
            for sample in range(0, rate * 31, 137):
                mapped = samples_to_pts(sample, rate, 90000)
                self.assertGreaterEqual(mapped, previous)
                self.assertLess(sample * 90000 - mapped * rate, rate)
                previous = mapped
        for bad in (True, -1, 1.1, "640"):
            with self.assertRaises(ValueError): samples_to_pts(bad, 16000, 90000)

    def test_resampling_44100_small_chunks_has_no_count_drift(self):
        resampler = RationalResampler(48000)
        size = 0
        for i in range(10000):
            size += len(resampler.convert(b"\x01\x00" * 137, 44100)) // 2
        self.assertEqual(size, 1370000 * 48000 // 44100)
        with self.assertRaises(ValueError): resampler.convert(bytes(640), 16000)
        with self.assertRaises(ValueError): RationalResampler(48000).convert(b"a", 16000)

    def test_dynamic_target_and_absolute_bounds(self):
        adaptive = AdaptiveBuffer()
        for i in range(100):
            target = adaptive.observe(i * .3, 20)
            self.assertLessEqual(target, 800)
            self.assertGreaterEqual(target, 320)
        self.assertEqual(target, 800)
        for bad in (dict(committed_ms=1000), dict(interruptible_ms=9999), dict(speculative_ms=0)):
            with self.assertRaises(ValueError): BufferPolicy(**bad)

    def test_flags_off_alias_and_conflicts(self):
        with patch.dict(os.environ, {}, clear=True): self.assertFalse(enabled())
        with patch.dict(os.environ, {"ASTRALIVE_MEDIA_TIMELINE_ENABLED": "true"}, clear=True): self.assertTrue(enabled())
        with patch.dict(os.environ, {"ASTRALIVE_MEDIA_TIMELINE_V2_ENABLED": "false",
                                    "ASTRALIVE_MEDIA_TIMELINE_ENABLED": "true"}, clear=True):
            with self.assertRaises(ValueError): enabled()

    def test_duration_bounded_fanout_splits_preserve_ranges(self):
        identity = MediaIdentity("session", 1, 1, 1, "s1", "u1", Lane.NARRATION)
        chunk = TimedAudioChunk(1, 0, bytes(44100 * 2), 44100, 1, identity, 0, 16000, 16000)
        parts = list(split_audio(chunk))
        self.assertEqual(len(parts), 50)
        self.assertEqual(sum(len(p.pcm) for p in parts), len(chunk.pcm))
        self.assertEqual(parts[-1].endSample, 16000)
        self.assertTrue(all(a.endSample == b.startSample for a, b in zip(parts, parts[1:])))


class TimelineControlTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.journal = TestJournal()
        self.timeline = MediaTimeline("session", 1, journal=self.journal)

    async def commit(self, count=640):
        return await self.timeline.CommitSegment(command(), "attempt", 1, descriptor(count), self.timeline.position(0), 0)

    async def test_commit_requires_journal_and_never_overlaps(self):
        memory = MediaTimeline("session", 1)
        with self.assertRaisesRegex(RuntimeError, "DEPENDENCY_UNAVAILABLE"):
            await memory.CommitSegment(command(), "attempt", 1, descriptor(), memory.position(0), 0)
        receipt = await self.commit()
        self.assertEqual(await self.commit(), receipt)
        self.assertEqual(len(self.journal.operations), 2)
        with self.assertRaisesRegex(ValueError, "overlap"):
            await self.timeline.CommitSegment(command(segment="s2", key="c2"), "a2", 2,
                descriptor(), self.timeline.position(0), 1)
        with self.assertRaisesRegex(ValueError, "COMMAND_CONFLICT"):
            await self.timeline.CommitSegment(command(), "attempt", 1, descriptor(1280), self.timeline.position(0), 0)

    async def test_suspend_completion_requires_all_contiguous_ranges(self):
        identity = (await self.commit())["identity"]
        receipt = await self.timeline.SuspendAtBoundary(command("SUSPEND_AT_BOUNDARY", key="suspend"), "s1", 1)
        self.assertEqual(receipt["state"], "accepted")
        self.assertEqual(receipt["operationState"], "SUSPEND_REQUESTED")
        with self.assertRaisesRegex(ValueError, "proof missing"):
            await self.timeline.SegmentCompleted(identity, self.timeline.position(640), [])
        self.assertFalse(self.timeline.observe_sink_progress(identity, "preview", "audio", 320, 640))
        for media in ("audio", "video"):
            self.assertTrue(self.timeline.observe_sink_progress(identity, "preview", media, 0, 640))
        proof = await self.timeline.SegmentCompleted(identity, self.timeline.position(640), [])
        before = len(self.journal.operations)
        self.assertEqual(await self.timeline.SegmentCompleted(identity, self.timeline.position(640), []), proof)
        self.assertEqual(len(self.journal.operations), before)
        self.assertEqual(proof["event"], "BOUNDARY_SUSPENDED")
        self.assertFalse(proof["audienceAudible"])
        with self.assertRaisesRegex(ValueError, "suspension"):
            await self.timeline.CommitSegment(command(segment="s2", key="c2"), "a2", 2,
                descriptor(), self.timeline.position(640), self.timeline.revision)

    async def test_old_epoch_fenced_new_epoch_preserves_pts_and_replays(self):
        identity = (await self.commit())["identity"]
        cut = self.timeline.position(640)
        invalid = command("INVALIDATE_AFTER", key="invalidate")
        await self.timeline.InvalidateAfter(invalid, cut, "answer", 1)
        self.assertFalse(self.timeline.eligible(identity, 0, 640))
        begin = command("BEGIN_EPOCH", epoch=2, key="begin")
        receipt = await self.timeline.BeginEpoch(begin, 1, 2, cut, "answer")
        self.assertEqual(await self.timeline.BeginEpoch(begin, 1, 2, cut, "answer"), receipt)
        self.assertEqual(receipt["position"].ptsUs, 40000)
        self.assertFalse(self.timeline.eligible(identity, 0, 640))
        answer = command(epoch=2, segment="answer", key="a", lane="AUDIENCE_ANSWER")
        result = await self.timeline.CommitSegment(answer, "answer-attempt", 2, descriptor(), self.timeline.position(640), 3)
        self.assertTrue(self.timeline.eligible(result["identity"], 640, 1280))
        self.assertFalse(self.timeline.eligible(replace(result["identity"], runEpoch=2), 640, 1280))
        self.assertEqual(self.timeline.CurrentCommittedPTS("session", 1)["committedExclusiveEnd"].ptsUs, 80000)

    async def test_stop_during_journal_does_not_install_media(self):
        self.journal.pause = asyncio.Event()
        task = asyncio.create_task(self.commit())
        await asyncio.sleep(0)
        self.timeline.fence_now()
        self.journal.pause.set()
        with self.assertRaisesRegex(ValueError, "RUN_SEALED"): await task
        self.assertEqual(self.timeline.committed_end, 0)

    async def test_ack_loss_blocks_publication_and_invalid_cut_rejected(self):
        self.journal.fail = "COMMIT_INSTALLED"
        with self.assertRaises(ConnectionError): await self.commit()
        self.assertTrue(self.timeline.blocked)
        self.assertEqual(self.timeline.committed_end, 0)
        self.journal.fail = None
        self.timeline = MediaTimeline("session", 1, journal=self.journal)
        await self.commit()
        with self.assertRaisesRegex(ValueError, "retracted"):
            await self.timeline.InvalidateAfter(command("INVALIDATE_AFTER", key="cut"),
                self.timeline.position(320), "natural", 1)

    async def test_identity_integer_validation_ledger_and_receipt_bounds(self):
        for bad in (True, 0, -1, 1.1, 2**53):
            with self.assertRaises(ValueError): MediaTimeline("session", bad)
        self.timeline.policy = BufferPolicy(max_segments=1)
        await self.commit()
        with self.assertRaisesRegex(ValueError, "ledger full"):
            await self.timeline.CommitSegment(command(key="second", segment="second"), "attempt2", 2,
                descriptor(), self.timeline.position(640), 1)
        bad = command(key="bool"); bad["runEpoch"] = True
        with self.assertRaises(ValueError):
            await self.timeline.SuspendAtBoundary(bad, "s1", 1)

    async def test_speculative_media_is_bounded_and_not_sink_eligible_before_commit(self):
        buffer = SpeculativeMediaBuffer(self.timeline)
        identity = MediaIdentity("session", 1, 1, 1, "s1", "u1", Lane.NARRATION)
        chunk = TimedAudioChunk(1, 0, bytes(640), 16000, 1, identity, 0, 320)
        self.assertTrue(buffer.offer_audio(chunk))
        self.assertIsNone(buffer.take_audio())
        for i in range(74):
            self.assertTrue(buffer.offer_audio(replace(chunk, startSample=(i+1)*320, endSample=(i+2)*320)))
        self.assertFalse(buffer.offer_audio(chunk))
        self.assertEqual(buffer.samples, 24000)
        await self.commit(24000)
        self.assertEqual(buffer.take_audio(), chunk)
        self.timeline.fence_now()
        self.assertEqual(buffer.samples, 0)
        self.assertFalse(buffer.offer_audio(chunk))


class TrackTests(unittest.IsolatedAsyncioTestCase):
    async def test_underrun_holds_semantic_cursor_and_pts_continue(self):
        clock = AudioMasterClock()
        audio, video = _TimelineAudioTrack(clock), _TimelineVideoTrack(clock)
        try:
            await audio.push(AudioChunk(1, 0, bytes(640 * 2)))
            self.assertEqual((await audio.recv()).pts, 0)
            self.assertEqual((await video.recv()).pts, 0)
            self.assertEqual((await audio.recv()).pts, 960)
            source = clock.source_sample
            self.assertEqual((await audio.recv()).pts, 1920)
            self.assertEqual(clock.source_sample, source)
            self.assertEqual(clock.audio_underruns, 1)
            self.assertEqual((await video.recv()).pts, 3600)
        finally:
            audio.stop(); video.stop()

    async def test_video_early_wait_late_drop_and_exact_dispositions(self):
        clock = AudioMasterClock()
        audio, video = _TimelineAudioTrack(clock), _TimelineVideoTrack(clock)
        try:
            early = VideoFrame(1, 80000, 8, 8, bytes(192))
            await video.push(early)
            clock.advance(960, 320)
            await video.recv()
            self.assertIsNone(video.latest)
            self.assertEqual(video.queue.qsize(), 1)
            clock.advance(960 * 4, 1600)
            await video.recv()
            self.assertEqual(video.dispositions.get(early), "consumed")
            late = VideoFrame(1, 0, 8, 8, bytes(192))
            await video.push(late)
            clock.advance(960 * 12, 5440)
            await video.recv()
            self.assertEqual(video.dispositions.get(late), "dropped")
            self.assertEqual(video.consumed, 1)
            self.assertEqual(clock.video_late_drops, 1)
        finally:
            audio.stop(); video.stop()

    async def test_resampling_partial_padding_and_pending_bound(self):
        clock = AudioMasterClock()
        audio = _TimelineAudioTrack(clock)
        try:
            for sequence in range(321):
                await audio.push(AudioChunk(1, sequence, bytes(137 * 2), 44100))
                self.assertLess(len(audio.pending), 1920)
                if audio.queue.qsize(): await audio.recv()
            self.assertEqual(audio.resampler.output_count, 321 * 137 * 48000 // 44100)
            self.assertEqual(audio.source_cursor, audio.resampler.output_count * 16000 // 48000)
            await audio.flush()
            self.assertLess(audio.padding_samples, 960)
        finally: audio.stop()

    async def test_retained_image_hold_has_new_pts_but_no_new_semantic_progress(self):
        timeline = MediaTimeline("session", 1, journal=TestJournal())
        identity = (await timeline.CommitSegment(command(), "attempt", 1, descriptor(), timeline.position(0), 0))["identity"]
        clock = AudioMasterClock(); clock.timeline = timeline
        video = _TimelineVideoTrack(clock)
        video.sink_id = "preview"
        try:
            await video.push(TimedVideoFrame(1,0,8,8,bytes([40,120,200])*64,identity,0))
            clock.advance(1920,640)
            first = await video.recv()
            video.clear(2)
            self.assertIsNone(video.latest)
            clock.advance(1920)
            held = await video.recv()
            self.assertGreater(held.pts, first.pts)
            self.assertTrue((held.to_ndarray(format="rgb24")[0,0] == [40,120,200]).all())
            self.assertEqual(video.consumed,0)
            self.assertEqual(clock.source_sample,640)
        finally: video.stop()

    async def test_queue_bounds_stalled_consumer_and_force_wakes_waiter(self):
        audio = _TimelineAudioTrack(AudioMasterClock(policy=BufferPolicy(committed_ms=20, interruptible_ms=40)))
        try:
            await audio.push(AudioChunk(1, 0, bytes(320 * 2)))
            await audio.push(AudioChunk(1, 1, bytes(320 * 2)))
            with self.assertRaises(MediaDeliveryError):
                await audio.push(AudioChunk(1, 2, bytes(320 * 2)), stale_window=.04, poll_interval=.005)
            self.assertLessEqual(audio.queue.qsize(), 2)
            task = asyncio.create_task(audio.push(AudioChunk(1, 2, bytes(640 * 2))))
            await asyncio.sleep(.01)
            audio.clear(2)
            await asyncio.wait_for(task, .2)
            self.assertEqual(audio.queue.qsize(), 0)
        finally: audio.stop()

    async def test_old_epoch_injected_at_dequeue_is_discarded(self):
        journal = TestJournal()
        timeline = MediaTimeline("session", 1, journal=journal)
        identity = (await timeline.CommitSegment(command(), "attempt", 1, descriptor(), timeline.position(0), 0))["identity"]
        clock = AudioMasterClock(); clock.timeline = timeline
        audio, video = _TimelineAudioTrack(clock), _TimelineVideoTrack(clock)
        try:
            await audio.push(TimedAudioChunk(1, 0, bytes(640 * 2), 16000, 1, identity, 0, 640))
            stale = TimedVideoFrame(1, 0, 8, 8, bytes(192), identity, 0)
            await video.push(stale)
            cut = timeline.position(640)
            await timeline.BeginEpoch(command("BEGIN_EPOCH", epoch=2, key="begin"), 1, 2, cut, "answer")
            self.assertEqual(bytes((await audio.recv()).planes[0])[:1920], bytes(1920))
            self.assertEqual(audio.consumed, 0)
            await video.recv()
            self.assertEqual(video.consumed, 0)
            self.assertEqual(video.dispositions.get(stale), "fenced")
        finally: audio.stop(); video.stop()

    async def test_single_sink_block_does_not_stall_other_and_packet_duration_bound(self):
        class Sink:
            def __init__(self, blocked=False): self.blocked=blocked; self.received=[]
            async def start(self): pass
            async def stop(self): pass
            async def push_audio(self, chunk):
                if self.blocked: await asyncio.Event().wait()
                self.received.append(chunk)
            async def push_video(self, frame): pass
            async def drain(self, generation): pass
        slow, healthy = Sink(True), Sink()
        with patch.dict(os.environ, {"ASTRALIVE_MEDIA_TIMELINE_V2_ENABLED": "true"}):
            fanout = FanoutMediaOutput([("blocked",slow),("healthy",healthy)], audio_buffer_ms=40)
        await fanout.start()
        try:
            await asyncio.wait_for(fanout.push_audio(AudioChunk(1, 0, bytes(16000 * 2))), 4)
            await fanout.channels[1].audio.join()
            self.assertTrue(healthy.received)
            self.assertTrue(all(len(c.pcm) <= 640 for c in healthy.received))
            self.assertLessEqual(fanout.channels[0].audio.qsize(), 2)
        finally: await fanout.stop()

    async def test_rtmp_only_successful_pipe_write_advances_audio_master(self):
        with patch.dict(os.environ, {"ASTRALIVE_MEDIA_TIMELINE_V2_ENABLED": "true"}):
            sink = FFmpegRTMPMediaOutput(RTMPSettings(enabled=True, publish_url="rtmp://localhost/live/fixture", width=8, height=8))
        sink.running = True
        sink._audio_fd = 123
        sink.connection_incarnation = 1
        async def write(fd, payload):
            sink.write_failures += 1
            sink.running = False
        sink._write_fd = write
        await sink.push_audio(AudioChunk(1, 0, bytes(640)))
        await sink._timeline_audio_clock()
        self.assertEqual(sink.timeline_clock.output_samples, 0)
        self.assertEqual(sink.audio_consumed, 0)

    async def test_rtmp_reconnect_releases_old_audio_tick_wait(self):
        with patch.dict(os.environ, {"ASTRALIVE_MEDIA_TIMELINE_V2_ENABLED": "true"}):
            sink = FFmpegRTMPMediaOutput(RTMPSettings(enabled=True, publish_url="rtmp://localhost/live/fixture", width=8, height=8))
        sink.running = True; sink.connection_incarnation = 1; sink._video_tick = 1000
        writes = []
        async def write(fd, payload):
            writes.append(sink.connection_incarnation); sink.running = False
        sink._write_fd = write
        task = asyncio.create_task(sink._timeline_video_clock())
        await asyncio.sleep(.01)
        sink.connection_incarnation = 2; sink._video_tick = 0
        sink.timeline_clock.output_samples = 960
        sink.timeline_clock.changed.set()
        await asyncio.wait_for(task, .3)
        self.assertEqual(writes, [2])

    async def test_successful_drain_retires_attempt_binding(self):
        from unittest.mock import AsyncMock
        from gpu_worker.validated.runtime_avatar import ConsumptionMediaOutput
        with patch.dict(os.environ, {"ASTRALIVE_MEDIA_TIMELINE_V2_ENABLED": "true"}):
            output = BoundConsumptionMediaOutput(SimpleNamespace(), SimpleNamespace())
        output.timeline_bindings = {1: object()}
        with patch.object(ConsumptionMediaOutput, "drain", AsyncMock()):
            await output.drain(1)
        self.assertEqual(output.timeline_bindings, {})

    async def test_epoch_fence_during_pipe_write_cannot_ack_current_epoch(self):
        timeline = MediaTimeline("session", 1, journal=TestJournal())
        identity = (await timeline.CommitSegment(command(), "attempt", 1, descriptor(), timeline.position(0), 0))["identity"]
        with patch.dict(os.environ, {"ASTRALIVE_MEDIA_TIMELINE_V2_ENABLED": "true"}):
            sink = FFmpegRTMPMediaOutput(RTMPSettings(enabled=True, publish_url="rtmp://localhost/live/fixture", width=8, height=8))
        sink.bind_timeline(timeline)
        sink.running = True; sink._audio_fd = 123; sink.connection_incarnation = 1
        started, release = asyncio.Event(), asyncio.Event()
        calls = 0
        async def write(fd, payload):
            nonlocal calls
            calls += 1
            if calls == 1:
                started.set(); await release.wait()
            else: sink.running = False
        sink._write_fd = write
        await sink.push_audio(TimedAudioChunk(1,0,bytes(640),16000,1,identity,0,320))
        task = asyncio.create_task(sink._timeline_audio_clock())
        await started.wait()
        self.assertEqual(sink.timeline_progress()["inFlight"]["audio"]["identity"]["timelineEpoch"], 1)
        await timeline.BeginEpoch(command("BEGIN_EPOCH", epoch=2, key="begin"),1,2,timeline.position(640),"answer")
        release.set(); await asyncio.wait_for(task,.5)
        self.assertEqual(sink.audio_consumed,0)
        self.assertEqual(sink.cancelled_in_flight,1)

    async def test_rtmp_fence_holds_consumed_image_not_unconfirmed_write(self):
        timeline = MediaTimeline("session", 1, journal=TestJournal())
        identity = (await timeline.CommitSegment(command(), "attempt", 1, descriptor(), timeline.position(0), 0))["identity"]
        with patch.dict(os.environ, {"ASTRALIVE_MEDIA_TIMELINE_V2_ENABLED": "true"}):
            sink = FFmpegRTMPMediaOutput(RTMPSettings(enabled=True, publish_url="rtmp://localhost/live/fixture", width=8, height=8))
        sink.bind_timeline(timeline);sink.running=True;sink._video_fd=123
        held=bytes([20,40,80])*64
        sink._held_video=held
        await sink.push_video(TimedVideoFrame(1,0,8,8,bytes([200,100,20])*64,identity,0))
        sink.timeline_clock.advance(1920,640)
        started,release=asyncio.Event(),asyncio.Event()
        async def write(fd,payload):started.set();await release.wait();sink.running=False
        sink._write_fd=write
        task=asyncio.create_task(sink._timeline_video_clock())
        await started.wait()
        await timeline.BeginEpoch(command("BEGIN_EPOCH",epoch=2,key="begin"),1,2,timeline.position(640),"answer")
        self.assertEqual(sink._latest_video,held)
        release.set();await asyncio.wait_for(task,.5)
        self.assertEqual(sink._held_video,held)
        self.assertEqual(sink.video_consumed,0)

    async def test_all_sink_dropped_worker_frame_never_commits_published_pose_credit(self):
        from unittest.mock import AsyncMock
        credits=[];logs=[]
        async def consumed(packet): credits.append(packet["frame_sequence"])
        with patch.dict(os.environ, {"ASTRALIVE_MEDIA_TIMELINE_V2_ENABLED": "true"}):
            sink = FFmpegRTMPMediaOutput(RTMPSettings(enabled=True, publish_url="rtmp://localhost/live/fixture", width=8, height=8))
            sink.running=True; sink._process=SimpleNamespace(returncode=None)
            avatar=SimpleNamespace(running=True,generation_id=1,link=SimpleNamespace(consumed=consumed),cached_idle=None,
                                   pipeline=SimpleNamespace(degrade=AsyncMock()),log=lambda event,**kw: logs.append(event))
            output=BoundConsumptionMediaOutput(sink,avatar)
        frame=VideoFrame(1,0,8,8,bytes(192))
        output.metadata[id(frame)]={"source":"GPU_INFERENCE","generation_id":42,"frame_sequence":0,"activity":"TALKING"}
        await output.push_video(frame)
        sink._dispose_video(frame,"dropped")
        await asyncio.sleep(.02)
        self.assertEqual(credits,[])
        self.assertIn("FrameDiscardedWithoutCredit",logs)
        self.assertNotIn("FrameActuallyConsumed",logs)
        avatar.pipeline.degrade.assert_awaited_once()
        self.assertEqual(sink.video_consumed,0)
        avatar.running=False
        await asyncio.gather(*tuple(output.acks))

    async def test_bound_ledger_does_not_authorize_native_idle_after_segment(self):
        from unittest.mock import AsyncMock
        sink = SimpleNamespace(timeline=object(), video_delivery_position=lambda: (1, 0), drain=AsyncMock())
        avatar = SimpleNamespace(speaking=False, generation_id=1, _stop_idle=AsyncMock())
        with patch.dict(os.environ, {"ASTRALIVE_MEDIA_TIMELINE_V2_ENABLED": "true"}):
            output = BoundConsumptionMediaOutput(sink, avatar)
        self.assertFalse(output.has_peer())
        avatar.speaking = True
        self.assertTrue(output.has_peer())
        await output.drain(1)
        avatar._stop_idle.assert_awaited_once()
        sink.drain.assert_awaited_once_with(1)
        sink.timeline = None
        avatar.speaking = False
        self.assertTrue(output.has_peer())

    async def test_bound_v2_does_not_wait_stalled_preview_admission(self):
        from unittest.mock import AsyncMock
        queued = asyncio.Queue(); queued.put_nowait(object())
        peer = SimpleNamespace(connection=SimpleNamespace(connectionState="connected"),
                               video=SimpleNamespace(enqueued=0, consumed=0, generation_id=1))
        web = SimpleNamespace(peers=[peer])
        channel = SimpleNamespace(name="webrtc", output=web, audio=queued, video=queued)
        fanout = SimpleNamespace(channels=[channel], push_audio=AsyncMock(), push_video=AsyncMock())
        avatar = SimpleNamespace(running=True, generation_id=1, pipeline=object(), cached_idle=None,
                                 link=object(), log=lambda *a,**k: None)
        with patch.dict(os.environ, {"ASTRALIVE_MEDIA_TIMELINE_V2_ENABLED": "true"}):
            output = BoundConsumptionMediaOutput(fanout, avatar)
        await asyncio.wait_for(output.push_audio(AudioChunk(1,0,bytes(640))), .1)
        frame=VideoFrame(1,0,8,8,bytes(192))
        output.metadata[id(frame)]={"source":"GPU_INFERENCE","generation_id":42,"frame_sequence":0,"activity":"TALKING"}
        await asyncio.wait_for(output.push_video(frame), .1)
        avatar.running=False
        await asyncio.gather(*tuple(output.acks))
        fanout.push_audio.assert_awaited_once();fanout.push_video.assert_awaited_once()


if __name__ == "__main__": unittest.main()
