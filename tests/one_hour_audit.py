"""Summarize the completed browser-connected run without changing the system."""
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import statistics
import sys

import redis
from jsonschema import Draft202012Validator, FormatChecker


root = Path(__file__).resolve().parents[1]
evidence = root / "integration/evidence"
tag = sys.argv[1] if len(sys.argv) > 1 else "60m"
browser = json.loads((evidence / f"browser-connected-soak-{tag}.json").read_text())
runtime = json.loads((evidence / f"browser-connected-runtime-{tag}.json").read_text())
system = json.loads((evidence / f"browser-connected-system-{tag}.json").read_text())
sid = browser["session_id"]

client = redis.Redis.from_url("redis://127.0.0.1:16391/14")
events = []
for _, fields in client.xrange("dh.runtime.events.v1"):
    raw = fields.get(b"event", fields.get(b"data"))
    if raw is None:
        continue
    event = json.loads(raw)
    if event.get("sessionId") == sid:
        events.append(event)
(evidence / f"browser-connected-events-{tag}.json").write_text(json.dumps(events, ensure_ascii=False, indent=2) + "\n")
schema = json.loads((root / "contracts/events/runtime-event.schema.json").read_text())
validator = Draft202012Validator(schema, format_checker=FormatChecker())
invalid = sum(bool(list(validator.iter_errors(event))) for event in events)
event_types = Counter(event["eventType"] for event in events)

queued = set()
queue_sizes = []
for event in events:
    kind, uid = event["eventType"], event.get("utteranceId")
    if kind == "UTTERANCE_QUEUED" and uid:
        queued.add(uid)
    elif kind in {"UTTERANCE_GENERATING", "UTTERANCE_INTERRUPTED", "UTTERANCE_FAILED", "UTTERANCE_COMPLETED"} and uid:
        queued.discard(uid)
    queue_sizes.append(len(queued))

tools = []
proxy_file = evidence / f"browser-connected-runtime-tool-{tag}.jsonl"
if proxy_file.exists():
    for line in proxy_file.read_text().splitlines():
        if line.strip():
            row = json.loads(line)
            if "/internal/v1/tools/products/" in row.get("path", ""):
                tools.append(row)

periodic = browser["samples"]
cycles = browser["cycle_media"]
keys = ["audioPackets", "audioBytes", "audioEnergy", "videoPackets", "framesDecoded"]
def nonincrease(rows, field):
    return sum(b[field] <= a[field] for a, b in zip(rows, rows[1:]))

def distribution(values):
    if not values:
        return "NOT AVAILABLE"
    values = sorted(values)
    return {"min": values[0], "p50": round(statistics.median(values), 1),
            "p95": values[min(len(values) - 1, int(0.95 * (len(values) - 1)))], "max": values[-1]}

samples = system["samples"]
rss = [s["runtime"]["rss_kib"] / 1024 for s in samples if "runtime" in s]
audit = {
    "session_id": sid, "browser_verdict": browser.get("verdict"),
    "browser_connected_monitor_s": browser.get("actual_connected_monitor_s"),
    "browser_sample_count": len(periodic), "cycle_media_count": len(cycles),
    "runtime_cycles": runtime.get("cycles"), "runtime_duration_s": runtime.get("actual_duration_s"),
    "runtime_stop": runtime.get("stop"), "runtime_errors": runtime.get("errors"),
    "business_questions": runtime.get("business_questions"),
    "force_interrupts": runtime.get("force_interrupts"),
    "lower_priority_interrupts": runtime.get("lower_priority_interrupts"),
    "none_fifo_checks": runtime.get("none_fifo_checks"),
    "event_count": len(events), "event_schema_invalid": invalid, "event_types": dict(event_types),
    "speech_waiting_queue": {"max": max(queue_sizes, default=0), "last": queue_sizes[-1] if queue_sizes else None},
    "audio_queue_size": "NOT AVAILABLE", "video_queue_size": "NOT AVAILABLE",
    "tool_count": len(tools), "tool_statuses": dict(Counter(str(row["status"]) for row in tools)),
    "product_tool_count": sum(row["path"].count("/products/") and not row["path"].endswith(("/stock", "/price")) for row in tools),
    "stock_tool_count": sum(row["path"].endswith("/stock") for row in tools),
    "price_tool_count": sum(row["path"].endswith("/price") for row in tools),
    "periodic_nonincrease": {key: nonincrease(periodic, key) for key in keys},
    "cycle_nonincrease": {key: nonincrease([row["browser_media"] for row in cycles], key) for key in keys},
    "periodic_disconnected_samples": sum(s["connection"] != "connected" or s["ice"] not in ("connected", "completed") for s in periodic),
    "cycle_disconnected_samples": sum(row["browser_media"]["connection"] != "connected" or row["browser_media"]["ice"] not in ("connected", "completed") for row in cycles),
    "latency": {key: distribution([row[key] for row in runtime["latencies"]]) for key in ("event_to_speech_ms", "tts_first_chunk_ms", "avatar_first_frame_ms")},
    "browser_media_start_ms": "NOT AVAILABLE",
    "resource_sample_count": len(samples),
    "rss_mib": {"first": rss[0], "peak": max(rss), "last": rss[-1],
                "first_10_mean": round(statistics.mean(rss[:10]), 1), "last_10_mean": round(statistics.mean(rss[-10:]), 1),
                "strictly_monotonic": all(b > a for a, b in zip(rss, rss[1:]))} if rss else "NOT AVAILABLE",
    "event_sha256": sha256((evidence / f"browser-connected-events-{tag}.json").read_bytes()).hexdigest(),
}
(evidence / f"browser-connected-audit-{tag}.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n")
print(json.dumps(audit, ensure_ascii=False, indent=2))
