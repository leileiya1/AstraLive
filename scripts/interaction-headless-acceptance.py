"""Opt-in formal REAL Session with Scheduler and RTMP, without a preview subscriber.

Uses an owned room created by the Chrome acceptance fixture. Private credentials
stay in the caller's directory. This is not browser/speaker/platform observation.
"""
import http.cookiejar
import json
import os
from pathlib import Path
import ssl
import time
import urllib.error
import urllib.request
import uuid


def main():
    if os.environ.get('RUN_REAL_INTERACTION') != '1':
        raise RuntimeError('Explicit real acceptance opt-in required')
    root = Path(os.environ['INTERACTION_PRIVATE_DIR'])
    evidence = Path(os.environ['INTERACTION_EVIDENCE'])
    if evidence.exists():
        raise RuntimeError('Choose a new evidence filename')
    fixture = json.loads(Path(os.environ['INTERACTION_ROOM_FIXTURE']).read_text())
    origin = os.environ.get('INTERACTION_ORIGIN', 'https://localhost:26843')
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),
                                        urllib.request.HTTPSHandler(context=ssl._create_unverified_context()))
    result = dict(classification='MOCK_COMMENT_REAL_HEADLESS_SOULX_RTMP', errors=[])
    sid = ''
    def api(path, method='GET', data=None):
        headers = {'Content-Type':'application/json', 'Origin':origin, 'Idempotency-Key':str(uuid.uuid4())}
        request = urllib.request.Request(origin+path, None if data is None else json.dumps(data).encode(), headers, method=method)
        try:
            with opener.open(request, timeout=15) as response:
                return response.status, json.load(response)['data']
        except urllib.error.HTTPError as exc:
            return exc.code, json.load(exc).get('code')
    def private(url):
        request = urllib.request.Request(url, headers={'Authorization':'Bearer '+(root/'runtime-control-token').read_text().strip()})
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.load(response)
    def wait(fn, timeout=60):
        deadline = time.monotonic()+timeout
        while time.monotonic()<deadline:
            value = fn()
            if value:
                return value
            time.sleep(.2)
        raise TimeoutError('Acceptance condition timed out')
    def trace(uid):
        traces = private(f'http://127.0.0.1:26800/internal/v0.4/sessions/{sid}/interaction-traces')['traces']
        return next((t for t in traces if t['utteranceId']==uid and 'utterance_completed' in t['points']), None)
    try:
        status, _ = api('/api/v0.4/auth/login', 'POST', dict(username='operator', password=(root/'operator-password').read_text()))
        assert status==200
        status, session = api('/api/v1/live-sessions', 'POST', dict(roomId=fixture['roomId']))
        assert status==201
        sid = session['sessionId'];result['sessionId']=sid
        assert api(f'/api/v1/live-sessions/{sid}/start', 'POST', {})[0]==202
        wait(lambda: api(f'/api/v1/live-sessions/{sid}')[1]['status']=='LIVE')
        result['providersBefore']=api(f'/api/v0.4/sessions/{sid}/providers')[1]
        assert result['providersBefore']['mode']=='REAL'
        assert api(f'/api/v0.4/interaction/{sid}/mock', 'POST', dict(text='价格多少？', users=1))[0]==202
        chosen=wait(lambda: api(f'/api/v0.4/interaction/{sid}/')[1].get('utteranceId'))
        completed=wait(lambda: trace(chosen))
        assert 'avatar_first_generated_frame' in completed['points']
        result['selectedTrace']=completed
        sink=private('http://127.0.0.1:26836/snapshot')
        video=next(r for r in sink['rows'] if r['kind']=='video' and r['marker']==completed['media']['speechMarker'] and r['generation']==completed['media']['generationId'])
        audio=next(r for r in sink['rows'] if r['kind']=='audio' and video['pts']-.08<=r['pts']<video['pts']+2)
        result['decodedReceiver']=dict(firstVideo=video, firstAudio=audio, counts=sink['counts'])
        legacy=dict(eventType='COMMENT', roomId=fixture['roomId'], user=dict(externalId='mock-legacy',nickname='mock-viewer'),payload=dict(text='价格多少？'))
        status, response=api('/api/v1/dev/platform-events','POST',legacy)
        result['legacyRunningStatus']=status;assert status==202
        result['legacyTrace']=wait(lambda: trace(response['utteranceId']))
        result['snapshot']=api(f'/api/v0.4/interaction/{sid}/')[1]
        after=api(f'/api/v0.4/sessions/{sid}/providers')[1]
        result['bindingUnchanged']=result['providersBefore']['bindingId']==after['bindingId'] and result['providersBefore']['profiles']==after['profiles']
        assert result['bindingUnchanged']
    except Exception as exc:
        result['errors'].append(type(exc).__name__)
        raise
    finally:
        if sid:
            assert api(f'/api/v1/live-sessions/{sid}/stop','POST',{})[0]==202
            result['finalState']=wait(lambda: api(f'/api/v1/live-sessions/{sid}')[1]['status']=='ENDED') and 'ENDED'
            if 'legacy' in locals():
                result['legacyStoppedStatus']=api('/api/v1/dev/platform-events','POST',legacy)[0]
                assert result['legacyStoppedStatus']==409
        with evidence.open('x') as file:
            json.dump(result,file,indent=2)
        print(json.dumps(dict(errors=result['errors'], finalState=result.get('finalState'), bindingUnchanged=result.get('bindingUnchanged'))))


if __name__=='__main__':
    main()
