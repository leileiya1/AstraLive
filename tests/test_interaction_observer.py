"""Measurement regression: existing marker remains readable after real sink scale/pad."""
import importlib.util
from pathlib import Path
import unittest
import numpy as np

spec = importlib.util.spec_from_file_location('rtmp_observer', Path(__file__).parents[1]/'scripts/interaction-rtmp-observer.py')
observer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(observer)


class MarkerTests(unittest.TestCase):
    def test_native_and_centered_scaled_marker(self):
        # Independent encoding matches diagnostic strip: RGB red=1 / green=0,
        # eight-pixel cells. Padding carries no diagnostic information.
        image = np.zeros((512, 512, 3), dtype=np.uint8)
        for row, value, width in [(0, 4097, 16), (8, 123456, 24), (16, 7, 16)]:
            for bit in range(width):
                image[row:row+8, bit*8:bit*8+8, 0 if value & (1<<bit) else 1] = 255
        self.assertEqual(observer.decode_marker(image), (4097, 7, 123456))
        # FFmpeg's accepted production sink is 720x1280 with a centered square.
        coordinates = np.floor(np.arange(720)*512/720).astype(int)
        scaled = image[coordinates[:, None], coordinates[None, :]]
        padded = np.zeros((1280, 720, 3), dtype=np.uint8)
        padded[280:1000] = scaled
        self.assertEqual(observer.decode_marker(padded), (4097, 7, 123456))

    def test_silent_unmarked_image_has_no_speech_identity(self):
        self.assertEqual(observer.decode_marker(np.zeros((1280, 720, 3), dtype=np.uint8)), (0, 0, 0))
