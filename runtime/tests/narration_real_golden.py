"""Real public control/API + Chrome observer; never replaces bound providers.

Comment transport is an explicit replay fixture. Speech/GPU/media must be real
and independently proved by Runtime/Worker/SQL evidence from the owning runner.
"""
import argparse
import asyncio
import base64
import binascii
import hashlib
import json
import random
from pathlib import Path
import time

import httpx


class GoldenFailure(Exception):
    pass


class ChromeRecordingWriter:
    """Strict sequential real Blob storage; rejects a bad chunk before writing it."""
    def __init__(self,file):
        self.file=file;self.next_sequence=0;self.chunks=[];self.failed=False

    def store(self,sequence,encoded,expected_bytes=None,expected_sha256=None):
        try:
            if self.failed or sequence!=self.next_sequence:
                raise GoldenFailure("Browser recording sequence gap or previous failure")
            try:payload=base64.b64decode(encoded,validate=True)
            except (binascii.Error,ValueError,TypeError):
                raise GoldenFailure("Browser recording Base64 invalid") from None
            sha=hashlib.sha256(payload).hexdigest()
            if not payload or (expected_bytes is not None and len(payload)!=expected_bytes) or (expected_sha256 is not None and sha!=expected_sha256):
                raise GoldenFailure("Browser recording Blob size or hash mismatch")
            self.file.write(payload);self.file.flush()
            self.chunks.append({"sequence":sequence,"bytes":len(payload),"sha256":sha})
            self.next_sequence+=1
        except Exception:
            self.failed=True;raise


def require_observable_state(snapshot):
    # Natural FINISHED is a terminal narration plan while the Session remains
    # live for explicit normal Stop; distinguish it from operator/failure Stop.
    if snapshot["state"] == "STOPPED" and snapshot.get("reason") == "FINISHED":
        return
    if snapshot["state"] in {"RECOVERY_REQUIRED", "FAILED", "STOPPING", "STOPPED"}:
        raise GoldenFailure("Narration stopped or requires recovery")


def require_fixture_completion(snapshot,required_facts,injected_questions,total_questions):
    if snapshot.get("state")!="STOPPED" or snapshot.get("reason")!="FINISHED":
        raise GoldenFailure("Fixture completion budget exceeded before authored plan finished")
    if injected_questions!=total_questions or not required_facts.issubset(set(snapshot["cursor"]["completedFactIds"])):
        raise GoldenFailure("Fixture completion lacks required facts/questions")


def comment_positions(mode,seconds,count,seed):
    rng=random.Random(seed)
    if mode=='soak' and seconds==3600:
        # Seeded stratified comments avoid changing this stability run into a
        # burst/dedup experiment. Those remain separate acceptance cases.
        width=seconds*.79/count
        return [seconds*.08+width*(i+rng.uniform(.25,.75)) for i in range(count)]
    return sorted(rng.uniform(seconds*.08,seconds*.87) for _ in range(count))


def require_browser_av(chrome,normal_stop):
    if not normal_stop:raise GoldenFailure("Actual Session normal Stop missing")
    if chrome.get("recordingFailed") or chrome.get("recorderErrors"):
        raise GoldenFailure("Actual browser recording delivery failed")
    if not isinstance(chrome.get("audioPreflight"),dict) or not chrome["audioPreflight"].get("ready"):
        raise GoldenFailure("Actual browser audio clock prerequisite missing")
    if not any(row["rms"]>.001 for row in chrome.get("audioEnergy",[])):
        raise GoldenFailure("Actual browser decoded speech energy missing")
    if not chrome.get("video"):raise GoldenFailure("Actual browser video missing")
    if not chrome.get("recordedBytes") or not chrome.get("recordingChunks"):
        raise GoldenFailure("Actual browser recording bytes missing")
    if chrome.get("deliveredRecordingBytes")!=chrome["recordedBytes"] or chrome.get("deliveredRecordingChunks")!=chrome["recordingChunks"]:
        raise GoldenFailure("Actual browser recording delivery incomplete")


def private(path):
    file=Path(path)
    if not file.is_file() or file.stat().st_mode&0o077:
        raise GoldenFailure("Private credential file unavailable")
    return file.read_text().strip()


