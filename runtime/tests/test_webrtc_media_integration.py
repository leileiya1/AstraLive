"""Opt-in local WebRTC peer and HTTP signaling tests."""
import asyncio
import os
import unittest
from app.providers import AudioChunk, VideoFrame


@unittest.skipUnless(os.getenv("RUN_WEBRTC_INTEGRATION") == "1", "Set RUN_WEBRTC_INTEGRATION=1")
class WebRTCMediaIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_repeated_drain_reconnect_and_stale_peer(self):
        from aiortc import RTCPeerConnection, RTCSessionDescription
        from app.webrtc_media import WebRTCMediaOutput, _AudioTrack, _VideoTrack, _Peer

        class StalledConnection:
            connectionState = "connected"
            iceConnectionState = "connected"

            async def close(self):
                self.connectionState = "closed"

        output = WebRTCMediaOutput()
        output.stale_window = 2.0
        await output.start()
        try:
            for generation in (1, 2):
                client = RTCPeerConnection()
                tracks = {}

                @client.on("track")
                def on_track(track):
                    tracks[track.kind] = track

                client.addTransceiver("audio", direction="recvonly")
                client.addTransceiver("video", direction="recvonly")
                receivers = []
                try:
                    await client.setLocalDescription(await client.createOffer())
                    answer = await output.create_answer(client.localDescription.sdp)
                    await client.setRemoteDescription(RTCSessionDescription(sdp=answer, type="answer"))
                    for _ in range(100):
                        if client.connectionState == "connected" and set(tracks) == {"audio", "video"}:
                            break
                        await asyncio.sleep(0.1)
                    self.assertEqual(client.connectionState, "connected")
                    async def receive_forever(track):
                        while True:
                            await track.recv()

                    receivers = [asyncio.create_task(receive_forever(tracks[kind])) for kind in ("audio", "video")]
                    healthy = next(iter(output.peers))
                    self.assertEqual((healthy.audio.generation_id, healthy.video.generation_id), (generation, generation))
                    self.assertEqual((healthy.audio.enqueued, healthy.audio.consumed, healthy.video.enqueued, healthy.video.consumed), (0, 0, 0, 0))
                    for cycle in range(3):
                        if generation == 1 and cycle == 2:
                            stalled = _Peer("stalled", StalledConnection(), _AudioTrack(), _VideoTrack())
                            output.peers.add(stalled)
                        await output.push_audio(AudioChunk(generation, cycle, b"\x01\x00" * 960, 48000, 1))
                        await output.push_video(VideoFrame(generation, cycle * 20000, 256, 256, bytes([220, 20, 20]) * (256 * 256)))
                        await asyncio.wait_for(output.drain(generation), 3)
                        self.assertEqual((healthy.audio.queue.qsize(), healthy.video.queue.qsize()), (0, 0))
                        self.assertEqual(healthy.audio.enqueued, healthy.audio.consumed)
                        self.assertEqual(healthy.video.enqueued, healthy.video.consumed)
                    if generation == 1:
                        self.assertNotIn(stalled, output.peers)
                finally:
                    for receiver in receivers:
                        receiver.cancel()
                    await asyncio.gather(*receivers, return_exceptions=True)
                    await client.close()
                    for _ in range(100):
                        if healthy not in output.peers:
                            break
                        await asyncio.sleep(0.01)
                    self.assertNotIn(healthy, output.peers)
                if generation == 1:
                    await output.interrupt(2)
        finally:
            await output.stop()

    async def test_audio_track_waits_for_consumer_when_buffer_is_full(self):
        from app.webrtc_media import _AudioTrack
        track = _AudioTrack()
        track.queue = asyncio.Queue(maxsize=1)
        chunk = AudioChunk(1, 0, b'\x01\x00' * (track.frame_samples * 2), track.sample_rate, 1)
        producer = asyncio.create_task(track.push(chunk))
        try:
            await asyncio.sleep(0)
            self.assertFalse(producer.done())
            self.assertEqual(track.queue.qsize(), 1)
            await track.recv()
            await asyncio.wait_for(producer, 1)
            self.assertEqual(track.queue.qsize(), 1)
        finally:
            producer.cancel()
            track.stop()

    async def test_http_offer_returns_complete_answer_and_stop_closes_peer(self):
        import httpx
        from aiortc import RTCPeerConnection, RTCSessionDescription
        from app.config import Settings
        from app.events import MemoryEventPublisher
        from app.main import create_app
        from app.providers import MockAvatarEngine, MockLLMProvider, MockTTSProvider
        from app.webrtc_media import WebRTCMediaOutput
        app = create_app(Settings(mock_media=False), MemoryEventPublisher(),
                         (MockLLMProvider, MockTTSProvider, MockAvatarEngine, WebRTCMediaOutput))
        client_peer = RTCPeerConnection()
        client_peer.addTransceiver("audio", direction="recvonly")
        client_peer.addTransceiver("video", direction="recvonly")
        create = {"commandId": "cmd_1", "traceId": "trace_1", "sessionId": "session_http", "avatar": {"avatarId": "avatar_1", "engine": "MOCK"}, "voice": {"voiceId": "voice_1", "provider": "MOCK"}, "config": {"fps": 25, "preview": {"type": "WEBRTC"}}, "context": {"roomId": "room_1", "systemPrompt": "欢迎观众。"}}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://runtime") as client:
            try:
                self.assertEqual((await client.post("/internal/v1/sessions", json=create)).status_code, 202)
                for _ in range(100):
                    if app.state.manager.get_session("session_http").state == "READY":
                        break
                    await asyncio.sleep(0.01)
                self.assertEqual((await client.post("/internal/v1/sessions/session_http/start", json={"commandId": "cmd_2", "traceId": "trace_1"})).status_code, 202)
                output = app.state.manager.get_session("session_http").media_output
                bad = await client.post("/internal/v1/sessions/session_http/webrtc/offer", json={"type": "offer", "sdp": "invalid sdp"})
                self.assertEqual((bad.status_code, bad.json()["code"]), (500, "WEBRTC_FAILED"))
                self.assertEqual(len(output.peers), 0)
                await client_peer.setLocalDescription(await client_peer.createOffer())
                response = await client.post("/internal/v1/sessions/session_http/webrtc/offer", json={"type": "offer", "sdp": client_peer.localDescription.sdp})
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()["type"], "answer")
                self.assertIn("a=candidate:", response.json()["sdp"])
                await client_peer.setRemoteDescription(RTCSessionDescription(sdp=response.json()["sdp"], type="answer"))
                self.assertEqual(len(output.peers), 1)
                self.assertEqual((await client.post("/internal/v1/sessions/session_http/stop", json={"commandId": "cmd_3", "traceId": "trace_1"})).status_code, 202)
                self.assertEqual(len(output.peers), 0)
            finally:
                await client_peer.close()
                await app.state.manager.close()

    async def test_local_peer_receives_audio_and_video(self):
        import numpy as np
        from aiortc import RTCPeerConnection, RTCSessionDescription
        from app.webrtc_media import WebRTCMediaOutput
        output = WebRTCMediaOutput(fps=25)
        await output.start()
        client = RTCPeerConnection()
        tracks = {}

        @client.on("track")
        def on_track(track):
            tracks[track.kind] = track

        client.addTransceiver("audio", direction="recvonly")
        client.addTransceiver("video", direction="recvonly")
        try:
            offer = await client.createOffer()
            await client.setLocalDescription(offer)
            answer_sdp = await output.create_answer(client.localDescription.sdp)
            await client.setRemoteDescription(RTCSessionDescription(sdp=answer_sdp, type="answer"))
            for _ in range(100):
                if client.connectionState == "connected" and set(tracks) == {"audio", "video"}:
                    break
                await asyncio.sleep(0.1)
            self.assertEqual(client.connectionState, "connected")
            self.assertEqual(set(tracks), {"audio", "video"})
            signal = (np.sin(np.linspace(0, 1000, 22050)) * 10000).astype("<i2").tobytes()
            await output.push_audio(AudioChunk(1, 0, signal, 22050, 1))
            await output.push_video(VideoFrame(1, 0, 256, 256, bytes((220, 20, 20)) * (256 * 256)))

            async def received_sound():
                for _ in range(100):
                    frame = await asyncio.wait_for(tracks["audio"].recv(), 2)
                    if np.max(np.abs(frame.to_ndarray().astype(np.int32))) > 100:
                        return True
                return False

            async def received_red():
                for _ in range(100):
                    frame = await asyncio.wait_for(tracks["video"].recv(), 2)
                    pixel = frame.to_ndarray(format="rgb24")[0, 0]
                    if int(pixel[0]) > 100 and int(pixel[0]) > int(pixel[1]) * 2:
                        return True
                return False

            sound, red = await asyncio.gather(received_sound(), received_red())
            self.assertTrue(sound)
            self.assertTrue(red)
            await output.interrupt(2)
            self.assertEqual(output.generation_id, 2)
            await output.push_audio(AudioChunk(1, 1, signal, 22050, 1))
            self.assertTrue(all(peer.audio.queue.empty() for peer in output.peers))
        finally:
            await client.close()
            for _ in range(100):
                if not output.peers:
                    break
                await asyncio.sleep(0.01)
            self.assertEqual(len(output.peers), 0)
            await output.stop()
            self.assertEqual(len(output.peers), 0)
