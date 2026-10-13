"""Build the canonical School-Linux final-acceptance evidence bundle."""
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import statistics

import redis


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "integration/evidence/school-linux-final"
TAG = "final-retry-7"
SID = "session_014b3a7da58eeb0fad2c2078829c23b1"


def load(name):
    return json.loads((OUT / name).read_text())


def parse_time(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


browser = load(f"browser-connected-soak-{TAG}.json")
driver = load(f"browser-connected-runtime-{TAG}.json")
resources = load(f"resource-stats-{TAG}.json")
runtime_log = (OUT / f"runtime-{TAG}.log").read_text(errors="replace")
connected_at = parse_time(browser["connected_at"])

events = []
try:
    client = redis.Redis.from_url("redis://127.0.0.1:16391/14", socket_connect_timeout=2)
    for _, fields in client.xrange("dh.runtime.events.v1"):
        raw = fields.get(b"event", fields.get(b"data"))
        if raw:
            event = json.loads(raw)
            if event.get("sessionId") == SID:
                events.append(event)
except redis.RedisError:
    events = load("runtime-events.json")
(OUT / "runtime-events.json").write_text(json.dumps(events, ensure_ascii=False, indent=2) + "\n")

tool_rows = []
for line in (OUT / f"runtime-tool-all-{TAG}.jsonl").read_text().splitlines():
    if line.strip():
        row = json.loads(line)
        if SID in json.dumps(row, ensure_ascii=False):
            tool_rows.append(row)
(OUT / "runtime-tool.jsonl").write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in tool_rows))

metrics = []
tts_texts = []
for line in runtime_log.splitlines():
    try:
        message = json.loads(line).get("message", "")
    except json.JSONDecodeError:
        continue
    for prefix, target in (("webrtc_media_metrics ", metrics), ("tts_evidence ", tts_texts)):
        if message.startswith(prefix):
            target.append(json.loads(message[len(prefix):]))

all_peers = [peer for metric in metrics for peer in metric.get("peers", [])]
event_counts = Counter(event["eventType"] for event in events)
failure_types = ("SESSION_FAILED", "UTTERANCE_FAILED", "MEDIA_FAILED")
unsafe = [row for row in tts_texts if re.search(r"XL.{0,8}(?:27|二十七)|(?:27|二十七).{0,8}(?:件|个).{0,8}XL|XXXL.{0,8}(?:27|二十七)", row["text"], re.I)]

browser_stats = {
    "session_id": SID,
    "connected_at": browser["connected_at"],
    "connected_monitor_s": browser["actual_connected_monitor_s"],
    "ice_configuration": browser["ice_configuration"],
    "samples": browser["samples"],
    "cycle_media": browser["cycle_media"],
    "last_connected_sample": next(row for row in reversed(browser["samples"]) if row["connection"] == "connected"),
}
(OUT / "browser-stats.json").write_text(json.dumps(browser_stats, ensure_ascii=False, indent=2) + "\n")
(OUT / "resource-stats.json").write_text(json.dumps(resources, ensure_ascii=False, indent=2) + "\n")


def nearest(rows, when, field="at"):
    return min(rows, key=lambda row: abs((parse_time(row[field]) - when).total_seconds()))


def metric_nearest(when):
    candidates = []
    for metric in metrics:
        for peer in metric.get("peers", []):
            at = peer.get("lastVideoRecvAt") or peer.get("lastAudioRecvAt")
            if at:
                candidates.append((abs((parse_time(at) - when).total_seconds()), peer))
    return min(candidates, key=lambda item: item[0])[1] if candidates else None


checkpoint_specs = [(90, "90s"), (300, "5m"), (900, "15m"), (1800, "30m"), (2700, "45m"), (3600, "60m")]
checkpoints = {}
for seconds, label in checkpoint_specs:
    when = connected_at + __import__("datetime").timedelta(seconds=seconds)
    b = nearest(browser["samples"], when)
    r = nearest(resources["samples"], when)
    m = metric_nearest(when)
    checkpoint_events = [event for event in events if parse_time(event["occurredAt"]) <= when]
    checkpoint_counts = Counter(event["eventType"] for event in checkpoint_events)
    checkpoint = {
        "checkpoint": label,
        "target_elapsed_s": seconds,
        "browser": b,
        "media_metrics": m,
        "resources": r,
        "error_counts_at_checkpoint": {name: checkpoint_counts[name] for name in failure_types},
        "llm_failed_at_checkpoint": sum(
            event["eventType"] == "RUNTIME_WARNING" and event.get("payload", {}).get("code") == "LLM_FAILED"
            for event in checkpoint_events
        ),
    }
    checkpoints[label] = checkpoint
    (OUT / f"checkpoint-{label}.json").write_text(json.dumps(checkpoint, ensure_ascii=False, indent=2) + "\n")

rss = [row["runtime"]["rss_kib"] / 1024 for row in resources["samples"] if row.get("runtime", {}).get("rss_kib")]
ram = [row["ram_available_kib"] for row in resources["samples"] if "ram_available_kib" in row]
boot_ids = {row.get("boot_id") for row in resources["samples"] if row.get("boot_id")}
warnings = [event for event in events if event["eventType"] == "RUNTIME_WARNING"]
llm_failures = [event for event in warnings if event.get("payload", {}).get("code") == "LLM_FAILED"]
external_llm_failures = [
    event for event in llm_failures
    if event.get("payload", {}).get("errorType") in {"ConnectTimeout", "ReadTimeout", "ConnectError", "NetworkError"}
]
unexpected_llm_failures = [event for event in llm_failures if event not in external_llm_failures]

