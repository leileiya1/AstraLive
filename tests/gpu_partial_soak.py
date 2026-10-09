"""Public Go -> remote Runtime GPU-host soak; browser media is checked separately.

Run with an isolated acceptance stack already running. The output is evidence,
not a substitute for a browser/WebRTC soak.
"""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import statistics
import subprocess
import threading
import time
import urllib.request
from uuid import uuid4

from e2e import BASE, request, wait_for


def iso_ms(later, earlier):
    return (datetime.fromisoformat(later.replace("Z", "+00:00")) -
            datetime.fromisoformat(earlier.replace("Z", "+00:00"))).total_seconds() * 1000


def remote_sample():
    host = os.getenv("ASTRALIVE_REMOTE_HOST", "ubuntu-server")
    code = r'''set -e
gpu=$(nvidia-smi --query-gpu=memory.used,memory.free,temperature.gpu,utilization.gpu --format=csv,noheader,nounits 2>/dev/null | head -n1 || true)
runtime_pid=$(pgrep -o -f '[u]vicorn app.main:app.*--port 18000' || true)
backend_pid=$(pgrep -o -f '[/]tmp/astralive-school-backend' || true)
ffmpeg_pid=$(pgrep -o -f '[f]fmpeg .* -f flv rtmp://' || true)
printf 'GPU|%s\n' "$gpu"
printf 'BOOT|'; cat /proc/sys/kernel/random/boot_id
printf 'LOAD|'; cat /proc/loadavg
printf 'MEM|'; awk '/MemAvailable:/{ma=$2}/SwapTotal:/{st=$2}/SwapFree:/{sf=$2}END{print ma","st-sf}' /proc/meminfo
printf 'TEMP|'; for d in /sys/class/hwmon/hwmon*; do if [ "$(cat "$d/name" 2>/dev/null)" = coretemp ]; then awk 'BEGIN{m=0}{if($1>m)m=$1}END{if(m)printf "%.1f\n",m/1000}' "$d"/temp*_input 2>/dev/null; break; fi; done
if [ -n "$runtime_pid" ]; then printf 'RUNTIME|'; ps -p "$runtime_pid" -o pid=,rss=,%cpu=,nlwp=; else echo 'RUNTIME|MISSING'; fi
if [ -n "$backend_pid" ]; then printf 'BACKEND|'; ps -p "$backend_pid" -o pid=,rss=,%cpu=,nlwp=; else echo 'BACKEND|MISSING'; fi
if [ -n "$ffmpeg_pid" ]; then printf 'FFMPEG|'; ps -p "$ffmpeg_pid" -o pid=,rss=,%cpu=,nlwp=; else echo 'FFMPEG|MISSING'; fi
docker stats --no-stream --format 'CONTAINER|{{.Name}}|{{.MemUsage}}' postgres redis-server 2>/dev/null || true
'''
    done = subprocess.run(["ssh", "-o", "BatchMode=yes", host, code],
                          text=True, capture_output=True, timeout=8, check=True)
    lines = done.stdout.strip().splitlines()
    values = {line.split("|", 1)[0]: line.split("|", 1)[1] for line in lines if "|" in line}
    gpu_text = values["GPU"]
    gpu = [int(x.strip()) for x in gpu_text.split(",")] if gpu_text else None
    runtime = values["RUNTIME"].split()
    backend = values["BACKEND"].split()
    ffmpeg = values["FFMPEG"].split()
    mem = [int(x) for x in values["MEM"].split(",")]
    sample = {"at": datetime.now().astimezone().isoformat(),
              "remote_host": host,
              "boot_id": values["BOOT"],
              "loadavg": values["LOAD"],
              "available_memory_kib": mem[0], "swap_used_kib": mem[1],
              "runtime_pid": int(runtime[0]), "runtime_rss_kib": int(runtime[1]),
              "runtime_cpu_pct_cumulative": float(runtime[2]), "runtime_threads": int(runtime[3]),
              "backend_pid": int(backend[0]), "backend_rss_kib": int(backend[1]),
              "backend_cpu_pct_cumulative": float(backend[2]), "backend_threads": int(backend[3]),
              "cpu_temp_c": float(values["TEMP"]) if values["TEMP"] else None,
              "container_memory": [line.split("|", 1)[1] for line in lines if line.startswith("CONTAINER|")]}
    if ffmpeg and ffmpeg[0] != "MISSING":
        sample.update({"ffmpeg_pid": int(ffmpeg[0]), "ffmpeg_rss_kib": int(ffmpeg[1]),
                       "ffmpeg_cpu_pct_cumulative": float(ffmpeg[2]), "ffmpeg_threads": int(ffmpeg[3])})
    if gpu:
        sample.update({"gpu_used_mib": gpu[0], "gpu_free_mib": gpu[1],
                       "gpu_temp_c": gpu[2], "gpu_util_pct": gpu[3]})
    return sample


