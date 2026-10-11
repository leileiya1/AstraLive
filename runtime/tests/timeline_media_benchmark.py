"""Isolated real Chrome + localhost RTMP A/B, deterministic synthetic PCM/RGB.

Not LLM/TTS/GPU/business continuity or physical-audibility acceptance. Run:
PYTHONPATH=runtime:. python runtime/tests/timeline_media_benchmark.py --output DIR
Requires installed Chrome, playwright, psutil, FFmpeg/ffprobe and real media deps.
"""
import argparse
import asyncio
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import shutil
import socket
import subprocess
import time
from unittest.mock import patch

import av
import numpy as np
import psutil
from aiortc import RTCPeerConnection, RTCConfiguration
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from playwright.async_api import async_playwright
import uvicorn

from app.config import RTMPSettings
from app.providers import AudioChunk, VideoFrame
from app.media_timeline import TimedAudioChunk
from app.webrtc_media import WebRTCMediaOutput
from app.rtmp_media import FFmpegRTMPMediaOutput
from app.media_fanout import FanoutMediaOutput

HTML = """<!doctype html><html><body><video id="v" muted autoplay playsinline width="320"></video>
<script>
window.samples={audio:[],video:[],stats:[],errors:[]};
window.start=async()=>{
 const pc=window.pc=new RTCPeerConnection({iceServers:[]});
 const stream=new MediaStream(); const v=document.getElementById('v');v.srcObject=stream;
 const canvas=document.createElement('canvas');canvas.width=160;canvas.height=160;
 const c=canvas.getContext('2d',{willReadFrequently:true});
 let last=0;let seen=new Set();
 const inspect=(now,meta)=>{
   c.drawImage(v,0,0,160,160);let marker=0;
   for(let b=0;b<12;b++){let p=c.getImageData(b*8+4,4,1,1).data;if(p[0]>p[1])marker|=1<<b;}
   if(marker && !seen.has(marker)){seen.add(marker);samples.video.push({marker,at:performance.now(),mediaTime:meta.mediaTime});}
   v.requestVideoFrameCallback(inspect);
 };v.requestVideoFrameCallback(inspect);
 pc.ontrack=e=>{
  stream.addTrack(e.track);
  if(e.track.kind==='audio'){
    const ctx=window.ctx=new AudioContext({latencyHint:'interactive'});
    const source=ctx.createMediaStreamSource(new MediaStream([e.track]));
    const analyser=ctx.createAnalyser();analyser.fftSize=512;
    const gain=ctx.createGain();gain.gain.value=.005;
    source.connect(analyser);analyser.connect(gain);gain.connect(ctx.destination);ctx.resume();
    const data=new Float32Array(512);let active=false;let lastPulse=-9999;
    window.audioPoll=setInterval(()=>{
      analyser.getFloatTimeDomainData(data);const peak=Math.max(...data.map(Math.abs));
      const now=performance.now();
      if(peak>.025 && !active && now-lastPulse>300){
        const output=ctx.getOutputTimestamp();samples.audio.push({at:now,peak,outputTimestamp:output,baseLatency:ctx.baseLatency,outputLatency:ctx.outputLatency});lastPulse=now;
      }active=peak>.025;
    },5);
  }
 };pc.addTransceiver('audio',{direction:'recvonly'});pc.addTransceiver('video',{direction:'recvonly'});
 await pc.setLocalDescription(await pc.createOffer());
 if(pc.iceGatheringState!=='complete')await new Promise(r=>pc.addEventListener('icegatheringstatechange',()=>{if(pc.iceGatheringState==='complete')r();}));
 const answer=await (await fetch('/offer',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({sdp:pc.localDescription.sdp})})).json();
 await pc.setRemoteDescription(answer);await v.play();
 window.statsPoll=setInterval(async()=>{
  const stats=await pc.getStats();let row={at:performance.now(),state:pc.connectionState};
  stats.forEach(x=>{if(x.type==='inbound-rtp')row[x.kind]={packetsReceived:x.packetsReceived,packetsLost:x.packetsLost,framesDecoded:x.framesDecoded,framesDropped:x.framesDropped,jitter:x.jitter,jitterBufferDelay:x.jitterBufferDelay,jitterBufferEmittedCount:x.jitterBufferEmittedCount};});samples.stats.push(row);
 },500);
};
window.finish=async()=>{clearInterval(audioPoll);clearInterval(statsPoll);await ctx.close();pc.close();return samples;};
</script></body></html>"""


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def percentile(values):
    if not values:
        return {"n": 0, "p50": None, "p95": None, "max": None}
    values = sorted(values)
    return {"n": len(values), "p50": values[math.ceil(len(values)*.5)-1],
            "p95": values[math.ceil(len(values)*.95)-1], "max": values[-1]}


