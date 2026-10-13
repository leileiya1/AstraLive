"""Actual BoundXiaoYa CPU CNY rendering probe, no LLM/GPU/media substitution."""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import wave

from app.models import VoiceConfig
from app.providers import GenerationContext
from app.session_binding import BoundXiaoYa
from app.voice_stream import StreamingVoiceAdapter


async def main(args):
    output=Path(args.output);output.mkdir(parents=True,exist_ok=False)
    model=Path(args.model_dir)
    provider=await asyncio.to_thread(BoundXiaoYa,str(model))
    adapter=StreamingVoiceAdapter(provider,"xiao_ya")
    rows=[]
    for index,amount in enumerate(("99.00","0.00","99.50")):
        text="这款目前价格是人民币"+amount+"元。"
        context=GenerationContext(index+1,"spoken-cny-preflight","cpu-only","u")
        pcm=b"".join([chunk.pcm async for chunk in adapter.synthesize_stream(text,VoiceConfig(voiceId="xiao_ya",provider="xiaoya"),context)])
        count=len(pcm)//2;pad=-count%640
        name=f"speech-{index}.wav"
        with wave.open(str(output/name),"wb") as wav:
            wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(16000);wav.writeframes(pcm)
        rows.append({"text":text,"samples":count,"pad":pad,"paddedMs":(count+pad)*1000//16000,
            "pcmSHA256":hashlib.sha256(pcm).hexdigest(),"nonSilent":any(pcm),"wave":name,"fits8s":count+pad<=128000})
    report={"scope":"actual BoundXiaoYa/Sherpa CPU TTS only; no GPU/sink/currency human hearing claim",
        "modelSHA256":hashlib.sha256((model/"zh_CN-xiao_ya-medium.onnx").read_bytes()).hexdigest(),
        "rows":rows,"humanPronunciation":"NOT TESTED",
        "status":"PASS" if all(row["nonSilent"] and row["fits8s"] for row in rows) else "FAIL"}
    (output/"result.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps(report,ensure_ascii=False))
    return int(report["status"]!="PASS")


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir",required=True);parser.add_argument("--output",required=True)
    raise SystemExit(asyncio.run(main(parser.parse_args())))
