import time,urllib.request,json,subprocess,pathlib,os
p=pathlib.Path.home()/'AstraLive/experiments/real-avatar/soulx-final-one-hour-pinned-20261009'
while True:
 try:
  j=json.load(urllib.request.urlopen('http://127.0.0.1:19997/v3/paths/list',timeout=3))
  if any(x.get('ready') for x in j.get('items',[])):break
 except Exception:pass
 time.sleep(.5)
f=subprocess.Popen(['ffmpeg','-nostdin','-hide_banner','-loglevel','info','-i','rtmp://127.0.0.1:19355/live/soulx-isolated-lab','-c','copy','-f','matroska',str(p/'rtmp-received.mkv')],stdin=subprocess.DEVNULL,stdout=(p/'rtmp-reader.log').open('w'),stderr=subprocess.STDOUT,start_new_session=True)
(p/'rtmp-reader.pid').write_text(str(f.pid));f.wait()
