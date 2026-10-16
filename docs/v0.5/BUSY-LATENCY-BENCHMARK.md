# Busy-speaker latency benchmark

**BLOCKED**: pending answer-prepared CCR and unproven production output isolation. No GPU, real DeepSeek/XiaoYa/SoulX, Chrome or RTMP test was started. No cloud GPU was purchased or started. Existing independent Agent 2/3 timings are not samples for this integration.

Machine-readable zero-sample record: `evidence/agent-4/media-benchmark.json`.

| Scenario/path | Attempted | Completed | Failed | Timeout | Unselected | Expired | P50 | P95 | Gate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Idle Fast Path | 0 | 0 | 0 | 0 | 0 | 0 | N/A | N/A | BLOCKED |
| Idle LLM Path | 0 | 0 | 0 | 0 | 0 | 0 | N/A | N/A | BLOCKED |
| Busy Fast Path | 0 | 0 | 0 | 0 | 0 | 0 | N/A | N/A | BLOCKED |
| Busy LLM Path | 0 | 0 | 0 | 0 | 0 | 0 | N/A | N/A | BLOCKED |
| 1/s, 5/s, 20/s, burst100 | 0 | 0 | 0 | 0 | 0 | 0 | N/A | N/A | BLOCKED |
| duplicates/product change/FORCE | 0 | 0 | 0 | 0 | 0 | 0 | N/A | N/A | BLOCKED |

Target remains idle P50≤3s/P95≤5s and busy P50≤5s/P95≤8s, independently for Fast/LLM paths. Neither target is met or failed by these zero samples: they have not been measured.

After prerequisites: collect at least 30 valid completions per key class while retaining every failed/timed-out/unselected/expired input and full ingress denominator. Correlate trace/attempt/segment/generation with DeepSeek first token, first speakable sentence, XiaoYa first PCM, SoulX first frame, Chrome first correlated AV, dedicated local RTMP decode, segment→reply yield and reply→next-script resume. Use each host's monotonic domain with explicit cross-host correlation; do not subtract unrelated clocks. Preserve raw sample rows and CPU/GPU utilization/memory observations.

Known source gate, not an invented measured bottleneck: existing legacy admission waits on a long utterance; segmentation now exists in planner/SQL arbitration but production exact-text/Guardian/drain wiring is incomplete. Full-answer persistence before TTS may also affect LLM latency after CCR; this must be measured, not waived. GPU first frame is not Browser AV; local RTMP decode is not official viewer verification. No short test establishes 24-hour SLA.