def remote_ffmpeg_pid():
    host = os.getenv("ASTRALIVE_REMOTE_HOST", "ubuntu-server")
    done = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", host,
         "pgrep -o -f '[f]fmpeg .* -f flv rtmp://' || true"],
        text=True, capture_output=True, timeout=8, check=True,
    )
    value = done.stdout.strip()
    return int(value) if value else None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=int, default=1800)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--session-id")
    parser.add_argument("--room-id")
    parser.add_argument("--already-started", action="store_true")
    parser.add_argument("--browser-ack-file", type=Path)
    parser.add_argument("--force-burst", type=int, default=0)
    parser.add_argument("--idle-seconds", type=int, default=0)
    args = parser.parse_args()
    suffix = uuid4().hex[:8]
    if args.session_id or args.room_id:
        assert args.session_id and args.room_id and args.already_started
        sid, rid = args.session_id, args.room_id
    else:
        status, avatar = request("POST", "/api/v1/avatars", {"name": "gpu-soak-" + suffix, "engine": "MOCK"})
        assert status == 201, avatar
        status, voice = request("POST", "/api/v1/voices", {"name": "gpu-soak-" + suffix, "provider": "MOCK", "providerVoiceId": "mock-female-01"})
        assert status == 201, voice
        status, product = request("POST", "/api/v1/products", {"name": "卫衣", "description": "GPU 验收", "price": 129,
                                                           "currency": "CNY", "stock": 27, "sizes": ["M", "L", "XL"]})
        assert status == 201, product
        status, room = request("POST", "/api/v1/live-rooms", {"name": "gpu-soak-" + suffix,
            "avatarId": avatar["data"]["avatarId"], "voiceId": voice["data"]["voiceId"],
            "activeProductId": product["data"]["productId"], "systemPrompt": "你是一名简洁自然的服装主播。"})
        assert status == 201, room
        rid = room["data"]["roomId"]
        status, session = request("POST", "/api/v1/live-sessions", {"roomId": rid})
        assert status == 201, session
        sid = session["data"]["sessionId"]
    seen = []
    ready = threading.Event()
    stop_reader = threading.Event()
    result = {"session_id": sid, "requested_duration_s": args.duration, "browser_media": "SEPARATE BROWSER MONITOR",
              "cycles": 0, "errors": [], "samples": [], "latencies": [], "business_questions": {},
              "force_interrupts": 0, "lower_priority_interrupts": 0, "none_fifo_checks": 0,
              "force_burst": [], "idle_test": None}

    def read_sse():
        try:
            with urllib.request.urlopen(BASE + f"/api/v1/live-sessions/{sid}/events", timeout=70) as stream:
                ready.set()
                name = None
                for line in stream:
                    if stop_reader.is_set():
                        break
                    line = line.decode().strip()
                    if line.startswith("event: "):
                        name = line[7:]
                    elif line.startswith("data: ") and name:
                        seen.append((name, json.loads(line[6:]), time.monotonic()))
                        name = None
        except Exception as exc:
            seen.append(("reader.error", {"error": repr(exc)}, time.monotonic()))

    thread = threading.Thread(target=read_sse, daemon=True)
    thread.start()
    assert ready.wait(10), "SSE did not connect"

    def event(kind, uid=None, timeout=90):
        match = lambda: next((row for row in seen if row[0] == kind and
                              (uid is None or row[1].get("utteranceId") == uid)), None)
        wait_for(lambda: bool(match()), kind + " " + str(uid), timeout)
        return match()

    def speak(text, priority=40, policy="NONE"):
        sent_at = time.monotonic()
        status, body = request("POST", f"/api/v1/live-sessions/{sid}/utterances",
                               {"text": text, "priority": priority, "interruptPolicy": policy, "source": "OPERATOR"},
                               f"gpu-{uuid4().hex}")
        assert status == 202, body
        return body["data"]["utteranceId"], sent_at

    start = None
    try:
        if not args.already_started:
            status, body = request("POST", f"/api/v1/live-sessions/{sid}/start", key="gpu-start-" + suffix)
            assert status == 202, body
        if not args.already_started:
            event("session.live", timeout=40)
        else:
            status, body = request("GET", f"/api/v1/live-sessions/{sid}")
            assert status == 200 and body["data"]["status"] in ("LIVE", "DEGRADED"), body
        initial_sample = remote_sample()
        result["samples"].append(initial_sample)
        assert initial_sample.get("ffmpeg_pid"), "RTMP FFmpeg process is missing at timer start"
        start = time.monotonic()
        result["started_at"] = datetime.now().astimezone().isoformat()
        result["timer_start_ffmpeg_pid"] = initial_sample["ffmpeg_pid"]
        if args.idle_seconds:
            idle_started = time.monotonic()
            idle_pid = remote_ffmpeg_pid()
            assert idle_pid, "RTMP FFmpeg process is missing before idle test"
            while time.monotonic() - idle_started < args.idle_seconds:
                time.sleep(min(5, args.idle_seconds - (time.monotonic() - idle_started)))
                assert remote_ffmpeg_pid() == idle_pid, "RTMP FFmpeg PID changed during idle test"
            result["idle_test"] = {
                "requested_seconds": args.idle_seconds,
                "actual_seconds": round(time.monotonic() - idle_started, 1),
                "ffmpeg_pid_before": idle_pid,
                "ffmpeg_pid_after": remote_ffmpeg_pid(),
                "pass": remote_ffmpeg_pid() == idle_pid,
            }
        if args.force_burst:
            initial_ffmpeg_pid = remote_ffmpeg_pid()
            assert initial_ffmpeg_pid, "RTMP FFmpeg process is missing before FORCE burst"
            for index in range(args.force_burst):
                old_uid, _ = speak("这是一段用于验证强制打断的连续主播内容。" * 8)
                event("utterance.playing", old_uid)
                new_uid, _ = speak(f"第 {index + 1} 次打断后立即接管。", 100, "FORCE")
                event("utterance.interrupted", old_uid)
                event("utterance.completed", new_uid)
                current_pid = remote_ffmpeg_pid()
                result["force_burst"].append({"index": index + 1, "ffmpeg_pid": current_pid})
                assert current_pid == initial_ffmpeg_pid, "RTMP FFmpeg PID changed during FORCE burst"
                result["force_interrupts"] += 1
        while time.monotonic() - start < args.duration:
            long_uid, _ = speak("欢迎来到直播间，今天介绍一件新衣服。" * 8)
            event("utterance.playing", long_uid)
            force_uid, _ = speak("现在为大家继续介绍。", 100, "FORCE")
            event("utterance.interrupted", long_uid)
            event("utterance.completed", force_uid)
            result["force_interrupts"] += 1

            lower_uid, _ = speak("空闲时为大家介绍面料和穿着感受。" * 6, 10, "NONE")
            event("utterance.playing", lower_uid)
            higher_uid, _ = speak("这款商品有哪些特点？", 80, "INTERRUPT_LOWER_PRIORITY")
            event("utterance.interrupted", lower_uid)
            event("utterance.completed", higher_uid)
            result["lower_priority_interrupts"] += 1

            first_uid, _ = speak("这件衣服穿着很舒适，欢迎大家看看详情。" * 3)
            event("utterance.playing", first_uid)
            second_uid, _ = speak("稍后再介绍搭配。", 20, "NONE")
            first_done = event("utterance.completed", first_uid)
            second_done = event("utterance.completed", second_uid)
            assert first_done[2] <= second_done[2], "NONE queue order violated"
            result["none_fifo_checks"] += 1

            sent_at = time.monotonic()
            status, body = request("POST", "/api/v1/dev/platform-events", {"eventType": "COMMENT", "roomId": rid,
                "user": {"externalId": "gpu-soak", "nickname": "测试用户"}, "payload": {"text": "XL 还有库存吗？"}})
            assert status == 202, body
            uid = body["data"]["utteranceId"]
            synth = event("utterance.synthesizing", uid)
            render = event("utterance.rendering", uid)
            playing = event("utterance.playing", uid)
            event("utterance.completed", uid)
            result["latencies"].append({"event_to_speech_ms": round((playing[2] - sent_at) * 1000, 1),
                "tts_first_chunk_ms": round(iso_ms(render[1]["occurredAt"], synth[1]["occurredAt"]), 1),
                "avatar_first_frame_ms": round(iso_ms(playing[1]["occurredAt"], render[1]["occurredAt"]), 1)})
            questions = ["库存多少？", ["有 XL 吗？", "有 XXXL 吗？", "现在多少钱？", "介绍一下这件商品。"][result["cycles"] % 4]]
            for question in questions:
                status, body = request("POST", "/api/v1/dev/platform-events", {"eventType": "COMMENT", "roomId": rid,
                    "user": {"externalId": "gpu-soak", "nickname": "测试用户"}, "payload": {"text": question}})
                assert status == 202, body
                event("utterance.completed", body["data"]["utteranceId"])
                result["business_questions"][question] = result["business_questions"].get(question, 0) + 1
            result["business_questions"]["XL 还有库存吗？"] = result["business_questions"].get("XL 还有库存吗？", 0) + 1
            result["cycles"] += 1
            result["samples"].append(remote_sample())
            if any(name in ("utterance.failed", "session.failed", "reader.error") for name, _, _ in seen):
                raise AssertionError("failure event observed")
            print(json.dumps({"cycle": result["cycles"], "elapsed_s": round(time.monotonic() - start),
                              "last_latency": result["latencies"][-1], "sample": result["samples"][-1]}), flush=True)
            if args.browser_ack_file:
                def browser_acknowledged():
                    try:
                        return int(args.browser_ack_file.read_text().strip()) >= result["cycles"]
                    except (FileNotFoundError, ValueError):
                        return False
                wait_for(browser_acknowledged, "browser media cycle " + str(result["cycles"]), 25)
            time.sleep(1)
    except Exception as exc:
        result["errors"].append(repr(exc))
        raise
    finally:
        result["actual_duration_s"] = round(time.monotonic() - start, 1) if start is not None else 0.0
        try:
            status, body = request("POST", f"/api/v1/live-sessions/{sid}/stop", key="gpu-stop-" + suffix)
            assert status == 202, body
            event("session.ended", timeout=40)
            result["stop"] = "PASS"
        except Exception as exc:
            result["stop"] = "FAIL"
            result["errors"].append("stop: " + repr(exc))
        try:
            result["samples"].append(remote_sample())
        except Exception as exc:
            result["errors"].append("final sample: " + repr(exc))
        stop_reader.set()
        result["ended_at"] = datetime.now().astimezone().isoformat()
        result["event_count"] = len(seen)
        for key in ("event_to_speech_ms", "tts_first_chunk_ms", "avatar_first_frame_ms"):
            values = [row[key] for row in result["latencies"]]
            result[key] = {"median": round(statistics.median(values), 1), "max": max(values)} if values else None
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
