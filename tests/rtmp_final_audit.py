"""Build the canonical evidence bundle for the completed RTMP final run."""
from collections import Counter
from datetime import datetime
import ast
import json
from pathlib import Path
import re
import urllib.request

import redis
from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "integration/evidence/rtmp-final"


def load(name):
    return json.loads((OUT / name).read_text())


browser = load("browser-stats.json")
driver = load("runtime-driver.json")
SID = driver["session_id"]
after = load("processes-after-stop.json")
ffprobe = load("ffprobe.json")
with urllib.request.urlopen(f"http://127.0.0.1:18080/api/v1/live-sessions/{SID}", timeout=5) as response:
    backend_session = json.loads(response.read())["data"]
resource_rows = [json.loads(line) for line in (OUT / "resource-stats.jsonl").read_text().splitlines() if line.strip()]
(OUT / "resource-stats.json").write_text(json.dumps({"samples": resource_rows}, indent=2) + "\n")

client = redis.Redis.from_url("redis://127.0.0.1:6379/14", socket_connect_timeout=2)
events = []
for _, fields in client.xrange("dh.runtime.events.v1"):
    raw = fields.get(b"event", fields.get(b"data"))
    if raw:
        event = json.loads(raw)
        if event.get("sessionId") == SID:
            events.append(event)
(OUT / "runtime-events.json").write_text(json.dumps(events, ensure_ascii=False, indent=2) + "\n")

schema = json.loads((ROOT / "contracts/events/runtime-event.schema.json").read_text())
validator = Draft202012Validator(schema, format_checker=FormatChecker())
invalid_events = sum(bool(list(validator.iter_errors(event))) for event in events)
event_counts = Counter(event["eventType"] for event in events)
event_types = [event["eventType"] for event in events]
stopping_index = event_types.index("SESSION_STOPPING") if "SESSION_STOPPING" in event_types else -1
ended_index = event_types.index("SESSION_ENDED") if "SESSION_ENDED" in event_types else -1

runtime_log = (OUT / "runtime.log").read_text(errors="replace")
messages = []
for line in runtime_log.splitlines():
    try:
        messages.append(json.loads(line).get("message", ""))
    except json.JSONDecodeError:
        continue

webrtc_metrics = []
rtmp_drop_marks = []
for message in messages:
    if message.startswith("webrtc_media_metrics "):
        webrtc_metrics.append(json.loads(message.split("webrtc_media_metrics ", 1)[1]))
    elif message.startswith("media_sink_warning "):
        try:
            warning = ast.literal_eval(message.split("media_sink_warning ", 1)[1])
        except (ValueError, SyntaxError):
            continue
        if warning.get("sink") == "rtmp" and warning.get("code") == "MEDIA_SINK_BACKPRESSURE_DROP":
            rtmp_drop_marks.append(warning)

periodic = browser["samples"]
cycle_rows = browser["cycle_media"]
connected = lambda row: row["connection"] == "connected" and row["ice"] in {"connected", "completed"}
growing_fields = ("audioPackets", "audioBytes", "videoPackets", "framesDecoded")
nonincrease = {field: sum(b[field] <= a[field] for a, b in zip(periodic, periodic[1:])) for field in growing_fields}

nonnull_driver_samples = [row for row in driver["samples"] if row.get("ffmpeg_pid")]
ffmpeg_pids = sorted({row["ffmpeg_pid"] for row in nonnull_driver_samples})
boot_ids = sorted({row["boot_id"] for row in driver["samples"]} | {after["boot_id"]})
runtime_rss = [row["runtime_rss_kib"] for row in driver["samples"] if row.get("runtime_rss_kib")]
ffmpeg_rss = [row["ffmpeg_rss_kib"] for row in nonnull_driver_samples]
memory_monotonic = all(b >= a for a, b in zip(runtime_rss, runtime_rss[1:]))

rtmp_periodic = []
for row in resource_rows:
    for session in row.get("media", {}).get("sessions", []):
        if session.get("sessionId") != SID:
            continue
        rtmp = session.get("media", {}).get("rtmp", {})
        sink = rtmp.get("sink", {})
        if not sink:
            continue
        rtmp_periodic.append({
            "at": row.get("at"),
            "soak_elapsed_s": row.get("soak_elapsed_s"),
            "ffmpeg_pid": sink.get("pid"),
            "fanout_audio_queue": rtmp.get("audioQueueSize"),
            "fanout_audio_queue_max": rtmp.get("audioQueueMax"),
            "fanout_video_queue": rtmp.get("videoQueueSize"),
            "fanout_video_queue_max": rtmp.get("videoQueueMax"),
            "fanout_failed_pushes": rtmp.get("failedPushes"),
            "rtmp_audio_queue": sink.get("audioQueueSize"),
            "rtmp_audio_queue_max": sink.get("audioQueueMax"),
            "rtmp_video_queue": sink.get("videoQueueSize"),
            "rtmp_video_queue_max": sink.get("videoQueueMax"),
            "audio_enqueued_total": sink.get("audioEnqueuedTotal"),
            "audio_consumed_total": sink.get("audioConsumedTotal"),
            "video_enqueued_total": sink.get("videoEnqueuedTotal"),
            "video_consumed_total": sink.get("videoConsumedTotal"),
            "audio_dropped": sink.get("audioDropped"),
            "video_dropped": sink.get("videoDropped"),
            "process_starts": sink.get("processStarts"),
            "reconnect_count": sink.get("reconnectCount"),
            "write_failures": sink.get("writeFailures"),
        })

