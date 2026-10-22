"""P8: the CPU VITS lexicon has no Latin letters, so the engine silently
skipped them ('T恤' -> '恤', sizes S/M/L, units ML/kg). spoken_text() must
leave nothing unpronounceable while keeping spoken_sizes() semantics."""
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

from app.real_tts import LETTERS, PROSODY, lexicon_characters, spoken_sizes, spoken_text, uncovered

MODEL = Path(os.environ.get("TTS_MODEL_DIR", Path(__file__).resolve().parents[1]
                            / ".local/vits-piper-zh_CN-xiao_ya-medium"))
PRODUCT = [
    "这款纯棉T恤有S、M、L和XL尺码。",
    "型号S123，耗时30 S，容量500 ML，长20 M。",
    "支持USB-C快充，5000mAh电池，重1.2kg。",
    "提供的尺码有M、L、XL、2XL；容量为500ML。",
    "iPhone 15 价格5999元，买二送一。",
    "打5折50%优惠，买2+1，满100减20~30，价格¥99元/件。",
    "A/B款颜色&尺码，编号#12，温度30℃，面积5㎡，规格2x3。",
]


class SpokenTextTests(unittest.TestCase):
    def test_product_sentences(self):
        self.assertEqual(spoken_text(PRODUCT[0]), "这款纯棉踢恤有艾丝、艾姆、艾尔和艾克斯艾尔尺码。")
        self.assertEqual(spoken_text(PRODUCT[1]), "型号艾丝123，耗时30秒，容量500毫升，长20米。")
        self.assertEqual(spoken_text(PRODUCT[2]), "支持优艾丝比-西快充，5000毫安时电池，重1.2千克。")

    def test_size_semantics_are_unchanged(self):
        # spoken_sizes itself is untouched; units after numbers are never sizes.
        self.assertEqual(spoken_sizes(PRODUCT[1]), PRODUCT[1])
        self.assertIn("艾克斯艾尔", spoken_text("这款有 XL 尺码"))
        self.assertNotIn("艾姆", spoken_text("长20 M"))

    def test_glossary_wins_over_spelling_and_is_word_bounded(self):
        glossary = {"iPhone": "爱疯"}
        self.assertEqual(spoken_text("这款iPhone很好", glossary), "这款爱疯很好")
        self.assertIn("艾皮艾尺欧恩伊", spoken_text("这款iPhone很好"))  # spelled, never silent
        self.assertEqual(spoken_text("iPhoneX", glossary), spoken_text("iPhoneX"))

    def test_meaning_carrying_symbols_are_read(self):
        self.assertEqual(spoken_text(PRODUCT[5]), "打5折百分之50优惠，买2加1，满100减20到30，价格99元每件。")
        self.assertEqual(spoken_text(PRODUCT[6]),
                         "诶或比款颜色和尺码，编号12号，温度30摄氏度，面积5平方米，规格2乘3。")

    def test_every_letter_has_a_reading(self):
        self.assertEqual(set(LETTERS), {chr(c) for c in range(ord("A"), ord("Z") + 1)})


@unittest.skipUnless((MODEL / "lexicon.txt").is_file(), "real TTS model not installed")
class LexiconCoverageTests(unittest.TestCase):
    def test_no_product_character_is_unpronounceable(self):
        known = lexicon_characters(str(MODEL))
        for text in PRODUCT:
            self.assertTrue(uncovered(spoken_sizes(text), known), text)  # the bug
            self.assertEqual(uncovered(spoken_text(text), known), set(), text)

    def test_real_engine_reports_no_ignored_characters(self):
        # The C++ engine logs "Ignore OOV" to stderr for every dropped char.
        script = (
            "import sys; sys.path.insert(0, sys.argv[1]);"
            "from app.real_tts import SherpaOnnxTTSProvider, spoken_text, spoken_sizes;"
            "p = SherpaOnnxTTSProvider(sys.argv[2]); f = spoken_text if sys.argv[3] == 'new' else spoken_sizes;"
            "[p.engine.generate(f(t), sid=0, speed=1.0) for t in sys.argv[4:]]"
        )
        runtime = str(Path(__file__).resolve().parents[1])
        def stderr(mode):
            return subprocess.run([sys.executable, "-c", script, runtime, str(MODEL), mode, *PRODUCT],
                                  capture_output=True, text=True, timeout=120, check=True).stderr
        def dropped(mode):
            return set(re.findall(r"Ignore OOV '(.)'", stderr(mode)))
        self.assertTrue(dropped("old") - PROSODY)  # the original bug: content dropped
        self.assertEqual(dropped("new") - PROSODY, set())  # only prosody marks may drop


if __name__ == "__main__":
    unittest.main()
