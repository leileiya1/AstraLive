# AstraLive v0.1 One-hour Production Stability Acceptance

**Current verdict: FAIL.** The initial run lost the Ubuntu host before normal Stop after a 3,632-second browser monitor; see [ISSUE-007](issues/007-one-hour-host-connection-loss.md). After the user reported network recovery, an independent retry failed earlier with one `UTTERANCE_FAILED` caused by `WebRTC playback drain timed out`; see [ISSUE-008](issues/008-webrtc-playback-drain-timeout.md). Neither run meets the one-hour acceptance criteria.

## Environment and repository state

| Item | Recorded baseline |
| --- | --- |
| Repository | `/Users/sapiece/innovationProject/AstraLive`; `git status` and `git rev-parse HEAD` returned `not a git repository`; commit/hash unavailable. |
| Ubuntu | 26.04.1 LTS; remote acceptance copy `/home/sapiece/astralive-browser-acceptance-20261007`. |
| GPU | RTX 2060, 6,144 MiB; driver 595.91.07. The prior GPU baseline recorded `nvidia-smi` CUDA 13.2; it was not re-read during the failed host window. |
| Python / Go / Bun / Chrome | Ubuntu Python 3.14.4; Mac Go 1.27.1 darwin/arm64; Bun 1.3.14; Google Chrome 154.0.8037.98. |
| Runtime | Health reported `runtimeVersion=0.1.0`, GPU available, Mock LLM, sherpa-onnx real TTS, `lightweight-2d` Avatar, WebRTC media, Redis events. |
| URLs | Mac Go `http://127.0.0.1:18080`; Ubuntu Runtime `http://127.0.0.1:18000` through SSH and local observing proxy `:18082`; frontend `http://127.0.0.1:18081`. |
| WebRTC ICE | Formal frontend build with `stun:stun.l.google.com:19302`; no TURN. No MuseTalk switch. |

The 5-minute preflight passed: 325 seconds connected, 9 business cycles, browser audio/video growth, FORCE and NONE checks, normal Stop, and Runtime `activeSessions=0`. [Preflight browser evidence](evidence/browser-connected-soak-preflight-5m.json) and [driver evidence](evidence/browser-connected-runtime-preflight-5m.json). The formal run used a new Session and evidence files; the accepted 30-minute files were preserved.

## Start, end, and duration

| Point | UTC |
| --- | --- |
| Browser connected | 2026-10-07 01:13:03.258 |
| Last connected periodic sample | 2026-10-07 02:13:05.092 |
| First failed/disconnected sample | 2026-10-07 02:13:35.104 |
| Browser runner ended | 2026-10-07 02:13:43.339 |

The browser monitor recorded **3,632 seconds**, exceeding the 3,600-second duration threshold. The Runtime driver completed its 87th cycle at elapsed 3,588 seconds, then was terminated with exit code 143 when the monitor detected disconnection. It did not write a normal final summary. [Runtime evidence](evidence/browser-connected-runtime-60m.json) is explicitly reconstructed from the driver log; its `actual_duration_s` is **NOT AVAILABLE** and must not be read as a successful driver completion.

## Business cycles, Speak, COMMENT, Product Tool, and Interrupt

The 87 completed cycles covered ordinary Speak, idle pauses, XL stock and aggregate stock COMMENT, alternating XL availability, XXXL availability, price, and product introduction, plus FORCE, `INTERRUPT_LOWER_PRIORITY`, and NONE FIFO. The Runtime proxy recorded **790 accepted utterance requests**: 529 operator and 261 platform COMMENT. The question counts were 87 each for “XL 还有库存吗？” and “库存多少？”, 22 each for “有 XL 吗？”, “有 XXXL 吗？” and “现在多少钱？”, and 21 for product introduction. [Business count](evidence/browser-connected-business-60m.json).

There were 88 accepted FORCE requests, including the unfinished final cycle. **87 complete cycles** verified the old utterance was interrupted and the new utterance completed; 87 verified lower-priority preemptions and 87 NONE FIFO checks also completed. Redis contained 176 `UTTERANCE_INTERRUPTED` events. The event audit recorded 612 completed utterances and one waiting utterance at the failure boundary. Per-cycle browser audio/video growth was observed for **87/87** completed cycles. This does not prove the final in-flight cycle or post-failure cleanup.

All **524 Product Tool calls returned 200**: 328 product, 174 aggregate stock, and 22 price. Tool facts showed sizes M/L/XL, aggregate stock 27, and price 129. Product.sizes does not prove per-size stock. Prior [TTS-boundary fact-safety evidence](evidence/fact-safety-v1.1.json) confirms the deterministic XL wording, and this run used the same frozen Runtime path; however, this run did **not** capture every spoken sentence at the TTS boundary, so a per-utterance hallucination audit is **NOT AVAILABLE**. No claim of hour-long spoken-text proof is made.

