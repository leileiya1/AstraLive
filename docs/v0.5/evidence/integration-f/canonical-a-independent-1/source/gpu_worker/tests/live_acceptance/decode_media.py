"""Decode complete received media, retaining per-track timing/gap measurements."""
import av,pathlib,json,sys,time,hashlib

def decode_file(path):
 path=pathlib.Path(path)
 tracks=[]
 with av.open(str(path)) as c:indices=[(s.index,s.type) for s in c.streams if s.type in {'audio','video'}]
 for index,kind in indices:
  count=0;first=last=None;nonmonotonic=[];large_gaps=[];previous_end=None
  with av.open(str(path)) as c:
   for f in c.decode(c.streams[index]):
    if f.pts is None:raise ValueError('missing frame timestamp')
    t=float(f.pts*f.time_base)
    if last is not None and t<=last:nonmonotonic.append({'frame':count,'previous':last,'time':t})
    if kind=='audio' and previous_end is not None and abs(t-previous_end)>.004:large_gaps.append({'frame':count,'time':t,'gapSeconds':t-previous_end})
    if first is None:first=t
    last=t;count+=1
    if kind=='audio':previous_end=t+f.samples/f.sample_rate
  tracks.append({'index':index,'kind':kind,'decodedFrames':count,'firstSeconds':first,'lastSeconds':last,'nonmonotonic':nonmonotonic,'audioGapsOver4ms':large_gaps})
 with path.open('rb') as f:digest=hashlib.file_digest(f,'sha256').hexdigest()
 return {'tracks':tracks,'passed':len(tracks)==2 and all(x['decodedFrames'] and not x['nonmonotonic'] and not x['audioGapsOver4ms'] for x in tracks),'bytes':path.stat().st_size,'sha256':digest,'sourcePath':str(path)}

if __name__=='__main__':
 p=pathlib.Path(sys.argv[1]);out={};started=time.monotonic()
 if '--single' in sys.argv:
  out=decode_file(p);out['elapsedSeconds']=time.monotonic()-started;print(json.dumps(out));sys.exit(0 if out['passed'] else 1)
 for name in ['browser-native.webm','browser-canvas.webm','rtmp-received.mkv']:
  if name=='rtmp-received.mkv' and not (p/name).exists():
   out[name]=json.loads((p/'rtmp-remote-decode.json').read_text())
  else:out[name]=decode_file(p/name)
 out['elapsedSeconds']=time.monotonic()-started;out['passed']=all(v['passed'] for v in out.values() if isinstance(v,dict));(p/'complete-media-decode.json').write_text(json.dumps(out,indent=2));print(json.dumps(out))
 if not out['passed']:sys.exit(1)
