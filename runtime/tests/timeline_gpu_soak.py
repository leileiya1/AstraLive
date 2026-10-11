"""Owned real SoulX/Chrome/RTMP media soak; no production Session or A journal.

Prerecorded PCM is incremental input, not live TTS. A run is one continuous
Worker connection and Chrome peer; fallback is a failing acceptance result.
"""
import argparse, asyncio, hashlib, json, os, pathlib, shutil, subprocess, time, wave
from types import SimpleNamespace
from unittest.mock import patch
import av, numpy as np, psutil, uvicorn
from aiortc import RTCPeerConnection, RTCConfiguration
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from playwright.async_api import async_playwright
from runtime.app.models import SessionConfig
from runtime.app.config import RTMPSettings
from runtime.app.providers import AudioChunk
from runtime.app.media_timeline import TimedAudioChunk
from runtime.app.webrtc_media import WebRTCMediaOutput
from runtime.app.rtmp_media import FFmpegRTMPMediaOutput
from runtime.app.media_fanout import FanoutMediaOutput
from runtime.app.bound_media import BoundConsumptionMediaOutput
from gpu_worker.runtime_adapter import RemoteAvatarEngine
from runtime.tests.timeline_media_benchmark import HTML, free_port, percentile


def audit(path):
    result={}
    with av.open(str(path)) as container:
        for stream in container.streams:
            kind=stream.type
            result[kind]={"packets":0,"backward":0,"duplicate":0,"first":None,"last":None,"maxGapMs":0}
        for packet in container.demux():
            if packet.pts is None:continue
            row=result[packet.stream.type];at=float(packet.pts*packet.time_base)
            if row["last"] is not None:
                row["backward"]+=at<row["last"];row["duplicate"]+=at==row["last"]
                row["maxGapMs"]=max(row["maxGapMs"],(at-row["last"])*1000)
            else:row["first"]=at
            row["last"]=at;row["packets"]+=1
    decode=subprocess.run([shutil.which('ffmpeg'),'-v','error','-xerror','-i',str(path),'-f','null','-'],capture_output=True,timeout=180)
    return {"streams":result,"strictDecodeExit":decode.returncode,"decodeErrors":decode.stderr.decode()[-2000:]}


