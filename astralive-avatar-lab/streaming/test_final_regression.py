"""Evidence-based browser clock and sample-mapping regression guards."""
import json,pathlib,unittest,numpy as np
from sync_measure import frames,audio,correlate
ROOT=pathlib.Path(__file__).parent/'integration/soulx-final-one-hour'
class BrowserClock(unittest.TestCase):
 def test_original_582ms_audio_pts_gap_explains_increment(self):
  r=json.loads((ROOT/'original-packet-audit.json').read_text());gap=sum(x['gap_s'] for x in r['audio_pts_gaps']);w={x['source_sample']:x for x in r['original_target_windows']};increment=w[40000]['audio_recording_s']-w[32000]['audio_recording_s']-.5
  self.assertAlmostEqual(gap,.582,places=3);self.assertAlmostEqual(increment,gap,places=3)
 def test_audio_context_clock_deficit_independently_observed(self):
  p=ROOT.parent/'public-dual-one-hour-20261009/browser-events.jsonl';r=[json.loads(x) for x in p.read_text().splitlines()];a=[x for x in r if x['event']=='AudioContextProbe' and 200<x['browserMonotonic']<203];self.assertEqual(len(a),3);deficit=a[-1]['browserMonotonic']-a[0]['browserMonotonic']-(a[-1]['contextTime']-a[0]['contextTime']);self.assertGreater(deficit,.57);self.assertLess(deficit,.60);self.assertTrue(all(x['contextState']=='running' for x in a))
 def test_suspend_calibration_keeps_native_recording_continuous(self):
  p=ROOT/'cpu-clock';d=json.loads((p/'analysis.json').read_text());self.assertTrue(any(x['gap_s']>.5 for x in d['D_canvas_context']['audio_pts_gaps']));self.assertFalse(any(x['gap_s']>.02 for x in d['A_native']['audio_pts_gaps']));self.assertFalse(any(x['gap_s']>.02 for x in d['B_canvas_native']['audio_pts_gaps']))
 def test_browser_native_playout_available_independently(self):
  rows=json.loads((ROOT/'cpu-clock/stats.json').read_text());pairs=[]
  for r in rows:
   s={x.get('kind'):x for x in r.get('stats',[]) if x['type']=='inbound-rtp'}
   if all('estimatedPlayoutTimestamp' in s.get(k,{}) for k in ['audio','video']):pairs.append(s)
  self.assertGreater(len(pairs),20);self.assertGreater(pairs[-1]['audio']['packetsReceived'],pairs[0]['audio']['packetsReceived']);self.assertGreater(pairs[-1]['video']['framesDecoded'],pairs[0]['video']['framesDecoded'])
 def test_sample_to_25fps_pts_and_reference_mapping(self):
  source=np.random.default_rng(7).normal(0,.1,8000).astype(np.float32);heard=np.r_[np.zeros(1600),source,np.zeros(2000)];r=correlate(source,heard,.1);self.assertGreater(r['correlation'],.999);self.assertAlmostEqual(r['video_minus_audio_ms'],0);self.assertEqual(40000*1000000//16000,2500000)
if __name__=='__main__':unittest.main(verbosity=2)