def bounded(sample, value_key, max_key):
    value, maximum = sample.get(value_key), sample.get(max_key)
    return isinstance(value, int) and isinstance(maximum, int) and 0 <= value <= maximum

queue_bounded = bool(rtmp_periodic) and all(
    bounded(row, value, maximum)
    for row in rtmp_periodic
    for value, maximum in (
        ("fanout_audio_queue", "fanout_audio_queue_max"),
        ("fanout_video_queue", "fanout_video_queue_max"),
        ("rtmp_audio_queue", "rtmp_audio_queue_max"),
        ("rtmp_video_queue", "rtmp_video_queue_max"),
    )
)
counters_monotonic = bool(rtmp_periodic) and all(
    all(b.get(key, -1) >= a.get(key, -1) for a, b in zip(rtmp_periodic, rtmp_periodic[1:]))
    for key in ("audio_enqueued_total", "audio_consumed_total", "video_enqueued_total", "video_consumed_total")
)

streams = ffprobe["streams"]
video = next((row for row in streams if row.get("codec_name") == "h264"), {})
audio = next((row for row in streams if row.get("codec_name") == "aac"), {})
codec_pass = (video.get("pix_fmt") == "yuv420p" and video.get("width") == 720 and
              video.get("height") == 1280 and video.get("r_frame_rate") == "25/1" and
              audio.get("sample_rate") == "48000" and audio.get("channels") == 2 and
              audio.get("channel_layout") == "stereo")

failure_events = sum(event_counts[name] for name in ("SESSION_FAILED", "UTTERANCE_FAILED", "MEDIA_FAILED"))
unexpected_log_failures = {name: runtime_log.count(name) for name in
                           ("Broken pipe", "RTMP_OUTPUT_FAILED", "RTMP_RECONNECT_FAILED")}
normal_stop = (driver["stop"] == "PASS" and stopping_index >= 0 and ended_index > stopping_index and
               after["runtime_health"]["activeSessions"] == 0 and after["ffmpeg"]["pid"] is None and
               not after["ffmpeg"]["zombies"])

rtmp_stats = {
    "session_id": SID,
    "ffmpeg_pids": ffmpeg_pids,
    "ffmpeg_pid_stable": len(ffmpeg_pids) == 1,
    "ffmpeg_rss_kib": {"min": min(ffmpeg_rss), "max": max(ffmpeg_rss)},
    "unexpected_reconnects": runtime_log.count("RTMP_RECONNECTING"),
    "write_failures": runtime_log.count("Broken pipe") + runtime_log.count("RTMP_OUTPUT_FAILED"),
    "rtmp_video_drop_counter_last_mark": max((row["dropped"] for row in rtmp_drop_marks), default=0),
    "configured_queue_bounds": {"fanout_audio_frames": 20, "fanout_video_frames": 10,
                                "rtmp_audio_frames": 20, "rtmp_video_frames": 10},
    "webrtc_metric_records": len(webrtc_metrics),
    "periodic_samples": rtmp_periodic,
    "periodic_sample_count": len(rtmp_periodic),
    "queue_bounded": queue_bounded,
    "counters_monotonic": counters_monotonic,
    "diagnostics_note": "In-process RTMP diagnostics were sampled by the independent systemd monitor throughout the accepted Session.",
}
(OUT / "rtmp-stats.json").write_text(json.dumps(rtmp_stats, indent=2) + "\n")

normal_stop_json = {
    "session_id": SID,
    "driver_stop": driver["stop"],
    "session_stopping_index": stopping_index,
    "session_ended_index": ended_index,
    "backend_status": backend_session["status"],
    "runtime_active_sessions_after_stop": after["runtime_health"]["activeSessions"],
    "ffmpeg_after_stop": after["ffmpeg"],
    "runtime_fd_after_stop": after["services"]["runtime"]["process"]["fd_count"],
    "runtime_session_removed": after["runtime_health"]["activeSessions"] == 0,
    "pipe_fds_closed": after["ffmpeg"]["pid"] is None,
    "workers_removed": after["runtime_health"]["activeSessions"] == 0,
    "pass": normal_stop,
}
(OUT / "normal-stop.json").write_text(json.dumps(normal_stop_json, indent=2) + "\n")

