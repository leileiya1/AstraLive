# Golden browser audio prerequisites

Source: `4e5f65e72b7c5121d58914b01c1c4621e54997a0`. C owns these test-only Runtime Golden files; F owns final integration and independent real acceptance. Production providers, media clocks, RTP, Worker, frozen contracts and request limits are unchanged.

The harness now activates AudioContext through a real button click, retains the actual incoming audio track and source, records context state/clock/output timestamp and track events, and requires both context and RTP decoded-audio clocks to advance before StartNarration. The condition-driven check has a bounded deadline and adds no fixed A/V delay. Final acceptance additionally requires actual decoded energy, video and recorder data. Failure still preserves available Chrome diagnostics.

Immutable-source full gate: PASS, Go/PostgreSQL faults and race/auth/ownership regressions, Runtime 270 tests (12 skips), frontend 40 tests and build. Focused observer policy: 3 PASS. Evidence and hashes: `evidence/agent-c/golden-browser-audio/manifest.json`.

Actual Chrome 155.0.8059.40 with unchanged B aiortc tracks, CPU silence/blank frames: context advanced 0.128 seconds, RTP decoded audio advanced 0.12 seconds; zero speech RMS correctly fails speech acceptance. The original harness also advances in a fresh Chrome 155 environment. These are environment diagnostics, not real TTS/GPU/business acceptance. At this pin recorder byte/chunk counts are browser counters; the diagnostic did not decode callback payloads to a WebM file. The subsequently identified multi-codec data URL delimiter bug needs a separate fix and strict recording round-trip validation.

The failed real tcp-9 run used Chrome 154 and had frozen context time, zero audio energy and zero recording. Its cause is not established by these CPU checks. Do not attribute a later Chrome 155 baseline result to this patch. tcp-9 also retains a repeated price fact and a Stop-interrupted final UNKNOWN attempt; this patch does not establish natural continuity or complete fact coverage. Real GPU/Chrome/RTMP Golden acceptance by C: NOT TESTED.

Reproduce software gate using `integration/v0.5/module_gate.py --source 4e5f65e72b7c5121d58914b01c1c4621e54997a0` with the owned PostgreSQL and media Python arguments recorded in the evidence. Environment diagnostic: `PYTHONPATH=runtime:runtime/tests <media-python> runtime/tests/golden_browser_cpu_diagnostic.py --output <new-directory>`. It must continue rejecting CPU silence as real speech.
