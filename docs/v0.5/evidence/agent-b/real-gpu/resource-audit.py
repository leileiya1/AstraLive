import json,pathlib,sys
name=sys.argv[1];p=pathlib.Path('/tmp/astralive-v05-b-gpu-'+name)
s=[json.loads(l) for l in (p/'samples.jsonl').read_text().splitlines()]
web=[]
for l in pathlib.Path(str(p)+'.log').read_text().splitlines():
 if l.startswith('webrtc_media_metrics '):web.extend(json.loads(l.split(' ',1)[1])['peers'])
result={'sampleCount':len(s),'sampledElapsedSeconds':s[-1]['elapsedSeconds']-s[0]['elapsedSeconds'],
 'driverCPUSecondsDelta':s[-1]['cpuSeconds']-s[0]['cpuSeconds'],'driverRssFirstPeakLastBytes':[s[0]['rssBytes'],max(x['rssBytes'] for x in s),s[-1]['rssBytes']],
 'workerEpochs':sorted({x['workerEpoch'] for x in s}),'anyDegraded':any(x['degraded'] for x in s),
 'peerIDs':sorted({x['peerId'] for x in web}),
 'webAudioQueuePeakMs':max(x['audioPeakQueueMs'] for x in web),'webVideoQueuePeakMs':max(x['videoPeakQueueMs'] for x in web),
 'webStallEvents':max(x['peerStallEvents'] for x in web),'webEvictions':max(x['peerEvictions'] for x in web),
 'webEndSnapshot':web[-1],
 'fanoutAudioMaxFrames':max(c['audioQueueMax'] for x in s for c in x['diagnostics'].values()),
 'fanoutVideoMaxFrames':max(c['videoQueueMax'] for x in s for c in x['diagnostics'].values()),
 'rtmpSampledAudioPeakMs':max(x['diagnostics']['rtmp']['sink']['audioQueueMs'] for x in s),
 'rtmpSampledVideoPeakMs':max(x['diagnostics']['rtmp']['sink']['videoQueueMs'] for x in s),
 'rtmpSampledLast':s[-1]['diagnostics']['rtmp']['sink'],
 'scope':'driver samples during playback; excludes post-run analysis and Chrome/FFmpeg process memory; generation fences/padding drops distinct from late video'}
if name in ('v2-soak-1','ledger-soak-1'):
 mpath=pathlib.Path('/tmp/astralive-v05-b-gpu-evidence/'+('ledger-soak-monitor.jsonl' if name=='ledger-soak-1' else 'soak-monitor.jsonl'))
 m=[json.loads(l) for l in mpath.read_text().splitlines()]
 start_wall=(p/'samples.jsonl').stat().st_birthtime-s[0]['elapsedSeconds']
 end_wall=start_wall+json.loads((p/'summary.json').read_text())['continuousSeconds']
 m=[x for x in m if start_wall-.5<=x.get('sampleUnixSeconds',0)<=end_wall+.5]
 result['serverWallWindow']={'startUnixSeconds':start_wall,'endUnixSeconds':end_wall,'method':'original macOS sample file birthtime; +/-500ms tolerance, clocks compared through job IDs'}
 status=[x['workerStatus'] for x in m if 'workerStatus' in x]
 own=[x['processes'][0] for x in m if x.get('processes')]
 result['serverMonitor']={'sampleCount':len(m),'monitorErrors':sum('monitorError' in x or 'sshExit' in x for x in m),
  'workerEpochs':sorted({x['workerEpoch'] for x in status}),
  'lastErrors':sorted({x['lastError'] for x in status if x['lastError'] is not None}),
  'workerRssFirstPeakLastBytes':[own[0]['rssBytes'],max(x['rssBytes'] for x in own),own[-1]['rssBytes']],
  'workerCPUSecondsDelta':own[-1]['cpuSeconds']-own[0]['cpuSeconds'],
  'queuePeakAudioSamples':max(x['queueDepth']['audioSamples'] for x in status),'queuePeakVideoFrames':max(x['queueDepth']['videoFrames'] for x in status),
  'gpuReservedPeakBytes':max(x['gpuReservedBytes'] for x in status),'gpuDeviceUsedPeakBytes':max(x['gpuDeviceMemoryUsedBytes'] for x in status)}
(p/'resources.json').write_text(json.dumps(result,indent=2))
print({k:v for k,v in result.items() if k not in ('webEndSnapshot','rtmpSampledLast')})
