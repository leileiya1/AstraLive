"""Keep every PCM correlation window, PTS gap, and browser health event.
Run with the Runtime venv. A capture finishing is not an AV acceptance PASS.
"""
import argparse,json,pathlib
from sync_measure import measure
ROOT=pathlib.Path(__file__).parent/'integration/soulx-cpu-av-repair-20261009'
def analyze(name):
 d=ROOT/name;j=json.loads((d/'browser.json').read_text());out={}
 for f in sorted(d.glob('*.webm')):
  epoch=int(f.stem.split('_epoch')[1]) if '_epoch'in f.stem else 1
  r=measure(f,[{'job_id':epoch,'marker':1,'generation':epoch,'source':str(d/'source.wav')}],window_samples=7680,stride_samples=7680);out[f.stem]=r
 (d/'analysis.json').write_text(json.dumps(out,indent=2))
 events=j.get('events',j.get('rows',[]));summary={'captureCompleted':j['status']=='PASS','events':[e for e in events if e['event']!='Frame'],'recordings':{k:{'trustedWindows':r['trusted_windows'],'medianP95MaxMs':r['absolute_offset_ms_percentiles'],'audioPTSGaps':r['audio_pts_gaps'],'allWindowsRetained':True}for k,r in out.items()}}
 for k,r in summary['recordings'].items():
  p=r['medianP95MaxMs'];r['syncGatePassed']=bool(r['trustedWindows']>=30 and p and p[1]<=150 and p[2]<=250 and not any(abs(x['gap_s'])>.1 for x in r['audioPTSGaps']))
 summary['scope']='CPU synthetic source, actual Chrome/aiortc. Not SoulX, LLM, TTS, RTMP or one-hour acceptance.'
 (d/'measurement-summary.json').write_text(json.dumps(summary,indent=2));print(json.dumps({'case':name,**summary},ensure_ascii=False))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('names',nargs='+')
 for name in p.parse_args().names:analyze(name)
