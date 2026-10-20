"""Agent 4 seam. Runtime holds only scoped IPC identity; no publishing resources.

bind/install/Stop are management operations on a different client/token. This
adapter never invents a generation, permit TTL, fence proof or drain receipt.
It does not expose legacy RTMP credit counters; Agent 4 must preserve existing
Worker credit via its current independent consumption adapter.
"""

import base64

import httpx

from .providers import MediaDeliveryError


class GuardianMediaOutput:
    def __init__(
        self, socket_path, token, attempt, *, sample_rate=16000, width=256, height=256
    ):
        self.attempt, self.sample_rate = attempt, sample_rate
        self.width, self.height = width, height
        self.generation_id = attempt["generation"]
        self.sequence = 0
        self.client = httpx.AsyncClient(
            base_url="http://guardian",
            transport=httpx.AsyncHTTPTransport(uds=socket_path),
            headers={"Authorization": "Bearer " + token},
            timeout=1,
            trust_env=False,
            follow_redirects=False,
        )
        self.running = False
        self.last_drain = None

    def configure_session(self, config):
        pass  # Media format is operator-owned; a Session cannot alter it.

    async def call(self, operation, payload=None):
        response = await self.client.post(
            "/guardian/v1/" + operation,
            json={"attempt": self.attempt} | (payload or {}),
            # finish has a bounded 2s independent decode/cleanup budget; it
            # does not extend the <=1s media Permit or any Worker timeout.
            timeout=3 if operation == "finish" else 1,
        )
        if response.status_code != 200:
            raise MediaDeliveryError("Guardian rejected media delivery")
        return response.json()

    async def start(self):
        self.running = True  # CONTROL must already have installed/bound this attempt.

    async def renew(self, permit_id):
        await self.call("renew", {"permitId": permit_id})

    async def push_audio(self, chunk):
        if (
            not self.running
            or chunk.generation_id != self.generation_id
            or chunk.sample_rate != self.sample_rate
            or chunk.channels != 1
        ):
            raise MediaDeliveryError("Guardian audio identity/format mismatch")
        # Chunk.sequence may reset per TTS sentence; IPC has its own contiguous
        # ordinal. PCM bytes and the existing Worker wire are unchanged.
        await self.call(
            "media",
            {
                "kind": "audio",
                "sequence": self.sequence,
                "payload": base64.b64encode(chunk.pcm).decode(),
            },
        )
        self.sequence += 1

    async def push_video(self, frame):
        if (
            not self.running
            or frame.generation_id != self.generation_id
            or (frame.width, frame.height) != (self.width, self.height)
        ):
            raise MediaDeliveryError("Guardian video identity/format mismatch")
        await self.call(
            "media",
            {
                "kind": "video",
                "pts_us": frame.pts_us,
                "payload": base64.b64encode(frame.rgb).decode(),
            },
        )

    async def drain(self, generation_id):
        if generation_id != self.generation_id:
            raise MediaDeliveryError("Guardian generation mismatch")
        evidence = await self.call("finish")
        if evidence.get("state") != "LOCAL_MEDIA_DRAINED":
            raise MediaDeliveryError("Guardian drain unproven")
        self.last_drain = evidence

    async def create_answer(self, offer_sdp):
        return (await self.call("offer", {"sdp": offer_sdp}))["sdp"]

    async def interrupt(self, generation_id):
        # Runtime cannot grant a new generation. CONTROL closes/rebinds first.
        if generation_id != self.generation_id:
            self.running = False
            raise MediaDeliveryError("Guardian CONTROL rebind required")

    async def stop(self):
        self.running = False
        await self.client.aclose()  # Actual Stop belongs to authenticated CONTROL.
