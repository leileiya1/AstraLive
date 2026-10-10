"""In-memory media validation helpers, not an AssetStorage/Profile implementation.

Call only after Backend ownership/consent checks. No filesystem or network writes.
Decoders and the face inspector must run in a resource-limited worker process.
"""
from dataclasses import dataclass
from io import BytesIO
import math
import wave


class AssetValidationError(ValueError):
    """Static codes only; never disclose decoder errors or user metadata."""


@dataclass(frozen=True)
class FaceObservation:
    # Worker-local detector output. Never accept these values from browser JSON.
    box: tuple[int, int, int, int]
    confidence: float
    yaw: float
    pitch: float
    roll: float
    eyes_visible: bool
    mouth_visible: bool


@dataclass(frozen=True)
class ValidatedPhoto:
    png: bytes
    width: int
    height: int
    crop: tuple[int, int, int, int]
    sharpness: float


def validate_photo(data: bytes, inspect_faces=None) -> ValidatedPhoto:
    import numpy as np
    from PIL import Image, ImageOps
    if not data or len(data) > 10 * 1024 * 1024:
        raise AssetValidationError("PHOTO_SIZE_INVALID")
    try:
        with Image.open(BytesIO(data)) as source:
            if source.format not in {"JPEG", "PNG", "WEBP"} or getattr(source, "n_frames", 1) != 1:
                raise AssetValidationError("PHOTO_FORMAT_INVALID")
            if source.width * source.height > 16_000_000 or min(source.size) < 512:
                raise AssetValidationError("PHOTO_DIMENSIONS_INVALID")
            source.load()
            image = ImageOps.exif_transpose(source).convert("RGB")
    except AssetValidationError:
        raise
    except Exception:
        raise AssetValidationError("PHOTO_DECODE_FAILED") from None
    if inspect_faces is None:
        raise AssetValidationError("FACE_CHECK_UNAVAILABLE")
    try:
        faces = inspect_faces(image)
    except Exception:
        raise AssetValidationError("FACE_CHECK_FAILED") from None
    if not isinstance(faces, (list, tuple)) or any(not isinstance(face, FaceObservation) for face in faces):
        raise AssetValidationError("FACE_CHECK_FAILED")
    if len(faces) != 1:
        raise AssetValidationError("PHOTO_REQUIRES_ONE_FACE")
    face = faces[0]
    values = (*face.box, face.confidence, face.yaw, face.pitch, face.roll)
    if (not all(math.isfinite(v) for v in values) or not 0.9 <= face.confidence <= 1
            or abs(face.yaw) > 15 or abs(face.pitch) > 15 or abs(face.roll) > 10
            or not face.eyes_visible or not face.mouth_visible):
        raise AssetValidationError("PHOTO_FACE_NOT_FRONTAL")
    left, top, right, bottom = face.box
    if (not all(isinstance(v, int) for v in face.box)
            or not 0 <= left < right <= image.width or not 0 <= top < bottom <= image.height
            or min(right - left, bottom - top) < 192):
        raise AssetValidationError("PHOTO_FACE_TOO_SMALL")
    gray = np.asarray(image.crop(face.box).resize((256, 256)).convert("L"), dtype=np.float32)
    laplacian = (gray[:-2, 1:-1] + gray[2:, 1:-1] + gray[1:-1, :-2]
                 + gray[1:-1, 2:] - 4 * gray[1:-1, 1:-1])
    sharpness = float(laplacian.var())
    if sharpness < 40:
        raise AssetValidationError("PHOTO_FACE_BLURRED")
    side = math.ceil(max(right - left, bottom - top) * 1.6)
    crop_left = (left + right - side) // 2
    crop_top = (top + bottom - side) // 2
    crop = (crop_left, crop_top, crop_left + side, crop_top + side)
    if crop_left < 0 or crop_top < 0 or crop[2] > image.width or crop[3] > image.height:
        raise AssetValidationError("PHOTO_FACE_CROP_CLIPPED")
    # Create fresh pixels to remove EXIF, GPS, PNG text and ICC metadata.
    resized = image.crop(crop).resize((512, 512), Image.Resampling.LANCZOS)
    clean = Image.frombytes("RGB", resized.size, resized.tobytes())
    output = BytesIO()
    clean.save(output, format="PNG")
    return ValidatedPhoto(output.getvalue(), image.width, image.height, crop, sharpness)


