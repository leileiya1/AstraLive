"""Owned-process crash fixture. CPU_SIMULATION only; no real LLM/TTS/GPU/audio sink."""
import asyncio
import os
from app.main import create_app
from app.config import Settings
from app.events import envelope
from app.providers import MockLLMProvider, MockTTSProvider, MockAvatarEngine, MockMediaOutput


class SlowTTS(MockTTSProvider):
    async def synthesize_stream(self, text, voice, ctx):
        # Make the physical-side-effect window observable and long enough for SIGKILL.
        for _ in range(25):
            async for chunk in super().synthesize_stream(text, voice, ctx):
                await asyncio.sleep(.02)
                await app.state.publisher.publish(envelope("RUNTIME_WARNING", ctx.session_id, ctx.trace_id, ctx.utterance_id, {"code": "CPU_SIMULATION"}))
                yield chunk


class CountingMedia(MockMediaOutput):
    async def push_audio(self, chunk):
        # This is an observable synthetic sink handoff, never a speaker/audience claim.
        with open(os.environ["DURABILITY_CPU_EFFECT_FILE"], "a") as evidence:
            evidence.write(f"CPU_SIMULATION {chunk.generation_id} {chunk.sequence} {len(chunk.pcm)}\n")
            evidence.flush()
            os.fsync(evidence.fileno())
        await super().push_audio(chunk)


app = create_app(Settings(), factories=(MockLLMProvider, SlowTTS, MockAvatarEngine, CountingMedia))
