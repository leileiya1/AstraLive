#!/usr/bin/env python3
"""One fresh full V3 real cached CPU synthesis; never a live Golden run."""
import asyncio
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
import re
import sys
import time
import traceback

OUT = Path(__file__).resolve().parent
SOURCE = '609ee76cec0924a44d683152d8e3d0285966a4ea'
SRC = OUT/'source'
MODEL = Path('/Users/sapiece/innovationProject/AstraLive/runtime/.local/vits-piper-zh_CN-xiao_ya-medium')
sys.path.insert(0,str(SRC/'runtime'))
from app.real_tts import SherpaOnnxTTSProvider
from app.voice_stream import StreamingVoiceAdapter
from app.models import VoiceConfig
from app.providers import GenerationContext


def sha(data):
    return 'sha256:'+hashlib.sha256(data).hexdigest()


def stamp():
    return datetime.now(timezone.utc).isoformat()


async def main():
    started = time.monotonic()
    fixture_path = SRC/'integration/v0.5/fixtures/real_golden_catalog.json'
    catalog = json.loads(fixture_path.read_text())
    assert catalog['fixtureVersion']=='real-golden-catalog-3'
    preview = catalog['trustedBuiltinPreview']
    builtin = {k:preview[k] for k in ('name','price','stock','sizes','currency')}
    assert builtin == {'name':'桌面整理指南','price':'99.00','stock':'20','sizes':'电子版','currency':'CNY'}
    assert catalog['product']['name']==builtin['name'] and catalog['product']['price']==99
    assert catalog['product']['currency']=='CNY' and catalog['product']['stock']==20
    assert catalog['product']['sizes']==['电子版']
    cases = []
    for beat_index,beat in enumerate(catalog['plan']['beats'],1):
        for statement_index,statement in enumerate(beat['statements'],1):
            template = statement['text']
            assert len(statement['factIds'])==1
            assert catalog['facts'][statement['factIds'][0]]==template
            def replace(match):
                assert match.group(1) in builtin,'UNAUTHORIZED_TEMPLATE'
                return builtin[match.group(1)]
            text = re.sub(r'\{\{([A-Za-z_]+)\}\}',replace,template)
            assert '{{' not in text and '}}' not in text
            cases.append({'kind':'V3_NARRATION_STATEMENT','beatOrdinal':beat_index,
                          'statementOrdinal':statement_index,'factIds':statement['factIds'],
                          'template':template,'text':text})
    assert len(cases)==140 and len({r['factIds'][0] for r in cases})==140
    extras = [
        {'kind':'CANONICAL_CNY_PRICE_ANSWER','text':'这款目前价格是人民币99.00元。','factIds':['price']},
        {'kind':'APPROVED_FACT_FREE_BRIDGE','text':'说到这里，接下来看看下一项讲解内容。','factIds':[]},
        {'kind':'APPROVED_FACT_FREE_BRIDGE','text':'这个问题也正好引出了下一项讲解内容，我们接着往下看。','factIds':[]},
    ]
    files = ['zh_CN-xiao_ya-medium.onnx','lexicon.txt','tokens.txt','phone.fst','date.fst','number.fst']
    model_hashes = [{'file':n,'bytes':(MODEL/n).stat().st_size,'sha256':sha((MODEL/n).read_bytes())} for n in files]
    (OUT/'modelhash.json').write_text(json.dumps({'modelDir':str(MODEL),'files':model_hashes},indent=2)+'\n')
    (OUT/'fixturehash.json').write_text(json.dumps({'source':SOURCE,'fixture':str(fixture_path),
        'sha256':sha(fixture_path.read_bytes()),'fixtureVersion':catalog['fixtureVersion'],
        'scriptVersion':catalog['scriptVersion'],'trustedBuiltinPreview':preview,
        'productionSourceHashes':{str(p.relative_to(SRC)):sha(p.read_bytes()) for p in
            [SRC/'runtime/app/real_tts.py',SRC/'runtime/app/voice_stream.py',SRC/'runtime/app/models.py',SRC/'runtime/app/providers.py']}},indent=2,ensure_ascii=False)+'\n')
    result = {'scope':'REAL_CACHED_CPU_TTS_FULL_FRESH_V3_SYNTHESIS_NOT_LIVE_NOT_GOLDEN_NOT_NATURALNESS',
        'source':SOURCE,'startedAt':stamp(),'fixtureSHA256':sha(fixture_path.read_bytes()),
        'provider':'PRODUCTION_SherpaOnnxTTSProvider_StreamingVoiceAdapter_PCM16kConverter',
        'config':{'provider':'cpu','voiceId':'xiao_ya','speakerId':0,'speed':1,'threads':2,'outputSampleRate':16000},
        'versions':{p:importlib.metadata.version(p) for p in ('sherpa-onnx','av','numpy','pydantic')},
        'rows':[],'emptyBridge':{'text':'','status':'VALID_EMPTY_CHOICE_NO_TTS_OR_MEDIA_REQUIRED'},
        'liveGolden':'NOT_TESTED','audible':'NOT_TESTED','humanNaturalness':'NOT_TESTED',
        'durationRule':'sum ONLY this fresh run complete narration source samples, no historical synthesis or extras'}
    def checkpoint():
        narration = [r for r in result['rows'] if r['kind']=='V3_NARRATION_STATEMENT']
        complete = [r for r in narration if r['synthesisStatus']=='COMPLETE']
        result.update(completedNarrationCount=len(complete),requestedNarrationCount=140,
            freshNarrationOriginalSeconds=sum(r['sourceSamples16k'] for r in complete)/16000,
            freshNarrationPaddedSeconds=sum(r['paddedSamples16k'] for r in complete)/16000,
            overEightSeconds=[{'ordinal':r['ordinal'],'kind':r['kind'],'samples':r['paddedSamples16k']} for r in result['rows'] if r.get('paddedSamples16k',0)>128000],
            failures=[{'ordinal':r['ordinal'],'kind':r['kind'],'exceptionType':r.get('exceptionType')} for r in result['rows'] if r['synthesisStatus']!='COMPLETE'],
            elapsedWallSeconds=time.monotonic()-started)
        (OUT/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    provider = SherpaOnnxTTSProvider(str(MODEL), speaker_id=0, num_threads=2)
    result['nativeSampleRate'] = provider.sample_rate
    adapter = StreamingVoiceAdapter(provider,'xiao_ya')
    voice = VoiceConfig(voiceId='xiao_ya',provider='xiaoya')
    checkpoint()
    for ordinal,case in enumerate(cases+extras,1):
        t = time.monotonic()
        pcm = bytearray()
        chunk_count = 0
        row = {'ordinal':ordinal,**case}
        try:
            ctx=GenerationContext(ordinal,'local-cpu-v3-preflight','NOT_A_LIVE_SESSION','preflight-'+str(ordinal))
            async for timed in adapter.timed_stream(case['text'],voice,ctx):
                chunk = timed.chunk
                assert chunk.sample_rate==16000 and chunk.channels==1
                assert chunk.generation_id==ordinal and chunk.sequence==chunk_count
                assert len(chunk.pcm)%2==0 and timed.first_sample_index==len(pcm)//2
                assert timed.pts_us==(len(pcm)//2)*1000000//16000
                pcm.extend(chunk.pcm);chunk_count+=1
            assert pcm
            samples = len(pcm)//2
            pad = (-samples)%640
            padded = pcm+bytes(2*pad)
            row.update(synthesisStatus='COMPLETE',chunkCount=chunk_count,
                sourceSamples16k=samples,padSamples640=pad,paddedSamples16k=samples+pad,
                originalDurationSeconds=samples/16000,paddedDurationSeconds=(samples+pad)/16000,
                prePadPCMSHA256=sha(pcm),readyContentHash=sha(padded),
                workerFrameCount=(samples+pad)//640,withinEightSecondProfile=(samples+pad)<=128000,
                zeroPadVerified=padded[len(pcm):]==bytes(2*pad),synthesisWallSeconds=time.monotonic()-t)
        except Exception as exc:
            row.update(synthesisStatus='FAILED',exceptionType=type(exc).__name__,exceptionMessage=str(exc),
                       partialSamples16k=len(pcm)//2,synthesisWallSeconds=time.monotonic()-t)
            traceback.print_exc()
        result['rows'].append(row)
        checkpoint()
        print(json.dumps(row,ensure_ascii=False),flush=True)
    result['endedAt']=stamp()
    result['cpuPreflightStatus']='PASS' if result['completedNarrationCount']==140 and result['freshNarrationOriginalSeconds']>=600 and not result['overEightSeconds'] and not result['failures'] else 'FAIL'
    checkpoint()
    print(json.dumps({k:v for k,v in result.items() if k not in ('rows','productionSourceHashes')},ensure_ascii=False),flush=True)
    return 0 if result['cpuPreflightStatus']=='PASS' else 1


if __name__=='__main__':
    sys.exit(asyncio.run(main()))