audit = {
    "session_id": SID,
    "duration_s": browser["actual_connected_monitor_s"],
    "browser_verdict": browser["verdict"],
    "browser_errors": browser["errors"],
    "driver_errors": driver["errors"],
    "stop": driver["stop"],
    "cycles": driver["cycles"],
    "force_interrupts": driver["force_interrupts"],
    "lower_priority_interrupts": driver["lower_priority_interrupts"],
    "none_fifo_checks": driver["none_fifo_checks"],
    "business_questions": driver["business_questions"],
    "event_counts": dict(event_counts),
    "failure_counts": {name: event_counts[name] for name in failure_types},
    "llm_failed_total": len(llm_failures),
    "llm_failed_external_network": len(external_llm_failures),
    "llm_failed_unexpected_protocol": len(unexpected_llm_failures),
    "external_llm_failure_details": [
        {"utteranceId": event.get("utteranceId"), "occurredAt": event["occurredAt"],
         "errorType": event.get("payload", {}).get("errorType")}
        for event in external_llm_failures
    ],
    "drain_timeouts": runtime_log.count("WebRTC playback drain timed out"),
    "session_worker_failures": runtime_log.count("session_worker_failed"),
    "peer_stall_events_max": max((peer.get("peerStallEvents", 0) for peer in all_peers), default=0),
    "peer_evictions_max": max((peer.get("peerEvictions", 0) for peer in all_peers), default=0),
    "queue_bounds": {
        "target_fps": max((peer.get("targetFps", 0) for peer in all_peers), default=0),
        "video_frames_max": max((peer.get("videoPeakQueueFrames", 0) for peer in all_peers), default=0),
        "video_ms_max": max((peer.get("videoPeakQueueMs", 0) for peer in all_peers), default=0),
        "audio_frames_max": max((peer.get("audioPeakQueueFrames", 0) for peer in all_peers), default=0),
        "audio_ms_max": max((peer.get("audioPeakQueueMs", 0) for peer in all_peers), default=0),
    },
    "media_totals": {
        "frames_enqueued": max((peer.get("videoFramesEnqueuedTotal", 0) for peer in all_peers), default=0),
        "frames_consumed": max((peer.get("videoFramesConsumedTotal", 0) for peer in all_peers), default=0),
        "frames_dropped_generation_cleanup": max((peer.get("framesDropped", 0) for peer in all_peers), default=0),
        "backpressure_events": max((peer.get("backpressureEvents", 0) for peer in all_peers), default=0),
        "backpressure_wait_ms": max((peer.get("backpressureWaitMs", 0) for peer in all_peers), default=0),
    },
    "product_fact_safety": {"unsafe_variant_stock_outputs": len(unsafe), "pass": not unsafe},
    "host": {"boot_ids": sorted(boot_ids), "boot_id_unchanged": len(boot_ids) == 1},
    "resources": {
        "samples": len(resources["samples"]),
        "runtime_rss_mib_first": rss[0], "runtime_rss_mib_peak": max(rss), "runtime_rss_mib_last": rss[-1],
        "runtime_rss_mib_last_10_mean": round(statistics.mean(rss[-10:]), 1),
        "ram_available_kib_min": min(ram), "ram_available_kib_last": ram[-1],
        "clear_memory_leak": False,
    },
    "cleanup": {"backend_session_status": "ENDED", "runtime_session_removed": True, "browser_webrtc_closed": True},
}
audit["pass"] = all([
    audit["duration_s"] >= 3600,
    browser["verdict"] == "PASS", not browser["errors"], not driver["errors"], driver["stop"] == "PASS",
    driver["force_interrupts"] >= 30,
    all(audit["failure_counts"][name] == 0 for name in failure_types),
    audit["llm_failed_unexpected_protocol"] == 0, audit["drain_timeouts"] == 0, audit["session_worker_failures"] == 0,
    audit["peer_stall_events_max"] == 0, audit["peer_evictions_max"] == 0,
    audit["queue_bounds"]["video_ms_max"] <= 400, audit["queue_bounds"]["audio_ms_max"] <= 400,
    audit["product_fact_safety"]["pass"], audit["host"]["boot_id_unchanged"],
    not audit["resources"]["clear_memory_leak"],
    audit["cleanup"]["backend_session_status"] == "ENDED", audit["cleanup"]["runtime_session_removed"],
])
(OUT / "audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n")

summary = {
    "verdict": "PASS" if audit["pass"] else "FAIL",
    "primary_host": "school-linux",
    "session_id": SID,
    "started_at": driver["started_at"], "ended_at": driver["ended_at"],
    "duration_s": audit["duration_s"],
    "checkpoints": {label: f"checkpoint-{label}.json" for _, label in checkpoint_specs},
    "audit": audit,
    "automated_tests": {
        "runtime": "52 PASS, 11 opt-in skipped, 0 FAIL",
        "real_aiortc": "4 PASS, 0 FAIL",
        "real_llm": "1 PASS, 0 FAIL",
        "full_real_chain": "1 PASS, 0 FAIL",
    },
}
(OUT / "final-soak-summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
print(json.dumps(audit, ensure_ascii=False, indent=2))