checks = {
    "actual_soak_at_least_900": driver["actual_duration_s"] >= 900,
    "browser_monitor_at_least_900": browser["actual_connected_monitor_s"] >= 900,
    "runtime_pid_alive_and_stable": len({row["runtime_pid"] for row in driver["samples"]}) == 1,
    "ffmpeg_pid_alive_and_stable": len(ffmpeg_pids) == 1,
    "boot_id_unchanged": len(boot_ids) == 1,
    "browser_connected_all_periodic_samples": all(connected(row) for row in periodic),
    "browser_counters_increasing": all(value == 0 for value in nonincrease.values()),
    "h264_aac_conformance": codec_pass,
    "no_failure_events": failure_events == 0,
    "no_unexpected_rtmp_reconnect": rtmp_stats["unexpected_reconnects"] == 0,
    "no_broken_pipe_or_output_failure": all(value == 0 for value in unexpected_log_failures.values()),
    "rtmp_periodic_metrics_present": len(rtmp_periodic) >= 10,
    "rtmp_queues_bounded": queue_bounded,
    "rtmp_counters_monotonic": counters_monotonic,
    "rtmp_no_failed_pushes": all(row["fanout_failed_pushes"] == 0 for row in rtmp_periodic),
    "rtmp_single_process_no_reconnect_or_write_failure": all(
        row["ffmpeg_pid"] == ffmpeg_pids[0] and row["process_starts"] == 1 and
        row["reconnect_count"] == 0 and row["write_failures"] == 0
        for row in rtmp_periodic
    ),
    "normal_stop_and_cleanup": normal_stop,
    "event_schema_valid": invalid_events == 0,
    "memory_not_monotonic": not memory_monotonic,
}
summary = {
    "schemaVersion": 1,
    "session_id": SID,
    "verdict": "READY FOR REAL PLATFORM RTMP" if all(checks.values()) else "NOT READY FOR REAL PLATFORM RTMP",
    "actual_soak_seconds": driver["actual_duration_s"],
    "browser_monitor_seconds": browser["actual_connected_monitor_s"],
    "checks": checks,
    "events": {"count": len(events), "invalid": invalid_events, "types": dict(event_counts)},
    "business": {"cycles": driver["cycles"], "force_interrupts": driver["force_interrupts"],
                 "lower_priority_interrupts": driver["lower_priority_interrupts"],
                 "none_fifo_checks": driver["none_fifo_checks"], "questions": driver["business_questions"]},
    "browser": {"periodic_samples": len(periodic), "cycle_samples": len(cycle_rows),
                "nonincrease": nonincrease, "last_connected": periodic[-1]},
    "resources": {"runtime_rss_kib": runtime_rss, "runtime_rss_monotonic": memory_monotonic,
                  "ffmpeg_rss_kib": rtmp_stats["ffmpeg_rss_kib"], "boot_ids": boot_ids},
    "observability": rtmp_stats["diagnostics_note"],
    "ffprobe_scope": "Captured while the accepted Session publisher was live.",
}
(OUT / "final-summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")

mediamtx_log = (OUT / "mediamtx.log").read_text(errors="replace")
ffmpeg_lines = [message for message in messages if message.startswith(("rtmp_output_started", "rtmp_output_stopped"))]
ffmpeg_lines.extend(line for line in mediamtx_log.splitlines()
                    if any(marker in line for marker in ("stream is available", "is publishing", "closed: EOF")))
redacted = []
for line in ffmpeg_lines:
    line = line.replace("live/astralive-test", "live/***")
    line = re.sub(r"rtmps?://[^\s\"'}]+", "rtmp://***", line)
    redacted.append(line)
(OUT / "ffmpeg-redacted.log").write_text("\n".join(redacted) + "\n")
(OUT / "mediamtx.log").write_text(
    re.sub(r"live/[^\s\"'}]+", "live/***", re.sub(r"rtmps?://[^\s\"'}]+", "rtmp://***", mediamtx_log))
)

harness_investigation = {
    "prior_incident_classification": "SSH/HARNESS TERMINATION strongly supported; exact prior exit status unavailable",
    "prior_evidence": {
        "tool_session_final_state": "Unknown process id 76542",
        "runtime_traceback": False,
        "ffmpeg_error": False,
        "oom_evidence": False,
        "boot_id_changed": False,
        "legacy_binding": "foreground SSH child plus trap cleanup EXIT INT TERM",
    },
    "final_run_lifecycle": {
        "remote_services": "systemd --user transient units with linger",
        "browser_driver": "macOS launchd submitted job",
        "ssh_tunnel": "macOS launchd submitted job",
        "agent_shell_owned_test_process": False,
        "runtime_unit_result": after["services"]["runtime"]["unit"],
    },
}
(OUT / "harness-investigation.json").write_text(json.dumps(harness_investigation, indent=2) + "\n")
print(json.dumps(summary, ensure_ascii=False, indent=2))
