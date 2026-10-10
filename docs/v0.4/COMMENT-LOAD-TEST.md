# Comment Load Test v0.4

CPU/Mock only. `go run ./cmd/comment-load` uses deterministic virtual arrival time and a Fake2s speech consumer; wall time and sampled Go heap are actually measured. `go run ./cmd/comment-load -wall` uses the real Mock Adapter and wall-clock10-second1/5/20/s runs, plus a real burst. Stop accounts for pending candidate drops; these short wall runs are not a steady-state or GPU soak.

## Reproducible offline

| Scenario | Input | Dedup | Merge | Select | Expire | Drop | Delivered | Peak queue | Sampled heap / growth bytes | Actual ms | P50/P95/Max ms (n) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: | --- |
| 1_per_second | 100 | 0 | 41 | 55 | 4 | 0 | 55 | 8 | 680408 / 220128 | 1.837 | 7000.000/17000.000/18000.000 (55) |
| 5_per_second | 100 | 0 | 80 | 17 | 3 | 0 | 17 | 11 | 618952 / 159136 | 2.274 | 7600.000/19400.000/19400.000 (17) |
| 20_per_second | 100 | 0 | 84 | 9 | 0 | 7 | 9 | 6 | 654072 / 194256 | 3.061 | 8850.000/16700.000/16700.000 (9) |
| burst_100 | 100 | 0 | 86 | 7 | 0 | 7 | 7 | 6 | 650912 / 190640 | 3.673 | 6000.000/12000.000/12000.000 (7) |
| mixed_1000 | 1000 | 100 | 390 | 34 | 35 | 441 | 34 | 23 | 1540304 / 1074456 | 40.347 | 11700.000/19600.000/19850.000 (34) |

Failure ratios (failed/selected), drop ratios (drop/input), FORCE count:

- 1_per_second: 0/55 failed; 0/100 dropped (0.0%); FORCE=0.
- 5_per_second: 0/17 failed; 0/100 dropped (0.0%); FORCE=0.
- 20_per_second: 0/9 failed; 7/100 dropped (7.0%); FORCE=0.
- burst_100: 0/7 failed; 7/100 dropped (7.0%); FORCE=0.
- mixed_1000: 0/34 failed; 441/1000 dropped (44.1%); FORCE=0.

## Actual wall-clock Replay

| Scenario | Input | Dedup | Merge | Select | Expire | Drop | Delivered | Peak queue | Sampled heap / growth bytes | Actual ms | P50/P95/Max ms (n) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: | --- |
| wall_1_per_second | 10 | 0 | 1 | 5 | 0 | 4 | 5 | 4 | 544848 / 72032 | 10253.330 | 1099.834/4299.637/4299.637 (5) |
| wall_5_per_second | 50 | 0 | 36 | 5 | 0 | 9 | 5 | 9 | 617608 / 106712 | 10281.707 | 3399.541/7899.757/7899.757 (5) |
| wall_20_per_second | 200 | 0 | 84 | 6 | 0 | 110 | 6 | 6 | 911520 / 399424 | 10401.931 | 3795.629/8098.524/8098.524 (6) |
| wall_burst_100 | 100 | 0 | 87 | 1 | 0 | 12 | 1 | 6 | 726536 / 176520 | 252.099 | 100.288/100.288/100.288 (1) |

Failure ratios (failed/selected), drop ratios (drop/input), FORCE count:

- wall_1_per_second: 0/5 failed; 4/10 dropped (40.0%); FORCE=0.
- wall_5_per_second: 0/5 failed; 9/50 dropped (18.0%); FORCE=0.
- wall_20_per_second: 0/6 failed; 110/200 dropped (55.0%); FORCE=0.
- wall_burst_100: 0/1 failed; 12/100 dropped (12.0%); FORCE=0.

## Resource/accounting and reproducibility

Heap is process Go HeapAlloc, sampled after offline events and every100ms/finally in wall mode. It is not native TTS/GPU memory or continuous maximum RSS. Report includes actual heap growth and measured CPU wall duration. All load consumers accept Fake dispatch; no LLM/TTS/network/GPU claims. Percentiles measure comment receive→selection only. Counts satisfy input=dedup+merge+selected+expired+dropped+filtered after drain/Stop, including explicit Stop drops. Real-wall counts/heap/timing can vary due to timers; offline outcome counts are reproducible. Full-queue drop is separately verified by a100-event,3-slot unit test; stress itself did not saturate default64 candidates.

Fixed fixture: `backend/internal/platform/mock/testdata/reconnect-duplicates.json` exercises source-time disorder, primary/backup duplicate identity, heartbeat/reconnect, merged XL options, separate SKU/overall stock and same-user repeats. Tests run it through Scheduler with a test clock and prove zero dispatch while speech gate is busy. Scenario(rate,count) supports arbitrary synthetic replay generation, including simultaneous users and burst100; API supplies unique mock source IDs per run.

## Fault coverage

| Fault | Evidence kind | Result |
| --- | --- | --- |
| DeepSeek401/429/ReadTimeout | httpx MockTransport, no external network | PASS: never echo comment; existing bound failure tests retained |
| Slow TTS / native cancellation / exception | fake native engine, actual asyncio/thread bridge | PASS: bounded production, prompt callback stop, exception propagates |
| GPU unavailable / startup / cleanup | existing BoundSessionManager fake bundle/Worker tests | PASS for injected guards; real GPU NOT TESTED |
| Runtime rejects speech429 | real loopback HTTP in formal CPU fixture, intentionally injected response | PASS: Go Utterance/receipt FAILED, no retry/TTS |
| Session Stop / Replay mid-cancel | actual formal Go/Python/Redis plus fake providers; adapter cancellation tests | PASS |
| Primary/backup duplicate / scheduler restart | fixed replay + persistent SQL receipts in formal CPU test | PASS: no second Utterance |
| Concurrent delivery / two Rooms / Operator / FORCE | Go race/unit + existing Runtime generation/media tests | PASS for CPU/Fake; distributed replicas/real GPU NOT TESTED |

No paid Provider/GPU was started. No existing Worker was stopped. Disposable SQL/Redis services contain only synthetic test identities/data and are removed after checks; no production cleanup command is used.

## Follow-up re-run (2026-10-10)

Re-run after directed-request classification change. Actual-wall Mock Replay still uses a Fake dispatcher; it is independent from the real-provider20-comment latency trial. Queue/resource/wall-time details are in [wall evidence](evidence/agent-b-followup-load-wall.json) and [offline1000-event evidence](evidence/agent-b-followup-load.json).

| Wall scenario | Input | Dedup | Merge | Selected | Expired | Dropped | Delivered | Peak queue | Sampled heap peak bytes | Elapsed ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| wall_1_per_second | 10 | 0 | 1 | 5 | 0 | 4 | 5 | 4 | 581168 | 10253.24 |
| wall_5_per_second | 50 | 0 | 36 | 5 | 0 | 9 | 5 | 9 | 727944 | 10284.54 |
| wall_20_per_second | 200 | 0 | 84 | 6 | 0 | 110 | 6 | 6 | 836712 | 10421.32 |
| wall_burst_100 | 100 | 0 | 87 | 1 | 0 | 12 | 1 | 6 | 688392 | 251.0 |

These are sampled Go heap values, not full-stack maximum RSS. Pending candidates are counted as dropped on Stop. All cases have automatic FORCE0. The actual-session fault trial additionally cancels a20/s Replay mid-flight with stable input and candidate peak6; it is not a claim that1000 GPU replies were generated.
