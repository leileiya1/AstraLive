"""Existing aiortc media semantics, with a guard installed BEFORE addTrack."""

import asyncio
from uuid import uuid4

from aiortc import RTCConfiguration, RTCPeerConnection, RTCSessionDescription

from runtime.app.webrtc_media import WebRTCMediaOutput, _AudioTrack, _Peer, _VideoTrack


class GuardedAudio(_AudioTrack):
    async def recv(self):
        self.guardian_check()
        frame = await super().recv()
        self.guardian_check()
        return frame


class GuardedVideo(_VideoTrack):
    async def recv(self):
        self.guardian_check()
        frame = await super().recv()
        self.guardian_check()
        return frame


class GuardianWebRTCOutput(WebRTCMediaOutput):
    def __init__(self, check, **kwargs):
        super().__init__(**kwargs)
        self.guardian_check = check

    async def create_answer(self, offer_sdp):
        self.guardian_check()
        if not self.running:
            raise RuntimeError("closed guardian peer")
        # Local dedicated acceptance has no public STUN/TURN dependency. Agent 4
        # must supply an approved ICE transport before external viewer release.
        pc = RTCPeerConnection(RTCConfiguration(iceServers=[]))
        audio = GuardedAudio(self.audio_buffer_ms, self.max_audio_buffer_ms)
        video = GuardedVideo(self.fps, self.video_buffer_ms, self.max_video_buffer_ms)
        audio.guardian_check = video.guardian_check = self.guardian_check
        audio.generation_id = video.generation_id = self.generation_id
        peer = _Peer("peer_" + uuid4().hex, pc, audio, video)
        self.peers.add(peer)
        pc.addTrack(audio)
        pc.addTrack(video)

        @pc.on("connectionstatechange")
        async def changed():
            if pc.connectionState in {"failed", "disconnected", "closed"}:
                await self._evict(peer, "connection_state")

        try:
            await pc.setRemoteDescription(RTCSessionDescription(offer_sdp, "offer"))
            await pc.setLocalDescription(await pc.createAnswer())
            self.guardian_check()
            if not self.running or peer not in self.peers:
                raise RuntimeError("closed guardian peer")
            return pc.localDescription.sdp
        except BaseException:
            self.peers.discard(peer)
            audio.stop()
            video.stop()
            await asyncio.wait_for(pc.close(), self.peer_close_timeout)
            raise