async def run(args):
    out=args.output;out.mkdir(parents=True,exist_ok=False)
    root=pathlib.Path(__file__).resolve().parents[2]
    (out/'source.json').write_text(json.dumps({
        'sourceSHA':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
        'sourceDirty':bool(subprocess.check_output(['git','status','--porcelain'],text=True)),
        'sourceFileSHA256':{str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest()
                            for p in (root/'runtime/app').glob('*media*.py')},
        'contract':'v0.5-frozen-1'},indent=2))
    os.environ['ASTRALIVE_MEDIA_TIMELINE_V2_ENABLED']='true' if args.v2 else 'false'
    os.environ.pop('ASTRALIVE_MEDIA_TIMELINE_ENABLED',None);os.environ['SOULX_LATENCY_MARKER']='1'
    with wave.open(str(args.wave)) as w:
        assert (w.getframerate(),w.getnchannels(),w.getsampwidth())==(16000,1,2)
        pcm=w.readframes(w.getnframes())
    cfg=SimpleNamespace(state_dir=str(out),worker_ref='v05-b-soulx',log_bytes=10*1024*1024,log_backups=5,startup_timeout_s=300)
    avatar=RemoteAvatarEngine({'port':args.port,'tokenFile':str(args.token_file),'avatarRef':'official-girl',
                              'assetSHA256':'384abd202f7dae45fdbbab3b6a7777cd7c8a64625fb19217a45d056f2162c624'},'session_v05_b_soak',cfg)
    config=SessionConfig(fps=25,preview={'type':'WEBRTC'})
    avatar.configure_session(config);await avatar.prepare(config)
    if avatar.degraded:await avatar.stop();raise RuntimeError('REAL_WORKER_PREFLIGHT_FAILED')
    worker_epoch=avatar.link.epoch
    settings=RTMPSettings(enabled=True,publish_url=f'rtmp://127.0.0.1:{free_port()}/live/b-soak',width=512,height=512,
                          ffmpeg_binary=shutil.which('ffmpeg'))
    receiver=await asyncio.create_subprocess_exec(settings.ffmpeg_binary,'-hide_banner','-loglevel','error','-listen','1',
        '-i',settings.target,'-c','copy','-y',str(out/'rtmp.flv'),stdout=asyncio.subprocess.DEVNULL,stderr=asyncio.subprocess.PIPE)
    web=WebRTCMediaOutput();rtmp=FFmpegRTMPMediaOutput(settings)
    fanout=FanoutMediaOutput([('webrtc',web),('rtmp',rtmp)]);media=BoundConsumptionMediaOutput(fanout,avatar)
    # Explicit audio ranges survive sink-local drops; no semantic journal claim.
    source_cursor=0
    original=media.push_audio
    async def typed_audio(chunk):
        nonlocal source_cursor
        pipeline = avatar.pipeline
        if pipeline:
            source_cursor = pipeline.origin + pipeline.delivered - len(chunk.pcm)//2
        timed=TimedAudioChunk(chunk.generation_id,chunk.sequence,chunk.pcm,16000,1,None,source_cursor,
                              source_cursor+len(chunk.pcm)//2,16000)
        source_cursor=timed.endSample
        await original(timed)
    media.push_audio=typed_audio
    app=FastAPI()
    html=HTML.replace('canvas.width=160;canvas.height=160','canvas.width=512;canvas.height=512').replace('c.drawImage(v,0,0,160,160)','c.drawImage(v,0,0,512,512)').replace(
        'packetsReceived:x.packetsReceived','estimatedPlayoutTimestamp:x.estimatedPlayoutTimestamp,packetsReceived:x.packetsReceived')
    @app.get('/')
    async def page():return HTMLResponse(html)
    @app.post('/offer')
    async def offer(request:Request):
        data=await request.json()
        with patch('runtime.app.webrtc_media.RTCPeerConnection',lambda:RTCPeerConnection(RTCConfiguration(iceServers=[]))):
            return {'type':'answer','sdp':await web.create_answer(data['sdp'])}
    server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=free_port(),log_level='error'))
    server_task=asyncio.create_task(server.serve());samples=[];cycles=[];browser=None;normal=False
    start=time.monotonic();generation=1;proc=psutil.Process()
    def emit(name,row):
        with (out/name).open('a') as f:f.write(json.dumps(row)+'\n')
    try:
        await avatar.start();await media.start()
        while not server.started:await asyncio.sleep(.01)
        async with async_playwright() as playwright:
            browser=await playwright.chromium.launch(channel='chrome',headless=True,args=['--autoplay-policy=no-user-gesture-required'])
            handle=await browser.new_page();await handle.goto(f'http://127.0.0.1:{server.config.port}/')
            await handle.evaluate('start()');await handle.wait_for_function("pc.connectionState==='connected'")
            start=time.monotonic()
            async def monitor():
                while True:
                    row={'elapsedSeconds':time.monotonic()-start,'rssBytes':proc.memory_info().rss,
                         'cpuSeconds':sum(proc.cpu_times()[:2]),'diagnostics':fanout.diagnostics(),
                         'workerEpoch':avatar.link.epoch,'degraded':avatar.degraded}
                    samples.append(row);emit('samples.jsonl',row)
                    print(json.dumps({'checkpointSeconds':round(row['elapsedSeconds'],1),'degraded':avatar.degraded,
                                      'rssBytes':row['rssBytes']}),flush=True)
                    await asyncio.sleep(30)
            monitor_task=asyncio.create_task(monitor())
            try:
                while time.monotonic()-start<args.duration:
                    cycle=len(cycles);cycle_start=time.monotonic();marker_before=avatar.marker
                    force=cycle%4==2
                    async def source():
                        for seq,offset in enumerate(range(0,len(pcm),640)):
                            yield AudioChunk(generation,seq,pcm[offset:offset+640],16000,1)
                    async def speech():
                        async for chunk in avatar.stream_audio(source(),generation):
                            frames=await avatar.push_audio(chunk)
                            await media.push_audio(chunk)
                            for frame in frames:await media.push_video(frame)
                    task=asyncio.create_task(speech())
                    if force:
                        await asyncio.sleep(3)
                        task.cancel();generation+=1
                        await avatar.interrupt(generation);await asyncio.gather(task,return_exceptions=True)
                        await media.interrupt(generation)
                    else:
                        await asyncio.wait_for(task,len(pcm)/32000+30)
                        await media.drain(generation)
                    row={'cycle':cycle,'elapsedSeconds':time.monotonic()-start,'wallSeconds':time.monotonic()-cycle_start,
                         'force':force,'generationId':generation,'markerBefore':marker_before,'degraded':avatar.degraded}
                    cycles.append(row);emit('cycles.jsonl',row)
                    if avatar.degraded or avatar.link.epoch!=worker_epoch:raise RuntimeError('REAL_GPU_CONTINUITY_LOST')
                    await asyncio.sleep(.3)
                chrome=await handle.evaluate('finish()');(out/'chrome.json').write_text(json.dumps(chrome,indent=2))
            finally:
                monitor_task.cancel();await asyncio.gather(monitor_task,return_exceptions=True)
            await browser.close();browser=None
        elapsed=time.monotonic()-start
        await avatar.stop();await media.stop();await asyncio.wait_for(receiver.communicate(),15)
        normal=rtmp._process.returncode==0
        events=[]
        for path in out.rglob('avatar-v05-b-soulx.log*'):
            for line in path.read_text().splitlines():
                try:events.append(json.loads(line))
                except ValueError:pass
        gpu=sum(e.get('event')=='FrameEnqueued' and e.get('source')=='GPU_INFERENCE' for e in events)
        fallback=sum(e.get('event')=='FrameEnqueued' and e.get('source')=='LIGHTWEIGHT_AVATAR' for e in events)
        estimated=[abs(s['video']['estimatedPlayoutTimestamp']-s['audio']['estimatedPlayoutTimestamp'])
                   for s in chrome['stats'] if s.get('audio',{}).get('estimatedPlayoutTimestamp') is not None
                   and s.get('video',{}).get('estimatedPlayoutTimestamp') is not None]
        result={'mode':'v2' if args.v2 else 'baseline','continuousSeconds':elapsed,'requestedSeconds':args.duration,
                'workerEpoch':worker_epoch,'cycles':len(cycles),'forces':sum(c['force'] for c in cycles),
                'gpuFrames':gpu,'fallbackFrames':fallback,'nativeEstimatedAVDriftMs':percentile(estimated),
                'normalStop':normal,'recording':await asyncio.to_thread(audit,out/'rtmp.flv'),
                'recordingSHA256':hashlib.sha256((out/'rtmp.flv').read_bytes()).hexdigest(),
                'waveSHA256':hashlib.sha256(args.wave.read_bytes()).hexdigest(),'rssPeakBytes':max(s['rssBytes'] for s in samples),
                'scope':'one Worker/Chrome session; prerecorded incremental PCM, real SoulX, local RTMP; no A/C business or physical audience'}
        (out/'summary.json').write_text(json.dumps(result,indent=2));print(json.dumps(result),flush=True)
        if not normal or not gpu or fallback:raise RuntimeError('REAL_GPU_ACCEPTANCE_FAILED')
    except BaseException as exc:
        (out/'failure.json').write_text(json.dumps({'errorType':type(exc).__name__,'elapsedSeconds':time.monotonic()-start,
                                                    'normalStop':normal,'degraded':avatar.degraded}))
        raise
    finally:
        if browser:await browser.close()
        await avatar.stop();await media.stop();server.should_exit=True;await server_task
        if receiver.returncode is None:receiver.terminate();await receiver.communicate()


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=pathlib.Path,required=True)
    p.add_argument('--token-file',type=pathlib.Path,required=True);p.add_argument('--port',type=int,default=18087)
    p.add_argument('--wave',type=pathlib.Path,required=True);p.add_argument('--duration',type=int,default=1800)
    p.add_argument('--v2',action='store_true');asyncio.run(run(p.parse_args()))