def sink_ids(logfile,sid):
    # Read actual owned Runtime telemetry, never invent peer/incarnation IDs.
    found=None
    for line in Path(logfile).read_text(errors="replace").splitlines():
        try:
            outer=json.loads(line);message=outer.get("message","")
            if not message.startswith("runtime_media_metrics "):continue
            report=json.loads(message[len("runtime_media_metrics "):])
            for session in report["sessions"]:
                if session["sessionId"]!=sid:continue
                media=session["media"]
                web=media.get("webrtc",{}).get("sink",{})
                rtmp=media.get("rtmp",{}).get("sink",{})
                peers=[peer["peerId"] for peer in web.get("peers",[]) if peer["connectionState"]=="connected"]
                if peers and rtmp.get("connectionIncarnation"):
                    found=[*peers,"rtmp:"+str(rtmp["connectionIncarnation"])]
        except (ValueError,KeyError,TypeError):pass
    return found


async def main(args):
    from playwright.async_api import async_playwright
    out=Path(args.output);out.mkdir(parents=True,exist_ok=False)
    fixture=json.loads(Path(args.fixture).read_text())
    report={"scope":"REAL_BOUND_PROVIDER_PUBLIC_API_CHROME_OBSERVER",
        "commentTransport":"MOCK_REPLAY_ONLY", "humanNaturalness":"NOT_TESTED",
        "audienceAudible":False,"correlatedAV":"NOT_ANALYSED",
        "localTransport":args.local_transport,"mode":args.mode,"requestedSeconds":args.seconds,"seed":args.seed,"fixture":fixture.get("name"),"events":[]}
    session=None;browser=None;page=None;normal_stop=False;recording_file=None;recording_writer=None;chrome_saved=False
    async with httpx.AsyncClient(base_url=args.backend,verify=False,trust_env=False,timeout=30) as client:
        async def api(method,path,payload=None,key=None):
            headers={"Origin":args.backend}
            if key:headers["Idempotency-Key"]=key
            response=await client.request(method,path,json=payload,headers=headers)
            try:packet=response.json()
            except ValueError:raise GoldenFailure("Non-JSON public response") from None
            if response.status_code>=300:
                # No raw body/request/credential is included in errors.
                raise GoldenFailure(f"Public API failed {path}: HTTP{response.status_code}/{packet.get('code','UNKNOWN')}")
            return packet.get("data")
        try:
            await api("POST","/api/v0.4/auth/login",{"username":args.username,"password":private(args.password_file)})
            profiles={}
            # The production provider-probe cooldown is shared across profiles.
            # Space distinct real probes without retrying failed mutations.
            preflight_origin=time.monotonic();last_probe_start=None
            report["preflightProbeTiming"]={"clock":"Python time.monotonic",
                "minimumStartSpacingSeconds":5.1,"attempts":[]}
            for kind,provider,config in [
                ("LLM","deepseek",{"model":"deepseek-flash","maxTokens":256}),
                ("TTS","xiaoya",{"voiceId":"xiao_ya","speed":1,"modelRef":"xiaoya-default"}),
                ("GPU_WORKER","soulx",{"workerRef":args.worker_ref}),
                ("AVATAR","soulx",{"avatarRef":args.avatar_ref,"workerProfileId":None})]:
                if kind=="AVATAR":config["workerProfileId"]=profiles["GPU_WORKER"]["profileId"]
                payload={"kind":kind,"name":"Golden "+kind,"provider":provider,"config":config}
                if kind=="LLM":payload["secret"]=private(args.llm_key_file)
                profile=await api("POST","/api/v0.3/config/profiles",payload)
                payload.pop("secret",None)
                wait_started=time.monotonic()
                if last_probe_start is not None:
                    while time.monotonic()<last_probe_start+5.1:
                        await asyncio.sleep(last_probe_start+5.1-time.monotonic())
                probe_start=time.monotonic()
                timing={"kind":kind,"startedSeconds":probe_start-preflight_origin,
                    "spacingFromPreviousSeconds":None if last_probe_start is None else probe_start-last_probe_start,
                    "cooldownWaitSeconds":probe_start-wait_started,"status":"STARTED"}
                report["preflightProbeTiming"]["attempts"].append(timing)
                last_probe_start=probe_start
                try:
                    profile=await api("POST","/api/v0.3/config/profiles/"+profile["profileId"]+"/test",{"expectedVersion":profile["version"]})
                except Exception:
                    timing.update(status="FAILED",durationSeconds=time.monotonic()-probe_start)
                    raise
                timing.update(status="PASSED",durationSeconds=time.monotonic()-probe_start)
                profile=await api("POST","/api/v0.3/config/profiles/"+profile["profileId"]+"/default",{"expectedVersion":profile["version"]})
                profiles[kind]=profile
            avatar=await api("POST","/api/v1/avatars",{"name":"Golden SoulX avatar","engine":"SOULX"})
            voice=await api("POST","/api/v1/voices",{"name":"Golden XiaoYa","provider":"xiaoya","providerVoiceId":"xiao_ya"})
            product=await api("POST","/api/v1/products",fixture["product"])
            room=await api("POST","/api/v1/live-rooms",{"name":"Golden owned room","avatarId":avatar["avatarId"],"voiceId":voice["voiceId"],
                "activeProductId":product["productId"],"systemPrompt":"自然、简短、只使用当前商品已确认事实。"})
            created=await api("POST","/api/v1/live-sessions",{"roomId":room["roomId"]});session=created["sessionId"]
            report.update(sessionId=session,productId=product["productId"],roomId=room["roomId"],profiles=profiles)
            await api("POST",f"/api/v1/live-sessions/{session}/start",{},"golden-start")
            for _ in range(600):
                state=await api("GET",f"/api/v1/live-sessions/{session}")
                if state["status"]=="LIVE":break
                if state["status"] in {"FAILED","ENDED"}:raise GoldenFailure("Bound Session failed before live")
                await asyncio.sleep(.2)
            else:raise GoldenFailure("Bound Session startup timed out")
            provider_status=await api("GET",f"/api/v0.4/sessions/{session}/providers")
            if provider_status["mode"]!="REAL" or not provider_status.get("workerEpoch"):
                raise GoldenFailure("Selected real bound provider is not ready")
            report["capturedProviders"]=provider_status
            async with async_playwright() as playwright:
                browser=await playwright.chromium.launch(channel="chrome",headless=True,args=["--autoplay-policy=no-user-gesture-required"])
                context=await browser.new_context(ignore_https_errors=True)
                cookies=[{"name":cookie.name,"value":cookie.value,"url":args.backend,"httpOnly":True,"secure":True,"sameSite":"Strict"}
                    for cookie in client.cookies.jar]
                await context.add_cookies(cookies)
                page=await context.new_page()
                recording_file=open(out/"chrome.webm","wb")
                recording_writer=ChromeRecordingWriter(recording_file)
                async def record_chunk(sequence,encoded,expected_bytes,expected_sha256):
                    recording_writer.store(sequence,encoded,expected_bytes,expected_sha256)
                await page.expose_function("__goldenRecording",record_chunk)
                await page.goto(args.backend+"/__golden/browser")
                await page.get_by_role("button",name="Enable real audio observation").click()
                await page.wait_for_function("ac && ac.state==='running'",timeout=5000)
                await page.evaluate("sid=>goldenStart(sid)",session)
                await page.wait_for_function("pc.connectionState==='connected'",timeout=30000)
                audio_preflight=await page.evaluate("goldenAudioReady()")
                report["browserAudioPreflight"]=audio_preflight
                if not audio_preflight["ready"]:
                    raise GoldenFailure("Actual browser audio clock stalled before narration")
                for _ in range(100):
                    required=sink_ids(args.runtime_log,session)
                    if required:break
                    await asyncio.sleep(.1)
                else:raise GoldenFailure("Actual named required sinks unavailable")
                plan=fixture["plan"]|{"requiredSinks":required,"requestId":"golden-plan","scriptVersion":fixture.get("scriptVersion","golden-real-1")}
                document=await api("POST",f"/api/v0.5/narration/{session}/start",plan)
                report.update(narrationId=document["plan"]["narrationId"],requiredSinks=required,chromeVersion=browser.version)
                began=time.monotonic();questions=fixture["questions"]
                if args.mode=="ten-minute" and (args.seconds<600 or len(questions)<5):
                    raise GoldenFailure("Formal G1 requires >=600 seconds and >=5 questions")
                deadline=1800 if args.mode=="ten-minute" else 180 if args.mode=="fixture-completion-smoke" else args.seconds
                report["observationBudgetSeconds"]=deadline
                required_facts=set(fact for beat in document["plan"]["beats"] for fact in beat["requiredFactIds"])
                positions=comment_positions(args.mode,args.seconds,len(questions),args.seed)
                report["commentPositionsSeconds"]=positions;next_question=0
                checkpoint_targets=[90,300,900,1800,2700,3600] if args.mode=='soak' and args.seconds==3600 else []
                next_checkpoint=0;report['checkpoints']=[]
                while time.monotonic()-began<deadline:
                    elapsed=time.monotonic()-began
                    if next_question<len(questions) and elapsed>=positions[next_question]:
                        answer=await api("POST",f"/api/v0.4/interaction/{session}/mock",{"text":questions[next_question],"users":1})
                        report["events"].append({"kind":"COMMENT_INJECTED","question":questions[next_question],"elapsedSeconds":elapsed,
                            "browserAt":await page.evaluate("performance.now()"),"response":answer});next_question+=1
                    snapshot=await api("GET",f"/api/v0.5/narration/{session}/")
                    try:
                        require_observable_state(snapshot)
                    except GoldenFailure:
                        # Preserve the public failure projection before finally's
                        # normal Stop can overwrite its original disposition.
                        report['failureNarrationBeforeStop']=snapshot
                        report['failureElapsedSeconds']=time.monotonic()-began
                        raise
                    if next_checkpoint<len(checkpoint_targets) and elapsed>=checkpoint_targets[next_checkpoint]:
                        browser_state=await page.evaluate('goldenCheckpoint()')
                        entry={'targetSeconds':checkpoint_targets[next_checkpoint],
                            'elapsedSeconds':time.monotonic()-began,'browser':browser_state,
                            'narrationState':snapshot['state'],'reason':snapshot['reason'],
                            'nextOrdinal':snapshot['cursor']['nextOrdinal'],
                            'completedFacts':len(snapshot['cursor']['completedFactIds'] or []),
                            'completedSegments':len(snapshot['cursor']['completedSegmentIds'] or [])}
                        report['checkpoints'].append(entry)
                        await page.screenshot(path=str(out/f"checkpoint-{checkpoint_targets[next_checkpoint]:04d}.png"))
                        (out/'progress.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
                        next_checkpoint+=1
                        if browser_state['peerCreations']!=1 or browser_state['connectionState']!='connected' or browser_state['recordingFailed']:
                            raise GoldenFailure('One-hour browser connection/recording prerequisite lost')
                    if snapshot["reason"]=="FINISHED":
                        if args.mode=="fixture-completion-smoke":
                            require_fixture_completion(snapshot,required_facts,next_question,len(questions))
                            break
                        if args.mode=="ten-minute" and elapsed<args.seconds:
                            raise GoldenFailure("Authored plan finished early: fixture duration insufficient")
                        if args.mode=="ten-minute":
                            if next_question != len(questions) or not required_facts.issubset(set(snapshot["cursor"]["completedFactIds"])):
                                raise GoldenFailure("Formal G1 plan completion lacks required facts/questions")
                            # F additionally verifies terminal selected turns from SQL.
                            break
                        if args.mode=="short":
                            report["shortPlanFinishedEarly"]=elapsed<args.seconds
                            break
                        if elapsed<args.seconds:
                            raise GoldenFailure("Soak authored fixture exhausted early")
                    await asyncio.sleep(.2)
                if args.mode=='soak' and args.seconds==3600:
                    browser_state=await page.evaluate('goldenCheckpoint()')
                    if browser_state['peerCreations']!=1 or browser_state['connectionState']!='connected' or browser_state['recordingFailed']:
                        raise GoldenFailure('One-hour final browser connection/recording prerequisite lost')
                    report['checkpoints'].append({'targetSeconds':3600,'elapsedSeconds':time.monotonic()-began,'browser':browser_state,
                        'narrationState':snapshot['state'],'reason':snapshot['reason'],'nextOrdinal':snapshot['cursor']['nextOrdinal'],
                        'completedFacts':len(snapshot['cursor']['completedFactIds'] or []),'completedSegments':len(snapshot['cursor']['completedSegmentIds'] or [])})
                    await page.screenshot(path=str(out/'checkpoint-3600.png'))
                    if next_question!=len(questions):raise GoldenFailure('One-hour comments not all injected')
                    report['oneHourScope']='one continuous Session/peer/recording; planned tail interrupted by normal Stop, not full-plan coverage'
                if args.mode=="ten-minute" and snapshot.get("reason")!="FINISHED":
                    raise GoldenFailure("Formal G1 deadline exceeded before authored plan completion")
                if args.mode=="fixture-completion-smoke":
                    require_fixture_completion(snapshot,required_facts,next_question,len(questions))
                    report["fixtureCompletionClaim"]="PENDING_SQL_SELECTED_TURN_AND_AV_AUDIT"
                report["continuousDurationSeconds"]=time.monotonic()-began
                report["finalNarrationBeforeStop"]=snapshot
                report["factCoverageClaim"]="PENDING_SQL_AUDIT" if args.mode=="ten-minute" else "NOT_FORMAL_COMPLETE_FACT_COVERAGE"
                await api("POST",f"/api/v1/live-sessions/{session}/stop",{},"golden-stop")
                for _ in range(200):
                    state=await api("GET",f"/api/v1/live-sessions/{session}")
                    if state["status"]=="ENDED":normal_stop=True;break
                    await asyncio.sleep(.1)
                chrome=await page.evaluate("goldenFinish()")
                recording_file.close()
                (out/"chrome.json").write_text(json.dumps(chrome,ensure_ascii=False))
                chrome_saved=True
                report.update(normalStop=normal_stop,chromeAudioObserved=any(row["rms"]>.001 for row in chrome["audioEnergy"]),
                    chromeVideoFrames=len(chrome["video"]),recordedBytes=(out/"chrome.webm").stat().st_size)
                require_browser_av(chrome,normal_stop)
                # Correlation, complete turn/fact SQL proofs and RTMP audit are
                # separate oracles; observing audio/video alone is not PASS.
                report["status"]="OBSERVED_PENDING_INDEPENDENT_SQL_AV_QUALITY_AUDIT"
        except Exception as exc:
            report.update(status="FAIL",errorType=type(exc).__name__,reason=str(exc) if isinstance(exc,GoldenFailure) else "Golden observer failed")
            raise
        finally:
            if session and not normal_stop:
                try:await api("POST",f"/api/v1/live-sessions/{session}/stop",{},"golden-stop")
                except Exception:report["cleanupPending"]=True
            if page and not chrome_saved:
                try:
                    chrome=await page.evaluate("goldenFinish()")
                    (out/"chrome.json").write_text(json.dumps(chrome,ensure_ascii=False))
                except Exception:report["browserDiagnosticPending"]=True
            if browser:await browser.close()
            if recording_file and not recording_file.closed:recording_file.close()
            if recording_writer:
                recording_data=(out/"chrome.webm").read_bytes()
                report["recordingStorage"]={"failed":recording_writer.failed,"bytes":len(recording_data),
                    "sha256":hashlib.sha256(recording_data).hexdigest(),"chunks":recording_writer.chunks}
            (out/"result.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    for name in ["backend","username","password-file","llm-key-file","worker-ref","avatar-ref","fixture","runtime-log","output"]:
        parser.add_argument("--"+name,required=True)
    parser.add_argument("--local-transport",choices=["tcp","uds"],default="tcp")
    parser.add_argument("--mode",choices=["short","fixture-completion-smoke","ten-minute","soak"],default="short")
    parser.add_argument("--seconds",type=int,default=600);parser.add_argument("--seed",type=int,default=20261012)
    asyncio.run(main(parser.parse_args()))
