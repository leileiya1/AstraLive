# Output Guardian acceptance — BLOCKED

`OUTPUT_FENCE_UNPROVEN`. Durable LIVE admission is closed in both actual production entrypoints, independent of any supplied registration object. `ASTRALIVE_DURABLE_LIVE_ENABLED` defaults to false; true is rejected before service creation. Unknown flag values reject configuration. There is no environment override that asserts fencing is proven.

## Source inspection

`runtime/app/session_binding.py:bundle_factories` creates the original BoundConsumptionMediaOutput around Runtime-owned outputs. `runtime/app/main.py` creates WebRTC and FFmpeg/RTMP providers. The process can retain direct publisher resources. `media_fanout.py:drain` accepts any successful sink; `bound_media.py` releases GPU consumption credit on WebRTC OR RTMP. These semantics are intentionally preserved. They are not all-required durable completion evidence.

Agent 2's SQL lease/Room binding/short permit and OutputGate are implemented. Agent 4 adds permit-expiry barrier invalidation so an in-flight renewal cannot re-enable the expired local attempt, and bounds completed local task retention. Local expiry/epoch/generation tests are CPU evidence only. No real production Guardian has been deployed, and no actual retained publisher has been physically isolated in this task.

## Compatibility proposal before changing credential/process ownership

Keep v0.4 outputs and frozen v1.1 behavior intact. For a separately enabled durable deployment:

1. Guardian owns RTMP publish credentials, publishing sockets, FFmpeg lifecycle and WebRTC peers. Runtime receives no publish credential and has no direct publishing egress. Provider Binding stays the existing owner-authorized capture; no credential goes to the browser, journal payload or logs.
2. Use a separate OS principal/container network boundary. Same-user files or a Runtime-supplied close callback cannot prevent a retained process from bypassing Guardian. The target ingest server must reject old publish credentials/connections. Revoke/close all former publishers before acknowledging a new outputBindingVersion, including across different logical runs.
3. Guardian handoff checks Room, run, epoch, outputBindingVersion, Session, producer, attempt, utterance and Generation plus a current short permit. It owns a watchdog independent of the producer. Required sink watermarks must cover complete correlated audio/video ranges; enqueue/credit/TTS success is insufficient.
4. Guardian supervisor must reap its FFmpeg children/cgroup and close unknown outputs after crash/restart. Persist only fencing metadata, start closed, reconcile with PostgreSQL and the ingest server, then acknowledge a barrier. A restart with unknown previous publishers must remain closed.
5. Preserve SoulX TCP binary wire, Worker epoch/generation/credit and H.264 PTS. Adapt only after the existing decoded output boundary. No fixed A/V delay or change to Worker semantics is proposed.
6. Validate old/new Runtime coexistence attempts, two physical publishers, Guardian SIGKILL/restart, permit expiry, DB loss, Stop/recovery race, WebRTC and dedicated RTMP decode before accepting this deployment. Official platform audience verification is a separate test.

The present deployment has not met steps 1–6. Compatibility source inspection and default-off/closed admission checks are implemented; process/network isolation and media compatibility validation are **NOT TESTED**. No production credentials, FFmpeg owner, shared Worker or publishing target was changed. Do not promote a database fence receipt or file-sink test to a production Guardian PASS.
