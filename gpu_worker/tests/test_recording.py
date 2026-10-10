"""Read-only CPU decode of pinned recordings; never an inference or fresh sync PASS."""
import json
from pathlib import Path
import unittest
import av

ROOT=Path(__file__).resolve().parents[2]/'astralive-avatar-lab/streaming/integration/soulx-final-one-hour-pinned-20261009'
class PinnedRecordingTests(unittest.TestCase):
    def test_first_15_seconds_of_both_recordings_decode_with_contiguous_audio_pts(self):
        for name in ('browser-native.webm','browser-canvas.webm'):
            with self.subTest(name=name):
                file=ROOT/name
                self.assertTrue(file.exists(),'pinned recording missing')
                counts={'audio':0,'video':0}; last={}; audio_end=None
                with av.open(str(file)) as container:
                    for frame in container.decode(audio=0,video=0):
                        kind='audio' if isinstance(frame,av.AudioFrame) else 'video'
                        stamp=float(frame.pts*frame.time_base)
                        if stamp>15 and counts['audio']>0 and counts['video']>0:break
                        if kind in last:self.assertGreater(stamp,last[kind])
                        if kind=='audio':
                            if audio_end is not None:self.assertLessEqual(abs(stamp-audio_end),.002)
                            audio_end=stamp+frame.samples/frame.sample_rate
                        last[kind]=stamp; counts[kind]+=1
                self.assertGreater(counts['audio'],100)
                self.assertGreater(counts['video'],100)
                print('PINNED_RECORDING_CPU_DECODE',name,counts)

if __name__=='__main__':unittest.main()