## Browser WebRTC and ICE

The browser used the normal frontend peer at 1% playback volume without muting. Across 121 periodic 30-second samples, 120 reported `connected/connected` and the final sample reported `failed/disconnected`. All **87** cycle media samples reported connected ICE. Audio packets rose to 179,955, audio bytes to 30,553,606 and `totalAudioEnergy` to 0.009476; video packets rose to 95,618 and decoded frames to 89,919. All adjacent periodic and cycle samples had increasing audio packets/bytes/energy and video packets/decoded frames until the last disconnected sample. Cumulative `packetsLost=178` and `framesDropped=134` appeared early and did not continue rising in the later samples. Jitter was sampled in the browser evidence. The final sample still contained cumulative media counters; it **does not** satisfy the ICE continuity requirement.

## Latency

These are 87 completed-cycle event-gap samples. `tts_first_chunk_ms` and `avatar_first_frame_ms` are Runtime event timestamp proxies, not direct provider instrumentation.

| Metric | Min | p50 | p95 | Max |
| --- | ---: | ---: | ---: | ---: |
| `event_to_speech_ms` | 355.2 | 501.3 | 692.4 | 955.3 |
| `tts_first_chunk_ms` | 107.0 | 135.0 | 158.0 | 319.0 |
| `avatar_first_frame_ms` | 30.0 | 44.0 | 164.0 | 181.0 |
| `browser_media_start_ms` | NOT AVAILABLE | NOT AVAILABLE | NOT AVAILABLE | NOT AVAILABLE |

## Backend, Runtime, GPU, and queue trend

The separate system monitor wrote 62 roughly minute-spaced samples; 60 included Ubuntu Runtime/GPU and 59 included Backend. A local `ps` UTF-8 decode error was corrected in the **test-only** monitor early in the run without touching the browser or Session. The last two samples recorded remote SSH failure and stack cleanup. No post-Stop resource measurement is available.

| Resource | Observed range / trend |
| --- | --- |
| Backend RSS | 27.2–28.9 MiB; last 28.9 MiB before stack cleanup. CPU samples ranged 0–1.8%; goroutine count **NOT AVAILABLE**. |
| Runtime RSS | First 640.9 MiB, peak 1,263.6 MiB, last reachable 1,236.4 MiB. First 10 valid samples averaged 966.5 MiB; last 10 averaged 1,209.1 MiB. RSS warmed and fluctuated, including a sustained mid-run drop; an infinite leak is not established. Post-Stop RSS **NOT AVAILABLE**. |
| Runtime CPU / threads | `%CPU` is cumulative process usage, around 59.1% late in the run. Threads ranged 23–69; asyncio task count **NOT AVAILABLE**. |
| GPU | VRAM 4 MiB at every valid sample; 42–44°C; sampled utilization 0% on the CPU Lightweight Avatar path. Post-Stop VRAM **NOT AVAILABLE**. |
| Speech waiting queue | Derived from Redis QUEUED→GENERATING/terminal events: max 1, final 1 while failure interrupted the final cycle. No sustained queue growth before the host loss. |
| Audio / video queue size | **NOT AVAILABLE** from the frozen Runtime's external telemetry. Browser media counters showed steady delivery until the connection failure. |

Minute sampling includes the required T+0/10/20/30/40/50 checkpoints and late samples near T+60; the host loss prevented a valid post-Stop T+60 sample. [System samples](evidence/browser-connected-system-60m.json).

## Errors, warnings, Session Stop, and cleanup

Redis audit found **4,738 schema-valid Runtime events**, `SESSION_FAILED=0`, `UTTERANCE_FAILED=0`, `RUNTIME_ERROR=0`, and `RUNTIME_WARNING=0`. The 176 `UTTERANCE_INTERRUPTED` events were expected from the two intentional preemptions per complete cycle. The sherpa-onnx process log also printed an OOV notice for `XL`; it was not a `RUNTIME_WARNING` event and did not stop earlier playback.

The first confirmed fault was remote SSH sampling timeout near 02:13:09 UTC, followed by the browser failure at 02:13:35 UTC; the Runtime SSH process logged `Connection to 10.65.13.94 closed by remote host`. Subsequent SSH probes failed. The exact host/network cause is unconfirmed. The browser runner attempted a public Stop during its failure cleanup, but the Runtime driver had already been terminated and the event stream contains **no `SESSION_STOPPING` or `SESSION_ENDED`**. Runtime Session removal, current utterance task removal, audio/video queue clearing, normal WebRTC peer close, browser connection close through Session Stop, and post-Stop RSS/VRAM could **not** be verified. The supervising shell cleaned up local test processes and tunnels; this is not a substitute for normal Session cleanup.

