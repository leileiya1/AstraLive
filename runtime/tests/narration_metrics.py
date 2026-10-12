"""Reproducible metrics for the explicitly synthetic native-sink fixture.

Audio pulses have no unique ID. Chronological assignment is a proxy permitted
only with complete equal-count coverage; video is decoded from unique markers.
Missing samples remain null and are counted, never converted into zero latency.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path


def summary(values):
    known = sorted(v for v in values if v is not None)
    return {"n": len(known), "missing": len(values)-len(known),
            "p50": known[math.ceil(len(known)*.5)-1] if known else None,
            "p95": known[math.ceil(len(known)*.95)-1] if known else None,
            "max": max(known) if known else None}


def metrics(result):
    events = [e for e in result["events"] if e.get("marker") is not None]
    chrome = result["chrome"]
    video = {row["marker"]: row["at"] for row in chrome["video"]}
    complete = (len(events) == len(chrome["audio"]) and len(events) > 0
                and len({e["marker"] for e in events}) == len(events)
                and {e["marker"] for e in events}.issubset(video))
    audio = {e["marker"]: p["at"] for e,p in zip(events,chrome["audio"])} if complete else {}
    comments = [e for e in result["events"] if e["lane"] == "COMMENT_SELECTED"]
    answers = [e for e in events if e["lane"] == "AUDIENCE_ANSWER"]
    pairs=[]
    for index,comment in enumerate(comments):
        answer = answers[index] if index < len(answers) else {}
        marker = answer.get("marker")
        pairs.append({"sourceId":comment["commandId"], "answerSegmentId":answer.get("segmentId"),
                      "answerMarker":marker,"commentBrowserAt":comment["browserAt"],
                      "comment_to_answer_audio_ms":audio[marker]-comment["browserAt"] if marker in audio else None,
                      "comment_to_answer_video_ms":video[marker]-comment["browserAt"] if marker in video else None})
    return {"clockDomain":"Chrome performance.now", "scope":"synthetic pulse proxy and unique decoded video; not physical audibility, semantic relevance, human quality or busy SLA",
            "audioPairing":"chronological, requires equal counts plus unique complete video coverage; pulses have no unique audio ID",
            "selectedComments":len(comments),"markedSegments":len(events), "decodedSegments":len(video),
            "audioPulseCount":len(chrome["audio"]),"audioCoverageComplete":complete,"pairs":pairs,
            "comment_to_answer_audio_ms":summary([p["comment_to_answer_audio_ms"] for p in pairs]),
            "comment_to_answer_video_ms":summary([p["comment_to_answer_video_ms"] for p in pairs]),
            "notCollected":["comment_to_interrupt_decision_ms", "interrupt_to_narration_stop_ms",
                            "answer_end_to_resume_audio_ms", "process_resource_timeseries", "real_GPU_stale_epoch_frames_dropped"]}


if __name__ == "__main__":
    parser=argparse.ArgumentParser();parser.add_argument("source");parser.add_argument("output")
    args=parser.parse_args();raw=Path(args.source).read_bytes()
    out={"source":args.source,"sourceSha256":hashlib.sha256(raw).hexdigest(),"metrics":metrics(json.loads(raw))}
    Path(args.output).write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n")
