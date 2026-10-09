"""Opt-in cumulative real-provider integration using in-process SDP exchange."""
import asyncio
import os
import unittest
import httpx
from app.config import Settings
from app.events import MemoryEventPublisher
from app.main import create_app


@unittest.skipUnless(os.getenv("RUN_FULL_REAL_CHAIN") == "1", "Set RUN_FULL_REAL_CHAIN=1")
class FullRealChainTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_llm_tts_avatar_webrtc(self):
        import numpy as np
        from aiortc import RTCPeerConnection, RTCSessionDescription

        pub = MemoryEventPublisher()
        app = create_app(Settings(mock_llm=False, mock_tts=False, mock_avatar=False, mock_media=False), pub)
        peer = RTCPeerConnection()
        tracks = {}

        @peer.on("track")
        def on_track(track):
            tracks[track.kind] = track

        peer.addTransceiver("audio", direction="recvonly")
        peer.addTransceiver("video", direction="recvonly")
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://runtime") as client:
                create = {"commandId": "cmd_full_1", "traceId": "trace_full_1", "sessionId": "session_full_1", "avatar": {"avatarId": "avatar_full_1", "engine": "LIGHTWEIGHT"}, "voice": {"voiceId": "voice_full_1", "provider": "SHERPA_ONNX"}, "config": {"fps": 25, "preview": {"type": "WEBRTC"}}, "context": {"roomId": "room_1", "systemPrompt": "你是直播间主持人。"}}
                self.assertEqual((await client.post("/internal/v1/sessions", json=create)).status_code, 202)
                for _ in range(100):
                    if app.state.manager.get_session("session_full_1").state == "READY":
                        break
                    await asyncio.sleep(0.01)
                self.assertEqual((await client.post("/internal/v1/sessions/session_full_1/start", json={"commandId": "cmd_full_2", "traceId": "trace_full_1"})).status_code, 202)
                output = app.state.manager.get_session("session_full_1").media_output
                offer = await peer.createOffer()
                await peer.setLocalDescription(offer)
                answer = await output.create_answer(peer.localDescription.sdp)
                await peer.setRemoteDescription(RTCSessionDescription(sdp=answer, type="answer"))
                for _ in range(100):
                    if peer.connectionState == "connected" and set(tracks) == {"audio", "video"}:
                        break
                    await asyncio.sleep(0.1)
                self.assertEqual(peer.connectionState, "connected")
                speak = {"commandId": "cmd_full_3", "traceId": "trace_full_1", "utteranceId": "utt_full_1", "text": "只回复四个字：欢迎光临。", "priority": 100, "interruptPolicy": "NONE", "source": "OPERATOR", "voice": {"voiceId": "voice_full_1"}}
                self.assertEqual((await client.post("/internal/v1/sessions/session_full_1/utterances", json=speak)).status_code, 202)

                async def get_non_silent_audio():
                    for _ in range(250):
                        frame = await asyncio.wait_for(tracks["audio"].recv(), 2)
                        if np.max(np.abs(frame.to_ndarray().astype(np.int32))) > 100:
                            return True
                    return False

                async def get_avatar_video():
                    for _ in range(150):
                        frame = await asyncio.wait_for(tracks["video"].recv(), 2)
                        pixel = frame.to_ndarray(format="rgb24")[0, 0]
                        if int(pixel[0]) > 100:
                            return True
                    return False

                received_audio, received_video = await asyncio.gather(get_non_silent_audio(), get_avatar_video())
                self.assertTrue(received_audio)
                self.assertTrue(received_video)
                for _ in range(100):
                    names = [e["eventType"] for e in pub.events]
                    if "UTTERANCE_COMPLETED" in names or "UTTERANCE_FAILED" in names:
                        break
                    await asyncio.sleep(0.1)
                self.assertIn("UTTERANCE_COMPLETED", names)
                self.assertNotIn("RUNTIME_WARNING", names)
                self.assertEqual((await client.post("/internal/v1/sessions/session_full_1/stop", json={"commandId": "cmd_full_4", "traceId": "trace_full_1"})).status_code, 202)
        finally:
            await peer.close()
            await app.state.manager.close()
