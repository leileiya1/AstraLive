import unittest
from io import BytesIO
import wave

import av
import numpy as np
from PIL import Image, PngImagePlugin

from app.personal_assets import (AssetValidationError, FaceObservation,
                                 validate_photo, validate_reference_audio)


def image_bytes(size=(800, 800)):
    image = Image.fromarray(np.random.default_rng(12).integers(0, 256, (*size[::-1], 3), dtype=np.uint8))
    output = BytesIO()
    meta = PngImagePlugin.PngInfo()
    meta.add_text("private", "never retain metadata")
    image.save(output, format="PNG", pnginfo=meta)
    return output.getvalue()


FACE = FaceObservation((250, 200, 550, 500), 0.99, 0, 0, 0, True, True)


def wav_bytes(duration=3, rate=24000, channels=1, silence=False, clipping=False):
    count = int(duration * rate)
    samples = (np.sin(np.arange(count) * 2 * np.pi * 220 / rate) * 8000).astype("<i2")
    if silence:
        samples[:] = 0
    if clipping:
        samples[:] = 32767
    samples = np.repeat(samples[:, None], channels, axis=1)
    output = BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(samples.tobytes())
    return output.getvalue()


class PersonalAssetTests(unittest.TestCase):
    def assert_code(self, code, call):
        with self.assertRaisesRegex(AssetValidationError, "^" + code + "$"):
            call()

    def test_photo_crop_and_metadata_removal(self):
        result = validate_photo(image_bytes(), lambda image: [FACE])
        with Image.open(BytesIO(result.png)) as image:
            self.assertEqual(image.size, (512, 512))
            self.assertEqual(image.mode, "RGB")
            self.assertEqual(image.info, {})
        self.assertEqual(result.crop, (160, 110, 640, 590))

    def test_face_check_unavailable_fails_closed(self):
        self.assert_code("FACE_CHECK_UNAVAILABLE", lambda: validate_photo(image_bytes()))

    def test_face_count_and_pose(self):
        data = image_bytes()
        for faces in ([], [FACE, FACE]):
            self.assert_code("PHOTO_REQUIRES_ONE_FACE", lambda: validate_photo(data, lambda image: faces))
        for change in ({"yaw": 30}, {"pitch": 25}, {"roll": 20}, {"eyes_visible": False},
                       {"mouth_visible": False}, {"confidence": 0.5}, {"yaw": float("nan")}):
            from dataclasses import replace
            face = replace(FACE, **change)
            self.assert_code("PHOTO_FACE_NOT_FRONTAL", lambda: validate_photo(data, lambda image: [face]))

    def test_detector_error_is_redacted(self):
        def fail(image):
            raise RuntimeError("private path or data")
        self.assert_code("FACE_CHECK_FAILED", lambda: validate_photo(image_bytes(), fail))

    def test_blur_and_clipped_head_crop(self):
        output = BytesIO()
        Image.new("RGB", (800, 800), "gray").save(output, format="PNG")
        self.assert_code("PHOTO_FACE_BLURRED", lambda: validate_photo(output.getvalue(), lambda image: [FACE]))
        from dataclasses import replace
        face = replace(FACE, box=(10, 10, 310, 310))
        self.assert_code("PHOTO_FACE_CROP_CLIPPED", lambda: validate_photo(image_bytes(), lambda image: [face]))

    def test_invalid_photo_size_decode_dimensions_and_animation(self):
        self.assert_code("PHOTO_SIZE_INVALID", lambda: validate_photo(b""))
        self.assert_code("PHOTO_SIZE_INVALID", lambda: validate_photo(b"x" * (10 * 1024 * 1024 + 1)))
        self.assert_code("PHOTO_DECODE_FAILED", lambda: validate_photo(b"private.jpg"))
        self.assert_code("PHOTO_DIMENSIONS_INVALID", lambda: validate_photo(image_bytes((256, 256))))
        output = BytesIO()
        Image.new("RGB", (800, 800)).save(output, format="GIF")
        self.assert_code("PHOTO_FORMAT_INVALID", lambda: validate_photo(output.getvalue()))

    def test_reference_downsample_stereo_and_normalize(self):
        result = validate_reference_audio(wav_bytes(channels=2), "这是一段参考语音。")
        self.assertEqual(result.samples, 48000)
        with wave.open(BytesIO(result.wav), "rb") as wav:
            self.assertEqual((wav.getframerate(), wav.getnchannels(), wav.getsampwidth()), (16000, 1, 2))
            self.assertEqual(wav.getnframes(), 48000)

    def test_browser_webm_opus_recording(self):
        output = BytesIO()
        with av.open(output, "w", format="webm") as container:
            stream = container.add_stream("libopus", rate=48000)
            for i in range(150):
                samples = (np.sin(np.arange(i * 960, (i + 1) * 960) * 2 * np.pi * 220 / 48000) * .2).astype("float32")
                frame = av.AudioFrame.from_ndarray(samples.reshape(1, -1), format="flt", layout="mono")
                frame.sample_rate = 48000
                for packet in stream.encode(frame):
                    container.mux(packet)
            for packet in stream.encode(None):
                container.mux(packet)
        result = validate_reference_audio(output.getvalue(), "浏览器录音。")
        self.assertAlmostEqual(result.samples / 16000, 3, delta=.03)

    def test_reference_size_text_decode_duration_silence_clipping(self):
        self.assert_code("REFERENCE_AUDIO_SIZE_INVALID", lambda: validate_reference_audio(b"", "文本"))
        self.assert_code("REFERENCE_AUDIO_SIZE_INVALID", lambda: validate_reference_audio(b"x" * (20 * 1024 * 1024 + 1), "文本"))
        self.assert_code("REFERENCE_TEXT_REQUIRED", lambda: validate_reference_audio(wav_bytes(), " "))
        self.assert_code("REFERENCE_AUDIO_DECODE_FAILED", lambda: validate_reference_audio(b"private.wav", "文本"))
        for duration in (2.9, 30.1):
            self.assert_code("REFERENCE_AUDIO_DURATION_INVALID", lambda: validate_reference_audio(wav_bytes(duration), "文本"))
        self.assert_code("REFERENCE_AUDIO_TOO_QUIET", lambda: validate_reference_audio(wav_bytes(silence=True), "文本"))
        self.assert_code("REFERENCE_AUDIO_CLIPPED", lambda: validate_reference_audio(wav_bytes(clipping=True), "文本"))


if __name__ == "__main__":
    unittest.main()