def rgb(marker):
    pixels = np.zeros((160,160,3), dtype=np.uint8)
    for bit in range(12): pixels[:8,bit*8:bit*8+8] = [220,40,40] if marker & (1<<bit) else [40,220,40]
    pixels[32:128,32:128] = [60,120,180]
    return pixels.tobytes()


def analyse_recording(path, ffprobe):
    probe = subprocess.run([ffprobe,"-v","error","-show_streams","-show_packets","-of","json",str(path)],
                           capture_output=True, text=True, check=True)
    data=json.loads(probe.stdout)
    regressions={};duplicates={};pts={}
    for stream in data["streams"]:
        index=stream["index"];kind=stream["codec_type"]
        values=[float(p["pts_time"]) for p in data["packets"] if p["stream_index"]==index and "pts_time" in p]
        pts[kind]=values
        regressions[kind]=sum(b<a for a,b in zip(values,values[1:]))
        duplicates[kind]=sum(b==a for a,b in zip(values,values[1:]))
    audio_onsets=[];video_onsets={};active=False;last=-99
    with av.open(str(path)) as container:
        for frame in container.decode(audio=0):
            array=frame.to_ndarray();peak=float(np.abs(array).max())
            at=float(frame.pts*frame.time_base)
            if peak>.025 and not active and at-last>.3:
                audio_onsets.append(at);last=at
            active=peak>.025
    with av.open(str(path)) as container:
        for frame in container.decode(video=0):
            pixels=frame.to_ndarray(format="rgb24");marker=0
            for bit in range(12):
                p=pixels[4,bit*8+4]
                if int(p[0])>int(p[1]):marker |=1<<bit
            if marker and marker not in video_onsets:video_onsets[marker]=float(frame.pts*frame.time_base)
    matched=[{"marker":i+1,"audio_s":at,"video_s":video_onsets[i+1],
              "drift_ms":(video_onsets[i+1]-at)*1000}
             for i,at in enumerate(audio_onsets) if i+1 in video_onsets]
    return {"streams":data["streams"],"ptsRegressions":regressions,"duplicatePTS":duplicates,
            "packetPTS":pts,"audioOnsets":audio_onsets,"videoOnsets":video_onsets,"matched":matched,
            "absoluteOnsetDriftMs":percentile([abs(x["drift_ms"]) for x in matched]),
            "scope":"decoded synthetic pulse onset, not lip-sync or platform audience"}


