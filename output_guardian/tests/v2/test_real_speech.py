"""Stage 2d with REAL TTS: sherpa-onnx VITS zh_CN-xiao_ya (CPU) + the existing
lightweight CPU avatar, through the Runtime coordinator into the real Guardian
v2 Receiver/PrivateIPC. The Backend is the contract oracle (see
test_answer_coordinator.py) and the Observer envelope is derived from the real
tail. Skips (never passes) when the gitignored model directory is absent.
"""

import os
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[3]
MODEL = Path(
    os.environ.get(
        "TTS_MODEL_DIR", ROOT / "runtime/.local/vits-piper-zh_CN-xiao_ya-medium"
    )
)
if not (MODEL / "zh_CN-xiao_ya-medium.onnx").is_file():
    pytest.skip(
        "real TTS model not installed (set TTS_MODEL_DIR)", allow_module_level=True
    )

from runtime.app.lightweight_avatar import LightweightAvatarEngine
from runtime.app.models import VoiceConfig
from runtime.app.real_tts import SherpaOnnxTTSProvider
from runtime.app.receiver1.answer_coordinator import (
    AnswerCoordinator,
    JournalExecutor,
)
from runtime.app.receiver1.speech_media import SpeechMedia

from .test_answer_coordinator import OracleJournal, command_of, source
from .test_cpu import setup_cpu
from .test_runtime_receiver import process_pin

TEXT = "欢迎来到直播间，这款纯棉T恤有S、M、L和XL尺码。"
VOICE = VoiceConfig(voiceId="voice_local")


@pytest.fixture(scope="module")
def tts():
    return SherpaOnnxTTSProvider(str(MODEL))


async def collect(stream):
    return [item async for item in stream]


async def native_samples(tts, text):
    from runtime.app.providers import GenerationContext

    ctx = GenerationContext(1, "t", "s", "u")
    return sum([len(c.pcm) // 2 async for c in tts.synthesize_stream(text, VOICE, ctx)])


@pytest.mark.asyncio
async def test_real_tts_is_resampled_without_losing_samples(tts):
    speech = SpeechMedia(tts, VOICE, sample_rate=16000, chunk_ms=200)
    items = await collect(speech(TEXT))
    audio = b"".join(p for kind, p, _ in items if kind == "audio")
    # VITS is stochastic: compare within THIS synthesis, never across two.
    native = speech.samples_in
    expected = native * 16000 / tts.sample_rate
    assert native > tts.sample_rate  # more than one second of real speech
    # Flushed libav resampling is exact up to rounding (measured: ceil);
    # an unflushed tail would lose 16-17 samples.
    assert abs(len(audio) // 2 - expected) <= 1
    assert speech.samples_out == len(audio) // 2
    assert await native_samples(tts, TEXT) > tts.sample_rate  # engine stands alone
    assert all(
        len(p) <= 16000 * 2 * 200 // 1000 for kind, p, _ in items if kind == "audio"
    )
    pcm = np.frombuffer(audio, dtype="<i2").astype(np.float64)
    assert np.sqrt(np.mean(pcm**2)) > 300  # genuinely audible speech, not silence


@pytest.mark.asyncio
async def test_avatar_frames_follow_audio_and_stay_continuous_across_units(tts):
    avatar = LightweightAvatarEngine(fps=25, size=64)
    await avatar.prepare(None)
    await avatar.start()
    speech = SpeechMedia(
        tts, VOICE, sample_rate=16000, avatar=avatar, frame_size=(64, 64)
    )
    first = await collect(speech("第一段讲解。"))
    second = await collect(speech("第二段继续。"))
    pts = [p for kind, _, p in first + second if kind == "video"]
    assert pts == sorted(set(pts)) and pts[0] == 0  # strictly increasing, no reset
    for unit in (first, second):
        seconds = sum(len(p) // 2 for k, p, _ in unit if k == "audio") / 16000
        frames = sum(k == "video" for k, _, _ in unit)
        assert abs(frames - seconds * 25) <= 2
        assert all(len(p) == 64 * 64 * 3 for k, p, _ in unit if k == "video")


@pytest.mark.asyncio
async def test_coordinator_speaks_two_units_with_real_tts_into_guardian(
    closed_domain, tts
):
    import secrets

    from output_guardian.v2.ipc import PrivateIPC
    from runtime.app.receiver1.runtime_client import GuardianChannel, ReceiverRuntime
    from runtime.app.receiver1.transport import Credential, identity
    from runtime.app.receiver1.wire import GuardianWire

    d = closed_domain
    token = secrets.token_urlsafe(32)
    ipc = PrivateIPC(d.r, d.ipc_dir, [process_pin(d, "REGISTERED_RUNTIME", token)])
    await ipc.start()
    me = identity(os.getpid())
    rt = ReceiverRuntime(
        lambda: GuardianChannel(
            ipc.directory / "runtime.sock", me, Credential(token.encode())
        ),
        GuardianWire(),
    )
    avatar = LightweightAvatarEngine(fps=25, size=64)
    await avatar.prepare(None)
    await avatar.start()
    speech = SpeechMedia(
        tts, VOICE, sample_rate=16000, avatar=avatar, frame_size=(64, 64)
    )
    executor = JournalExecutor(OracleJournal(d.x), rt, command_of(d), speech)
    # Real owned CPU output child: drains Guardian's bounded queue by actually
    # encoding/decoding; only the Evidence envelope is synthetic (from real ranges).
    cpu = await setup_cpu(d)
    tails = []
    observe = cpu.observe

    async def record(lineage, tail):
        tails.append(tail)
        return await observe(lineage, tail)

    cpu.observe = record
    try:
        coord = AnswerCoordinator(source(d.x.artifacts), executor)
        for _ in d.x.artifacts:
            assert await coord.prepare_next()
            await coord.start_next()
            await coord.drain()
        assert not await coord.prepare_next()  # seal
        assert coord.view()["drained"] == 2 and coord.view()["sealed"]
        assert rt.tts_invocations == 2 and speech.units == 2
        # Guardian's own tail equals exactly what real TTS produced, and unit 2
        # continues unit 1's sample clock (the oracle also enforced this).
        assert tails[0].audio_start == 0 and tails[1].audio_start == tails[0].audio_end
        assert tails[1].audio_end == speech.samples_out
        assert tails[0].video_pts[-1] < tails[1].video_pts[0]
    finally:
        await rt.close()
        await ipc.close()