## Evidence files

- [Browser media and failure](evidence/browser-connected-soak-60m.json)
- [Reconstructed Runtime driver evidence](evidence/browser-connected-runtime-60m.json), [raw driver cycles](evidence/browser-connected-driver-60m.jsonl)
- [Redis Runtime events](evidence/browser-connected-events-60m.json), [audit](evidence/browser-connected-audit-60m.json)
- [System resource samples](evidence/browser-connected-system-60m.json)
- [Tool HTTP proxy](evidence/browser-connected-runtime-tool-60m.jsonl), [business counts](evidence/browser-connected-business-60m.json)
- [Runtime log](evidence/browser-connected-runtime-60m.log), [Backend log](evidence/browser-connected-backend-60m.log)

## Verdict

**FAIL.** Duration and 87 completed business cycles were observed, but Browser WebRTC disconnected before normal Stop and cleanup could not be verified. The project remains **not accepted** for the v0.1 Core Technical MVP one-hour gate. RTMP, RAG v0.2, MuseTalk, production TURN, multi-room, multi-GPU, payments, multi-tenant, and commercial deployment were outside this gate and did not cause this verdict.

## Independent retry after Ubuntu recovery

The user reported temporary network loss and Ubuntu recovery. Read-only host records confirmed a boot boundary coincident with the first failed run; the initiating cause of that restart remains undetermined. A new **330-second preflight passed** with 7 business cycles, connected browser media, normal Stop, and Runtime `activeSessions=0`. [Retry preflight browser](evidence/browser-connected-soak-preflight-retry-1.json) and [Runtime](evidence/browser-connected-runtime-preflight-retry-1.json).

The retry used Session `session_371be80779b552dd2d47f566f5bd7445`, the same frozen providers and frontend STUN configuration, and separate `60m-retry-1` evidence. It completed **51** mixed business cycles over **2,232.0 seconds of driver monotonic time**. The 52nd cycle accepted a NONE-policy queued utterance; that utterance reached `UTTERANCE_PLAYING` at 03:05:47.958 UTC and `UTTERANCE_FAILED` at 03:06:02.986 UTC. The Runtime log states **`RuntimeError: WebRTC playback drain timed out`**. The driver timed out waiting for completion; its normal Stop returned Backend `INTERNAL_ERROR` and did not reach `SESSION_STOPPING → ENDED`. Wall-clock start/end timestamps span longer than the driver monotonic duration; this discrepancy is not counted as soak time. This is a core failure independent of the later host/network loss. [ISSUE-008](issues/008-webrtc-playback-drain-timeout.md).

The retry's Redis audit captured **2,800 schema-valid events**, including 361 completed utterances, 104 intended interrupts, **one `UTTERANCE_FAILED`**, zero `SESSION_FAILED`, and no `SESSION_STOPPING` or `SESSION_ENDED`. There were 52 accepted FORCE requests, 51 completed NONE FIFO checks, 153 COMMENT requests, and **308/308 Product Tool responses were 200**. The browser's saved console output showed connected ICE and increasing audio/video counters through the 2,131-second periodic sample. The browser runner's final cleanup request later hung when the local stack became unavailable; it was terminated, so a complete 30-second browser trace and normal browser-close evidence are **NOT AVAILABLE**. The [browser retry summary](evidence/browser-connected-soak-60m-retry-1.json) explicitly identifies this incomplete trace.

Retry resource samples recorded Runtime RSS from 561.1 MiB to a 1,178.1 MiB peak, then 1,054.3 MiB at the last available sample; GPU VRAM stayed 4 MiB. The waiting speech queue derived from events peaked at 1 and ended at 0. Audio/video queue sizes and post-Stop cleanup are **NOT AVAILABLE**. Event-gap latency distributions for 51 completed cycles appear in the [retry audit](evidence/browser-connected-audit-60m-retry-1.json). The per-run spoken TTS text was not captured, so the prior fact-safety boundary evidence remains the wording proof, not a transcript of this retry.

Retry evidence: [Runtime driver](evidence/browser-connected-runtime-60m-retry-1.json), [raw Redis events](evidence/browser-connected-events-60m-retry-1.json), [audit](evidence/browser-connected-audit-60m-retry-1.json), [system samples](evidence/browser-connected-system-60m-retry-1.json), [Tool/utterance proxy](evidence/browser-connected-runtime-tool-60m-retry-1.jsonl), [Runtime log](evidence/browser-connected-runtime-60m-retry-1.log), and [business counts](evidence/browser-connected-business-60m-retry-1.json).

**Retry verdict: FAIL.** Duration < 3,600 seconds, `UTTERANCE_FAILED=1`, and normal Stop/cleanup failed. The Core Technical MVP remains unaccepted. No production module was changed in this acceptance session.