@dataclass(frozen=True)
class ValidatedReferenceAudio:
    wav: bytes
    samples: int
    rms: float
    clipped_fraction: float


def validate_reference_audio(data: bytes, reference_text: str) -> ValidatedReferenceAudio:
    import av
    import numpy as np
    if not data or len(data) > 20 * 1024 * 1024:
        raise AssetValidationError("REFERENCE_AUDIO_SIZE_INVALID")
    if (not reference_text.strip() or reference_text != reference_text.strip()
            or len(reference_text) > 1000 or "\x00" in reference_text):
        raise AssetValidationError("REFERENCE_TEXT_REQUIRED")
    pcm = bytearray()
    try:
        # Custom in-memory IO needs no URL protocol. Deny nested network/file reads.
        with av.open(BytesIO(data), mode="r", options={"protocol_whitelist": ""}) as container:
            formats = set(container.format.name.split(","))
            if not formats.intersection({"wav", "mp3", "ogg", "matroska", "webm", "mov", "mp4", "m4a", "flac"}):
                raise AssetValidationError("REFERENCE_AUDIO_FORMAT_INVALID")
            # Browser recordings are audio only, not an arbitrary video upload.
            if len(container.streams) != 1 or len(container.streams.audio) != 1:
                raise AssetValidationError("REFERENCE_AUDIO_STREAMS_INVALID")
            stream = container.streams.audio[0]
            resampler = av.AudioResampler(format="s16", layout="mono", rate=16000)
            native_rate = None
            native_samples = 0

            def collect(frames):
                for frame in frames:
                    if len(pcm) + frame.samples * 2 > 30 * 16000 * 2:
                        raise AssetValidationError("REFERENCE_AUDIO_DURATION_INVALID")
                    pcm.extend(bytes(frame.planes[0])[:frame.samples * 2])

            for frame in container.decode(stream):
                if (not 8000 <= frame.sample_rate <= 96000 or len(frame.layout.channels) not in {1, 2}
                        or frame.samples > frame.sample_rate * 31):
                    raise AssetValidationError("REFERENCE_AUDIO_FORMAT_INVALID")
                if native_rate is None:
                    native_rate = frame.sample_rate
                if frame.sample_rate != native_rate:
                    raise AssetValidationError("REFERENCE_AUDIO_RATE_CHANGED")
                native_samples += frame.samples
                if native_samples > native_rate * 31:
                    raise AssetValidationError("REFERENCE_AUDIO_DURATION_INVALID")
                if not np.isfinite(frame.to_ndarray()).all():
                    raise AssetValidationError("REFERENCE_AUDIO_DECODE_FAILED")
                collect(resampler.resample(frame))
            collect(resampler.resample(None))
    except AssetValidationError:
        raise
    except Exception:
        raise AssetValidationError("REFERENCE_AUDIO_DECODE_FAILED") from None
    samples = len(pcm) // 2
    if not 3 * 16000 <= samples <= 30 * 16000:
        raise AssetValidationError("REFERENCE_AUDIO_DURATION_INVALID")
    values = np.frombuffer(pcm, dtype="<i2").astype(np.float64) / 32768
    rms = float(np.sqrt(np.mean(values ** 2)))
    clipped = float(np.mean(np.abs(values) >= 0.999))
    if rms < 0.003:
        raise AssetValidationError("REFERENCE_AUDIO_TOO_QUIET")
    if clipped > 0.01:
        raise AssetValidationError("REFERENCE_AUDIO_CLIPPED")
    output = BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(pcm)
    return ValidatedReferenceAudio(output.getvalue(), samples, rms, clipped)
