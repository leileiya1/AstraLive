import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncIterator, Protocol
import httpx
from .models import AvatarConfig, SessionConfig, SpeechPlan, VoiceConfig


@dataclass(frozen=True)
class GenerationContext:
    generation_id: int
    trace_id: str
    session_id: str
    utterance_id: str


@dataclass(frozen=True)
class AudioChunk:
    generation_id: int
    sequence: int
    pcm: bytes
    sample_rate: int = 16000
    channels: int = 1


@dataclass(frozen=True)
class VideoFrame:
    generation_id: int
    pts_us: int
    width: int
    height: int
    rgb: bytes


@dataclass(frozen=True)
class LLMRequest:
    text: str
    system_prompt: str
    fact_context: str


class LLMProvider(Protocol):
    async def stream(self, request: LLMRequest) -> AsyncIterator[str]: ...


class TTSProvider(Protocol):
    async def synthesize_stream(self, text: str, voice: VoiceConfig, ctx: GenerationContext) -> AsyncIterator[AudioChunk]: ...


class AvatarEngine(Protocol):
    def configure_session(self, config: SessionConfig) -> None: ...
    async def prepare(self, config: AvatarConfig) -> None: ...
    async def start(self) -> None: ...
    async def push_audio(self, chunk: AudioChunk) -> list[VideoFrame]: ...
    async def interrupt(self, generation_id: int) -> None: ...
    async def stop(self) -> None: ...


class MediaOutput(Protocol):
    def configure_session(self, config: SessionConfig) -> None: ...
    async def start(self) -> None: ...
    async def push_audio(self, chunk: AudioChunk) -> None: ...
    async def push_video(self, frame: VideoFrame) -> None: ...
    async def drain(self, generation_id: int) -> None: ...
    async def interrupt(self, generation_id: int) -> None: ...
    async def stop(self) -> None: ...


class MediaDeliveryError(RuntimeError):
    """Media could not be delivered to a playback peer."""


class MockLLMProvider:
    async def stream(self, request: LLMRequest) -> AsyncIterator[str]:
        for part in request.text.split(" "):
            await asyncio.sleep(0)
            yield part + " "


class OpenAICompatibleLLMProvider:
    """Streaming chat completion adapter; yields only spoken content deltas."""

    def __init__(self, base_url: str, api_key: str, model: str, max_tokens: int = 256,
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        if not (base_url and api_key and model):
            raise ValueError("LLM base URL, API key and model are required")
        self.base_url, self.api_key, self.model = base_url.rstrip("/"), api_key, model
        self.max_tokens = max_tokens
        self.transport = transport
        self.client: httpx.AsyncClient | None = None

    @asynccontextmanager
    async def _stream_client(self):
        if self.client is not None:
            yield self.client
        else:
            async with httpx.AsyncClient(timeout=httpx.Timeout(60, connect=10), transport=self.transport, trust_env=False, follow_redirects=False) as client:
                yield client

    async def stream(self, request: LLMRequest) -> AsyncIterator[str]:
        import json
        done = False
        terminal_finish = False
        async with self._stream_client() as client:
            async with client.stream(
                "POST", f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                json={"model": self.model, "stream": True, "max_tokens": self.max_tokens,
                      "messages": [
                          {"role": "system", "content": getattr(request, "system_prompt", "")},
                          {"role": "system", "content": "只回复简洁自然的口语。商品库存、价格等动态事实只能依据已提供的 Tool Facts；缺失或不可用时直接说明暂时查不到，不得猜测。"},
                          {"role": "system", "content": "Tool Facts:\n" + getattr(request, "fact_context", "商品动态事实不可用。")},
                          {"role": "user", "content": request.text},
                      ]},
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        if not terminal_finish:
                            raise RuntimeError("LLM stream sent [DONE] without terminal finish")
                        done = True
                        break
                    if not data:
                        continue
                    packet = json.loads(data)
                    if packet.get("error"):
                        raise RuntimeError("LLM stream returned an error")
                    for choice in packet.get("choices", []):
                        finish_reason = choice.get("finish_reason")
                        if finish_reason == "stop":
                            terminal_finish = True
                        elif finish_reason is not None:
                            raise RuntimeError(f"LLM stream ended with {finish_reason}")
                        content = choice.get("delta", {}).get("content")
                        if content:
                            yield content
        if not done and not terminal_finish:
            raise RuntimeError("LLM stream ended without terminal finish")


class MockTTSProvider:
    async def synthesize_stream(self, text: str, voice: VoiceConfig, ctx: GenerationContext) -> AsyncIterator[AudioChunk]:
        for sequence, _ in enumerate(text.encode("utf-8")[::32] or b"x"):
            await asyncio.sleep(0)
            yield AudioChunk(ctx.generation_id, sequence, b"\0" * 320)


class MockAvatarEngine:
    def __init__(self) -> None:
        self.generation_id = 1
        self.received: list[AudioChunk] = []

    def configure_session(self, config: SessionConfig) -> None: pass
    async def prepare(self, config: AvatarConfig) -> None: pass
    async def start(self) -> None: pass
    async def push_audio(self, chunk: AudioChunk) -> list[VideoFrame]:
        if chunk.generation_id == self.generation_id:
            self.received.append(chunk)
        return []
    async def interrupt(self, generation_id: int) -> None:
        self.generation_id = generation_id
        self.received.clear()
    async def stop(self) -> None:
        self.received.clear()


class MockMediaOutput:
    def __init__(self) -> None:
        self.generation_id = 1
        self.received: list[AudioChunk] = []
        self.video_frames: list[VideoFrame] = []

    def configure_session(self, config: SessionConfig) -> None: pass
    async def start(self) -> None: pass
    async def push_audio(self, chunk: AudioChunk) -> None:
        if chunk.generation_id == self.generation_id:
            self.received.append(chunk)
    async def push_video(self, frame: VideoFrame) -> None:
        if frame.generation_id == self.generation_id:
            self.video_frames.append(frame)
            if len(self.video_frames) > 100:
                del self.video_frames[0]
    async def drain(self, generation_id: int) -> None: pass
    async def interrupt(self, generation_id: int) -> None:
        self.generation_id = generation_id
        self.received.clear()
        self.video_frames.clear()
    async def stop(self) -> None:
        self.received.clear()
        self.video_frames.clear()