async def trial(mode, output_dir, markers=20, faults=False):
    os.environ["ASTRALIVE_MEDIA_TIMELINE_V2_ENABLED"]="true" if mode=="v2" else "false"
    os.environ.pop("ASTRALIVE_MEDIA_TIMELINE_ENABLED",None)
    ffmpeg=shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
    ffprobe=shutil.which("ffprobe") or "/opt/homebrew/bin/ffprobe"
    record=output_dir/f"{mode}.flv"
    port=free_port()
    settings=RTMPSettings(enabled=True,publish_url=f"rtmp://127.0.0.1:{port}/live/owned-fixture",
                          width=160,height=160,ffmpeg_binary=ffmpeg)
    receiver=await asyncio.create_subprocess_exec(ffmpeg,"-hide_banner","-loglevel","error","-listen","1",
        "-i",settings.target,"-c","copy","-y",str(record),stdout=asyncio.subprocess.DEVNULL,stderr=asyncio.subprocess.PIPE)
    web=WebRTCMediaOutput()
    rtmp=FFmpegRTMPMediaOutput(settings)
    fanout=FanoutMediaOutput([("webrtc",web),("rtmp",rtmp)])
    app=FastAPI()
    @app.get("/")
    async def page(): return HTMLResponse(HTML)
    @app.post("/offer")
    async def offer(request:Request):
        data=await request.json()
        # Fixture-local ICE removes unrelated public STUN delays for both arms.
        with patch("app.webrtc_media.RTCPeerConnection",lambda:RTCPeerConnection(RTCConfiguration(iceServers=[]))):
            return {"type":"answer","sdp":await web.create_answer(data["sdp"])}
    server=uvicorn.Server(uvicorn.Config(app,host="127.0.0.1",port=free_port(),log_level="error"))
    server_task=asyncio.create_task(server.serve())
    resources=[];events=[];browser=None;page_handle=None
    fault_events=[];chrome_parts=[]
    delayed=[]
    reconnect_record=None
    proc=psutil.Process();start=time.monotonic();cpu_start=sum(proc.cpu_times()[:2])
    try:
        await asyncio.sleep(.4)
        await fanout.start()
        while not server.started: await asyncio.sleep(.01)
        async with async_playwright() as playwright:
            browser=await playwright.chromium.launch(channel="chrome",headless=True,
                args=["--autoplay-policy=no-user-gesture-required"])
            page_handle=await browser.new_page()
            await page_handle.goto(f"http://127.0.0.1:{server.config.port}/")
            await page_handle.evaluate("start()")
            await page_handle.wait_for_function("pc.connectionState==='connected'")
            await asyncio.sleep(.5)
            exchange_start=time.monotonic()
            chrome_now=await page_handle.evaluate("performance.now()")
            exchange_end=time.monotonic()
            clock_offset=chrome_now-(exchange_start+exchange_end)*500
            clock_half_width=(exchange_end-exchange_start)*500
            fixture_start=time.monotonic()
            # 80ms paired tone/marker every 800ms; fixture PCM is explicit synthetic input.
            source_sample=0
            generation=1
            for tick in range(markers*40):
                await asyncio.sleep(max(0,fixture_start+tick*.02-time.monotonic()))
                if faults and tick and tick%160==0:
                    generation+=1
                    await fanout.interrupt(generation)
                    # Explicit delayed old-generation result at the publication seam.
                    await fanout.push_audio(AudioChunk(generation-1,tick,b"\x00\x7f"*320))
                    await fanout.push_video(VideoFrame(generation-1,source_sample*1000000//16000,160,160,rgb(4000)))
                    fault_events.append({"fault":"FORCE generation fence + delayed old generation injection",
                                         "generation":generation,"tick":tick,"sourceSample":source_sample})
                if faults and tick==markers*20:
                    # Browser reconnect to a fresh sink clock; RTMP is untouched.
                    chrome_parts.append(await page_handle.evaluate("finish()"))
                    await page_handle.reload()
                    await page_handle.evaluate("start()")
                    await page_handle.wait_for_function("pc.connectionState==='connected'")
                    fixture_start=time.monotonic()-tick*.02
                    fault_events.append({"fault":"Chrome peer reconnect", "tick":tick,
                                         "sourceSample":source_sample,"newClockDomain":True})
                if faults and tick==markers*30:
                    await rtmp._abort_process("owned_fixture_encoder_failure")
                    _,receiver_error=await asyncio.wait_for(receiver.communicate(),8)
                    (output_dir/f"{mode}-receiver-before-reconnect.log").write_bytes(receiver_error)
                    reconnect_record=output_dir/f"{mode}-reconnected.flv"
                    receiver=await asyncio.create_subprocess_exec(ffmpeg,"-hide_banner","-loglevel","error","-listen","1",
                        "-i",settings.target,"-c","copy","-y",str(reconnect_record),
                        stdout=asyncio.subprocess.DEVNULL,stderr=asyncio.subprocess.PIPE)
                    fixture_start=time.monotonic()-tick*.02
                    fault_events.append({"fault":"owned RTMP encoder terminate + listener reconnect",
                                         "tick":tick,"sourceSample":source_sample,"newClockDomain":True})
                marker=tick//40+1 if tick%40<4 else 0
                values=(np.sin(2*np.pi*440*np.arange(320)/16000)*6000).astype("<i2") if marker else np.zeros(320,dtype="<i2")
                if tick%40==0: events.append({"marker":marker,"submittedAt":time.monotonic()})
                underrun=faults and tick%160 in (92,93,94,95)
                if not underrun:
                    await fanout.push_audio(TimedAudioChunk(generation,tick,values.tobytes(),16000,1,
                                                           None,source_sample,source_sample+320,16000))
                elif tick%160==92:
                    fault_events.append({"fault":"80ms audio producer underrun", "tick":tick})
                if tick%2==0:
                    frame=VideoFrame(generation,source_sample*1000000//16000,160,160,rgb(marker))
                    if faults and tick%160==60:
                        async def later(item):
                            await asyncio.sleep(.25)
                            await fanout.push_video(item)
                        delayed.append(asyncio.create_task(later(frame)))
                        fault_events.append({"fault":"250ms late video", "tick":tick})
                    else:
                        await fanout.push_video(frame)
                if not underrun: source_sample+=320
                if tick%25==0:
                    resources.append({"at":time.monotonic(),"rssBytes":proc.memory_info().rss,
                        "cpuSeconds":sum(proc.cpu_times()[:2]),"diagnostics":fanout.diagnostics()})
            await asyncio.gather(*delayed)
            await fanout.drain(generation)
            await asyncio.sleep(.7)
            chrome=await page_handle.evaluate("finish()")
            chrome_parts.append(chrome)
            chrome["version"]=browser.version
            await browser.close();browser=None
        before=fanout.diagnostics()
        await fanout.stop()
        raw,error=await asyncio.wait_for(receiver.communicate(),10)
        (output_dir/f"{mode}-receiver.log").write_bytes(error)
        decoded=await asyncio.to_thread(analyse_recording,record,ffprobe)
        reconnected=await asyncio.to_thread(analyse_recording,reconnect_record,ffprobe) if reconnect_record else None
        pairs=[]
        for domain,part in enumerate(chrome_parts):
            video=sorted(part["video"],key=lambda row:row["marker"])
            if len(video)!=len(part["audio"]):
                part["errors"].append("onset counts differ; cohort is unpaired, retained as failure")
                continue
            for audio,video_row in zip(part["audio"],video):
                pairs.append({"marker":video_row["marker"],"clockDomain":domain,"audioAt":audio["at"],
                              "videoAt":video_row["at"],"driftMs":video_row["at"]-audio["at"]})
        related_latencies=[max(p["audioAt"],p["videoAt"])-events[p["marker"]-1]["submittedAt"]*1000-clock_offset for p in pairs] if not faults else []
        result={"mode":mode,"faultScenario":faults,"faultEvents":fault_events,
                "scope":"real native Chrome headless + localhost RTMP, synthetic PCM/RGB; no GPU/providers/business",
                "generatedMarkers":markers,"sourceSamples":source_sample,"chrome":chrome,"chromeConnections":chrome_parts,"chromePairs":pairs,
                "staleInjectedMarkerObserved":any(v["marker"]==4000 for part in chrome_parts for v in part["video"]),
                "chromeAbsoluteOnsetDriftMs":percentile([abs(p["driftMs"]) for p in pairs]),
                "rtmp":decoded,"resources":resources,"events":events,"diagnostics":before,
                "rtmpReconnected":reconnected,
                "rssPeakBytes":max(x["rssBytes"] for x in resources),
                "cpuSeconds":sum(proc.cpu_times()[:2])-cpu_start,"wallSeconds":time.monotonic()-start,
                "correlatedFirstAVLatencyMs":percentile(related_latencies),
                "clockExchangeHalfWidthMs":clock_half_width,
                "recordingSha256":hashlib.sha256(record.read_bytes()).hexdigest(),
                "drainFailed":any(w.get("code")=="MEDIA_SINK_DRAIN_FAILED" for w in fanout.warnings),
                "normalStop":rtmp._process.returncode==0,"receiverExit":receiver.returncode,
                "audienceAudible":False,"firstAVScope":"browser decoded marker + AudioContext analyser onset"}
        (output_dir/f"{mode}.json").write_text(json.dumps(result,indent=2))
        return result
    finally:
        for task in delayed: task.cancel()
        await asyncio.gather(*delayed,return_exceptions=True)
        if browser: await browser.close()
        await fanout.stop()
        server.should_exit=True
        await server_task
        if receiver.returncode is None:
            receiver.terminate();await receiver.communicate()


async def main():
    parser=argparse.ArgumentParser();parser.add_argument("--output",type=Path,required=True);parser.add_argument("--markers",type=int,default=20)
    parser.add_argument("--faults",action="store_true")
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    root=Path(__file__).resolve().parents[2]
    manifest={"sourceSHA":subprocess.check_output(["git","rev-parse","HEAD"],text=True).strip(),
              "sourceDirty":bool(subprocess.check_output(["git","status","--porcelain"],text=True)),
              "sourceFileSHA256":{str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest()
                                  for p in (root/"runtime/app").glob("*media*.py")},
              "baselineSHA":"5a24478126211cbcde5a9565d0c6063748426527","contract":"v0.5-frozen-1",
              "platform":platform.platform(),"python":platform.python_version(),"pyav":av.__version__,
              "fixture":"440Hz synthetic 80ms pulse + RGB marker every800ms; seed=0",
              "clockDomains":"Chrome performance.now; Runtime monotonic; FLV PTS; no host-clock subtraction",
              "limitations":["AudioContext analyser onset is not physical device output", "headless native Chrome is not human visual assessment",
                              "no actual LLM/TTS/SoulX or busy interaction", "sequential A then B, warm-up/resource order bias retained"]}
    for mode in ("baseline","v2"):
        print(f"starting {mode}",flush=True)
        result=await trial(mode,args.output,args.markers,args.faults)
        print(json.dumps({"mode":mode,"chromeDrift":result["chromeAbsoluteOnsetDriftMs"],
                          "rtmpDrift":result["rtmp"]["absoluteOnsetDriftMs"],"normalStop":result["normalStop"]}),flush=True)
    (args.output/"manifest.json").write_text(json.dumps(manifest,indent=2))


if __name__=="__main__": asyncio.run(main())
