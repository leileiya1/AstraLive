#!/usr/bin/env python3
"""Fresh CPU speech sizing for an authored fixture; never live/GPU acceptance."""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import sys
import subprocess

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'runtime'))
from app.real_tts import SherpaOnnxTTSProvider
from app.voice_stream import StreamingVoiceAdapter
from app.models import VoiceConfig
from app.providers import GenerationContext


async def run(args):
    out=Path(args.output);out.mkdir(parents=True,exist_ok=False)
    fixture=Path(args.fixture);data=json.loads(fixture.read_text());values=data['trustedBuiltinPreview']
    provider=SherpaOnnxTTSProvider(args.model_dir,speaker_id=0,num_threads=2)
    adapter=StreamingVoiceAdapter(provider,'xiao_ya');voice=VoiceConfig(voiceId='xiao_ya',provider='xiaoya')
    pin=subprocess.check_output(['git','-C',str(ROOT),'rev-parse',args.source],text=True).strip()
    report={'source':pin,'requestedSource':args.source,'scope':'fresh real cached CPU TTS duration/framing only; no live/GPU/naturalness',
            'fixtureSHA256':hashlib.sha256(fixture.read_bytes()).hexdigest(),'rows':[],'nativeSampleRate':provider.sample_rate,
            'outputSampleRate':16000,'speakerId':0,'speed':1,'threads':2,'status':'RUNNING'}
    for beat in data['plan']['beats']:
        for statement in beat['statements']:
            text=statement['text']
            for key,value in values.items():text=text.replace('{{'+key+'}}',str(value))
            if '{{' in text:raise ValueError('Unresolved authored placeholder')
            pcm=bytearray();count=0
            async for timed in adapter.timed_stream(text,voice,GenerationContext(len(report['rows'])+1,'cpu-preflight','NOT_LIVE','fixture-sizing')):
                c=timed.chunk
                assert c.sample_rate==16000 and c.channels==1 and c.sequence==count
                assert timed.first_sample_index==len(pcm)//2
                pcm.extend(c.pcm);count+=1
            n=len(pcm)//2;pad=(-n)%640
            row={'ordinal':len(report['rows'])+1,'text':text,'factIds':statement['factIds'],
                 'samples':n,'padSamples':pad,'paddedSeconds':(n+pad)/16000,
                 'pcmSHA256':hashlib.sha256(pcm).hexdigest(),'within8s':0<n and n+pad<=128000}
            report['rows'].append(row);print(json.dumps(row,ensure_ascii=False),flush=True)
            (out/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    report.update(status='PASS' if all(r['within8s'] for r in report['rows']) and sum(r['samples']+r['padSamples'] for r in report['rows'])/16000>=args.minimum_seconds else 'FAIL',
                  paddedSeconds=sum(r['samples']+r['padSamples'] for r in report['rows'])/16000,
                  over8s=[r['ordinal'] for r in report['rows'] if not r['within8s']])
    (out/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='rows'}),flush=True)
    return int(report['status']!='PASS')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for arg in ('fixture','model-dir','output','source'):parser.add_argument('--'+arg,required=True)
    parser.add_argument('--minimum-seconds',type=float,default=3600)
    raise SystemExit(asyncio.run(run(parser.parse_args())))
