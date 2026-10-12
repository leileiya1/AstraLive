"""Default-off Golden instrumentation, after real GPU decoding, before READY.

No synthesis or native pose changes. Only one decoded RGB artifact is retained.
The original H264 and speech reference permit independent F correlation/audit.
"""
import hashlib
import json
from pathlib import Path
import wave

LAYOUT = "astralive-golden-barcode-24-v1"


def barcode_bits(ordinal, sequence):
    if not 1 <= ordinal <= 4095 or not 0 <= sequence <= 199:
        raise ValueError("observer barcode range")
    body = ordinal << 8 | sequence
    crc = 0
    for offset in range(0, 20, 4):
        crc ^= (body >> offset) & 15
    return [(body << 4 | crc) >> bit & 1 for bit in range(23, -1, -1)]


def overlay(rgb, ordinal, sequence):
    if len(rgb) != 512 * 512 * 3:
        raise ValueError("observer requires real 512 RGB frame")
    output = bytearray(rgb)
    for cell, bit in enumerate(barcode_bits(ordinal, sequence)):
        color = bytes((40, 220, 40) if bit else (220, 40, 40)) * 8
        for row in range(8):
            offset = (row * 512 + cell * 8) * 3
            output[offset:offset + 24] = color
    return bytes(output)


class StagingObserver:
    def __init__(self, directory):
        self.directory = Path(directory) if directory else None
        self.ordinal = 0
        if self.directory:
            self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)

    def begin(self, stage, pcm):
        if not self.directory:
            return None
        self.ordinal += 1
        if self.ordinal > 4095:
            raise ValueError("observer attempt budget exceeded")
        identity = stage.identity
        folder = self.directory / ("attempt-%04d" % self.ordinal)
        folder.mkdir(mode=0o700)
        with wave.open(str(folder / "speech.wav"), "wb") as wav:
            wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(16000);wav.writeframes(pcm)
        with (folder / "native.h264").open("wb") as video:
            for _, payload, _ in stage.frames:
                video.write(payload)
        return {"folder": folder, "ordinal": self.ordinal, "layoutRevision": LAYOUT,
            "identity": identity, "stageDescriptor": stage.descriptor,
            "speechPCMHash": "sha256:" + hashlib.sha256(pcm).hexdigest(), "frames": [],
            "scope": "TEST_ONLY_REAL_GPU_OUTPUT_INSTRUMENTATION", "audienceAudible": False}

    def frame(self, observation, header, rgb):
        if observation is None:
            return rgb
        sequence = header["frame_sequence"]
        emitted = overlay(rgb, observation["ordinal"], sequence)
        observation["frames"].append({"sequence": sequence, "ptsUs": header["pts_us"],
            "nativeRGBHash": header["native_rgb_sha256"],
            "decodedRGBHash": "sha256:" + hashlib.sha256(rgb).hexdigest(),
            "emittedRGBHash": "sha256:" + hashlib.sha256(emitted).hexdigest()})
        return emitted

    def finish(self, observation, **metadata):
        if observation is None:
            return
        folder = observation.pop("folder")
        observation.update(metadata)
        (folder / "reference.json").write_text(json.dumps(observation, ensure_ascii=False, indent=2) + "\n")
