"""Actual Chrome + unchanged B aiortc tracks, silence/blank CPU environment diagnostic.

No LLM/TTS/GPU/live-business acceptance; zero energy MUST NOT pass speech gate.
The captured RTP/AudioContext clocks and actual recorder bytes isolate harness.
"""
import argparse
import asyncio
import json
from pathlib import Path

from aiortc import RTCPeerConnection, RTCConfiguration, RTCSessionDescription
from playwright.async_api import async_playwright
from app.media_timeline import AudioMasterClock
from app.webrtc_media import _TimelineAudioTrack, _TimelineVideoTrack
from narration_real_golden import GoldenFailure, require_browser_av


async def main(args):
    out=Path(args.output);out.mkdir(parents=True,exist_ok=False)
    html=Path(args.legacy_html).read_text() if args.legacy_html else (Path(__file__).parent/'fixtures/golden_browser.html').read_text()
    clock=AudioMasterClock();audio=_TimelineAudioTrack(clock);video=_TimelineVideoTrack(clock)
    peer=RTCPeerConnection(RTCConfiguration(iceServers=[]));peer.addTrack(audio);peer.addTrack(video)
    report={'scope':'ACTUAL_CHROME_UNCHANGED_B_TRACKS_CPU_SILENCE_ENVIRONMENT_ONLY','GPU':'NOT_TESTED','realSpeech':'NOT_TESTED'}
    chunks=[]
    async with async_playwright() as p:
        browser=await p.chromium.launch(channel='chrome',headless=True,args=['--autoplay-policy=no-user-gesture-required'])
        try:
            page=await browser.new_page()
            async def recording(sequence,payload):chunks.append((sequence,len(payload)))
            await page.expose_function('__goldenRecording',recording)
            async def route(request):
                if request.request.url.endswith('/__golden/browser'):
                    await request.fulfill(status=200,content_type='text/html',body=html)
                else:
                    offer=request.request.post_data_json
                    await peer.setRemoteDescription(RTCSessionDescription(sdp=offer['sdp'],type='offer'))
                    await peer.setLocalDescription(await peer.createAnswer())
                    await request.fulfill(status=200,content_type='application/json',body=json.dumps({'data':{'type':'answer','sdp':peer.localDescription.sdp}}))
            await page.route('http://127.0.0.1:9/**',route)
            await page.goto('http://127.0.0.1:9/__golden/browser')
            if not args.legacy_html:
                await page.get_by_role('button',name='Enable real audio observation').click()
                await page.wait_for_function("ac && ac.state==='running'")
            await page.evaluate("goldenStart('cpu-diagnostic')")
            await page.wait_for_function("pc.connectionState==='connected'")
            preflight=await page.evaluate('goldenAudioReady()') if not args.legacy_html else await page.evaluate("()=>({state:ac?.state??null,currentTime:ac?.currentTime??null})")
            await asyncio.sleep(1.2)
            chrome=await page.evaluate('goldenFinish()')
            (out/'chrome.json').write_text(json.dumps(chrome,indent=2)+'\n')
            report.update(browserVersion=browser.version,audioPreflight=preflight,recordedBytes=chrome['recordedBytes'],recordingChunks=chrome['recordingChunks'],audioRMSMax=max((row['rms'] for row in chrome['audioEnergy']),default=0),videoFrames=len(chrome['video']),runtimeOutputSamples=clock.output_samples)
            if args.legacy_html:
                report.update(status='OBSERVED_LEGACY_ENV_DIAGNOSTIC_ONLY',finalContextTime=await page.evaluate('ac?.currentTime??null'),inbound=chrome['inbound'])
            try:require_browser_av(chrome,True)
            except GoldenFailure as exc:report['speechGateRejection']=str(exc)
            else:raise AssertionError('CPU silence falsely passed real decoded speech gate')
            if not args.legacy_html:
                report['status']='PASS' if preflight['ready'] and chrome['recordedBytes']>0 and report['speechGateRejection']=='Actual browser decoded speech energy missing' else 'FAIL'
        finally:
            await peer.close();await browser.close()
            (out/'result.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report))
    return int(report['status']=='FAIL')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',required=True);parser.add_argument('--legacy-html')
    raise SystemExit(asyncio.run(main(parser.parse_args())))
