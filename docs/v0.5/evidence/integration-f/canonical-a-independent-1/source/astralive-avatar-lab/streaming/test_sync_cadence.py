import unittest,numpy as np
from sync_warped import cadence_reference
from sync_measure import correlate
class Tests(unittest.TestCase):
 def reference(self):
  a=np.random.default_rng(11).normal(0,.1,7680).astype(np.float32);a[:2560]*=.2
  times=np.arange(24)*.02;times[8:]+=.4;ref,indices,collisions=cadence_reference(a,0,320,times)
  self.assertEqual(len(ref),14080);self.assertEqual(collisions,0);return a,ref
 def test_independent_consumption_cadence_does_not_invent_offset(self):
  source,ref=self.reference();heard=np.r_[np.zeros(1600),ref,np.zeros(16000)];naive=correlate(source,heard,.1);aware=correlate(ref,heard,.1)
  self.assertGreater(abs(naive['video_minus_audio_ms']),250);self.assertGreater(aware['correlation'],.999);self.assertAlmostEqual(aware['video_minus_audio_ms'],0)
 def test_real_600ms_audio_delay_remains_detectable_with_pacing_correction(self):
  _,ref=self.reference();heard=np.r_[np.zeros(11200),ref,np.zeros(16000)];r=correlate(ref,heard,.1);self.assertGreater(r['correlation'],.999);self.assertAlmostEqual(r['video_minus_audio_ms'],-600)
 def test_audio_callback_coalescing_is_explicit_and_bounded(self):
  source=np.ones(960,np.float32);ref,indices,collisions=cadence_reference(source,0,320,[1,1,1.04]);self.assertEqual(indices,[0,320,640]);self.assertEqual(collisions,1);self.assertEqual(len(ref),960)
if __name__=='__main__':unittest.main(verbosity=2)
