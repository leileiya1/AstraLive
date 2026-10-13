"""A small 2D audio-reactive avatar with audio-clocked RGB frames."""
import asyncio
import math
from pathlib import Path
from PIL import Image, ImageDraw
import numpy as np
from .models import AvatarConfig, SessionConfig
from .providers import AudioChunk, VideoFrame


class LightweightAvatarEngine:
    def __init__(self, image_path: str | None = None, fps: int = 25, size: int = 512):
        self.image_path = image_path
        self.fps = fps
        self.size = size
        self.generation_id = 1
        self.audio_us = 0
        self.next_frame_us = 0
        self.base: Image.Image | None = None
        self.running = False

    def configure_session(self, config: SessionConfig) -> None:
        self.fps = config.fps

    async def prepare(self, config: AvatarConfig) -> None:
        if self.image_path:
            source = Image.open(Path(self.image_path).expanduser()).convert("RGB")
            self.base = source.resize((self.size, self.size))
        else:
            image = Image.new("RGB", (self.size, self.size), "#dce8f0")
            draw = ImageDraw.Draw(image)
            s = self.size
            draw.ellipse((s*.18, s*.08, s*.82, s*.82), fill="#f1c9aa")
            draw.pieslice((s*.15, s*.03, s*.85, s*.48), 180, 360, fill="#334659")
            draw.ellipse((s*.35, s*.39, s*.39, s*.44), fill="#273849")
            draw.ellipse((s*.61, s*.39, s*.65, s*.44), fill="#273849")
            draw.polygon([(s*.18,s*.83),(s*.82,s*.83),(s*.98,s),(s*.02,s)], fill="#375d72")
            self.base = image

    async def start(self) -> None:
        if self.base is None:
            raise RuntimeError("Avatar must be prepared before start")
        self.running = True

    async def push_audio(self, chunk: AudioChunk) -> list[VideoFrame]:
        if not self.running or chunk.generation_id != self.generation_id:
            return []
        return await asyncio.to_thread(self._render, chunk)

    def _render(self, chunk: AudioChunk) -> list[VideoFrame]:
        if chunk.generation_id != self.generation_id or self.base is None:
            return []
        samples = np.frombuffer(chunk.pcm, dtype="<i2")
        if not len(samples):
            return []
        amplitude = min(1.0, math.sqrt(float(np.mean(np.square(samples.astype(np.float32))))) / 12000.0)
        duration_us = round(len(samples) / (chunk.sample_rate * chunk.channels) * 1_000_000)
        end_us = self.audio_us + duration_us
        frames = []
        while self.next_frame_us < end_us:
            image = self.base.copy()
            draw = ImageDraw.Draw(image)
            s = self.size
            opening = max(3, int(s * (0.01 + 0.075 * amplitude)))
            draw.ellipse((s*.41, s*.64-opening/2, s*.59, s*.64+opening/2), fill="#853f45", outline="#70383e", width=2)
            frames.append(VideoFrame(chunk.generation_id, self.next_frame_us, s, s, image.tobytes()))
            self.next_frame_us += round(1_000_000 / self.fps)
        self.audio_us = end_us
        return frames if chunk.generation_id == self.generation_id else []

    async def interrupt(self, generation_id: int) -> None:
        self.generation_id = generation_id

    async def stop(self) -> None:
        self.running = False
        self.base = None
