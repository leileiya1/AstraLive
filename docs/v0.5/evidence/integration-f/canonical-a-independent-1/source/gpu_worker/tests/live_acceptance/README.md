# RTX3080 isolated live-chain acceptance

This harness uses an existing pinned installation and private SSH control master. It never buys/starts a cloud instance, installs dependencies, downloads weights, changes the default provider, or publishes to a real platform.

`prepare.py RUN SECONDS` builds a new append-only run under `astralive-avatar-lab/streaming/integration`. It preserves the accepted Runtime sinks and loads the product `gpu_worker.runtime_adapter`, private protocol 1.1 and paired clock. The lab provider records exact yielded 16k PCM and numeric timing events; the top24 image rows carry lab packet markers. The operator-only binding fixture exercises the frozen reference resolver; it does not replace the Go production configuration/session-binding route or create an auth/database service.

Requirements: existing RTX3080 pinned install; private GPU SSH master; `school-linux` key alias; isolated loopback forward/reverse ports17087/18100/18180; an isolated PostgreSQL schema owned by the existing application role; test MediaMTX loopback19355/API19997; source-private valid LLM key; real Sherpa TTS files; CPU test Python with numpy/PyAV; Chrome and the existing Mac audio policy. Use the venv executable path without resolving its symlink to the base Python.

```sh
python3 gpu_worker/tests/live_acceptance/prepare.py soulx-product-3080-NEW-RUN 3600
python3 gpu_worker/tests/live_acceptance/launch.py soulx-product-3080-NEW-RUN
python3 gpu_worker/tests/live_acceptance/status.py soulx-product-3080-NEW-RUN
gpu_worker/.venv-tests/bin/python gpu_worker/tests/live_acceptance/collect.py soulx-product-3080-NEW-RUN
gpu_worker/.venv-tests/bin/python gpu_worker/tests/live_acceptance/decode_media.py astralive-avatar-lab/streaming/integration/soulx-product-3080-NEW-RUN
python3 gpu_worker/tests/live_acceptance/stop_stack.py soulx-product-3080-NEW-RUN
```

First complete a separate300s preflight. Formal timing starts only after LIVE, actual connected peer/consumption, real GPU frames, entry FORCE, healthy Worker and RTMP publishing. The same session/peer must remain continuous;90/300/900/1800/2700/3600s checkpoints keep native playback estimates separate from same-file source-PCM recording correlation. Keep every source window/outlier. A failed run is not added to another run. Final PASS also requires zero critical business failures, fences/queue bounds, API Stop→ENDED and complete media/process cleanup. A one-hour result is not a month-long SLA or production release.

`prepare_recovery.py` prepares the explicitly named separate recovery run. `owned_crash.py` cross-checks the current pinned supervisor child/parent/command before one SIGKILL, recorded in a one-use marker. Only use it after the healthy run has normally stopped. The recovery test keeps the same business session/peer, verifies actual displayed Lightweight frames, a new Worker epoch and future speech recovery; no old utterance is replayed. Re-running needs a new reviewed run/marker, not deleting evidence.

For an independent inference-network fault, prepare a new run, then use
`prepare_recovery.py RUN network`. The operator creates the dedicated SSH master
`/tmp/astralive-3080-fault-tunnel.sock` with school reverse port17089 to Mac
loopback17087, and launches with `SOULX_LAB_WORKER_PORT=17089`. The fixed loopback
lab endpoint closes only that master once, leaving application/API tunnels up;
after the fallback utterance completes it restores the same approved tunnel.
This run requires actual displayed Lightweight frames and future GPU speech
with the **same** Worker epoch, demonstrating network recovery without a model
reload. These fault endpoints are private test fixtures, never product APIs.

All secret files stay in ignored `.private` folders. Collect only bounded numeric status and sanitized logs in release-facing summaries. Close the lab SSH tunnels and stop the named test receiver and Worker after final cleanup; preserve the paid cloud instance and pinned assets.

RTMP recording correlation runs beside the receiver with the unchanged algorithm,
windows and thresholds. Final collection decodes its complete stopped file there
and retains its SHA256, byte count and source path; the original recording stays
on school-linux. Native and canvas recordings remain on Mac. This avoids copying
growing or multi-GB recordings over the Mac VPN during acceptance. The launcher
temporarily uses `caffeinate` only for the driver lifetime; keep the Mac lid open.
