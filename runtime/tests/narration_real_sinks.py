"""Owned native Chrome + localhost RTMP fixture. Synthetic inference, real sinks.

No physical-audibility, human-quality or SoulX acceptance claims. Uses B's
existing benchmark page and marker decoder; requires explicit test opt-in.
"""
import asyncio
import json
import os
from pathlib import Path
from unittest.mock import patch

import numpy as np
from aiortc import RTCPeerConnection, RTCConfiguration
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from playwright.async_api import async_playwright
import uvicorn

from app.config import RTMPSettings
from app.providers import AudioChunk
from app.lightweight_avatar import LightweightAvatarEngine
from app.webrtc_media import WebRTCMediaOutput
from app.rtmp_media import FFmpegRTMPMediaOutput
from app.media_fanout import FanoutMediaOutput
from app.narration_segments import SegmentExecutor
from timeline_media_benchmark import HTML, free_port, analyse_recording

_owned={}
async def cleanup():
    """Retire only fixture-owned browser/encoder/server, also on failed proofs."""
    browser=_owned.get("browser");playwright=_owned.get("playwright")
    if browser:await browser.close()
    if playwright:await playwright.stop()
    fanout=_owned.get("fanout")
    if fanout:
        try:await asyncio.wait_for(fanout.stop(),10)
        except (Exception,asyncio.CancelledError):pass
    receiver=_owned.get("receiver")
    if receiver and receiver.returncode is None:
        receiver.terminate()
        try:await asyncio.wait_for(receiver.communicate(),3)
        except asyncio.TimeoutError:receiver.kill();await receiver.communicate()
    server=_owned.get("server");task=_owned.get("server_task")
    if server:server.should_exit=True
    if task:await asyncio.gather(task,return_exceptions=True)
    _owned.clear()


class SyntheticThreeSecondTTS:
    """Timing-controlled pulse+sine fixture, explicitly NOT synthesized speech."""
    async def synthesize_stream(self,text,voice,ctx):
        for seq in range(150):
            times=(np.arange(320)+seq*320)/16000
            pcm=(np.sin(2*np.pi*440*times)*6000 if seq<5 else np.zeros(320)).astype('<i2').tobytes()
            yield AudioChunk(ctx.generation_id,seq,pcm)


async def open_sinks(session,journal,guard,evidence):
    os.environ["ASTRALIVE_MEDIA_TIMELINE_ENABLED"]="true"
    os.environ.pop("ASTRALIVE_MEDIA_TIMELINE_V2_ENABLED",None)
    out=Path(evidence);out.mkdir(parents=True,exist_ok=True)
    port=free_port();settings=RTMPSettings(enabled=True,publish_url=f"rtmp://127.0.0.1:{port}/live/c-owned-fixture",width=160,height=160)
    receiver=await asyncio.create_subprocess_exec(settings.ffmpeg_binary,"-hide_banner","-loglevel","error","-listen","1",
        "-i",settings.target,"-c","copy","-y",str(out/"continuity.flv"),stdout=asyncio.subprocess.DEVNULL,stderr=asyncio.subprocess.PIPE)
    _owned["receiver"]=receiver
    web=WebRTCMediaOutput();rtmp=FFmpegRTMPMediaOutput(settings);fanout=FanoutMediaOutput([("webrtc",web),("rtmp",rtmp)])
    _owned["fanout"]=fanout
    session.media_output=fanout;session.tts_provider=SyntheticThreeSecondTTS()
    avatar=LightweightAvatarEngine(size=160);await avatar.prepare(None);await avatar.start();session.avatar_engine=avatar
    session.continuity=SegmentExecutor(session,1,journal,guard)
    await fanout.start()
    app=FastAPI()
    @app.get("/")
    async def page():return HTMLResponse(HTML)
    @app.post("/offer")
    async def offer(request:Request):
        data=await request.json()
        with patch("app.webrtc_media.RTCPeerConnection",lambda:RTCPeerConnection(RTCConfiguration(iceServers=[]))):
            return {"type":"answer","sdp":await web.create_answer(data["sdp"])}
    server=uvicorn.Server(uvicorn.Config(app,host="127.0.0.1",port=free_port(),log_level="error"));server_task=asyncio.create_task(server.serve())
    _owned.update(server=server,server_task=server_task)
    while not server.started:await asyncio.sleep(.01)
    playwright=await async_playwright().start();_owned["playwright"]=playwright
    browser=await playwright.chromium.launch(channel="chrome",headless=True,args=["--autoplay-policy=no-user-gesture-required"]);_owned["browser"]=browser
    page=await browser.new_page();await page.goto(f"http://127.0.0.1:{server.config.port}/");await page.evaluate("start()");await page.wait_for_function("pc.connectionState==='connected'")
    sinks=[peer.peer_id for peer in web.peers]+[f"rtmp:{rtmp.connection_incarnation}"]
    events=[];next_marker=0
    async def mark(command):
        nonlocal next_marker
        lane=command["lane"];marker=None
        if lane in {"NARRATION","AUDIENCE_ANSWER","RESUME_BRIDGE"}:next_marker+=1;marker=next_marker
        from PIL import ImageDraw
        draw=ImageDraw.Draw(avatar.base)
        if marker is not None:
            for bit in range(12):draw.rectangle((bit*8,0,bit*8+7,7),fill=(220,40,40) if marker&(1<<bit) else (40,220,40))
        events.append({"commandId":command["commandId"],"lane":lane,"segmentId":command["segmentId"],"marker":marker,"browserAt":await page.evaluate("performance.now()")})
    async def close():
        await asyncio.sleep(.5);chrome=await page.evaluate("finish()");chrome["version"]=browser.version
        await browser.close();await playwright.stop();before=fanout.diagnostics();await fanout.stop()
        try:_,error=await asyncio.wait_for(receiver.communicate(),10)
        except asyncio.TimeoutError:receiver.kill();_,error=await receiver.communicate()
        (out/"receiver.log").write_bytes(error)
        decoded=await asyncio.to_thread(analyse_recording,out/"continuity.flv","ffprobe")
        server.should_exit=True;await server_task
        _owned.clear()
        result={"scope":"real native headless Chrome + localhost FFmpeg RTMP; synthetic TTS + Lightweight2D + real PG journal/business cursor",
            "chrome":chrome,"rtmp":decoded,"events":events,"diagnostics":before,"requiredSinks":sinks,"audienceAudible":False,
            "normalStop":rtmp._process.returncode==0,"notTested":["real LLM/TTS/SoulX","human naturalness","official platform","busy SLA"]}
        from narration_metrics import metrics
        result["continuityMetrics"]=metrics(result)
        (out/"media.json").write_text(json.dumps(result,ensure_ascii=False,indent=2))
        answer_markers={e["marker"] for e in events if e["lane"]=="AUDIENCE_ANSWER"};bridge_markers={e["marker"] for e in events if e["lane"]=="RESUME_BRIDGE"}
        assert answer_markers.issubset({row["marker"] for row in chrome["video"]}),"Chrome never decoded answer markers"
        assert bridge_markers.issubset({row["marker"] for row in chrome["video"]}),"Chrome never decoded bridge markers"
        assert chrome["audio"],"Chrome audio analyser saw no pulse"
        assert decoded["audioOnsets"],"RTMP recording saw no pulse"
        return result
    return sinks,mark,close
