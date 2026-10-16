# Crash recovery acceptance

Overall **BLOCKED** for the production Session/media lifecycle. Component PostgreSQL/Redis and real Go/Python subprocess faults are tested in dedicated loopback instances. Raw commands/results are in `evidence/agent-4/`; final run is identified in INTEGRATION-REPORT. Controlled file sinks and injected range/Guardian fixtures are not real TTS/GPU output.

| Required injection | Actual coverage | Production status |
| --- | --- | --- |
| Outbox commit then SIGKILL | TestProcessCommitThenGoSIGKILL: own Go child, real SQL | Session/media BLOCKED |
| Runtime receives, HTTP202 lost | TestProcessRealRuntimeLost202: actual Python HTTP/journal + file effect | COMMENT wire BLOCKED |
| Runtime START, Go killed | TestProcessGoSIGKILLWhilePythonPlayingAndReattach: permits close local output, no replay | Guardian BLOCKED |
| Runtime dies mid-segment | TestProcessPythonSIGKILLPreservesUnknown: SQL UNKNOWN, no completion | Real segment BLOCKED |
| Redis pause/recovery | TestRedisIsolatedDisconnectAndSQLFallback: own shutdown/restart; streams reclaim/dedup | Component test only |
| PostgreSQL pause/recovery | TestPostgresIsolatedServerOutage: marker-owned cluster; connection-drop probe | Component test only |
| Two Coordinators / owner competition | Real PG lease/CAS/SKIP LOCKED tests | Physical publishers BLOCKED |
| Late old Epoch | SQL rejection/history + Python local Gate | Real output BLOCKED |
| Guardian restart | No deployed independent Guardian | BLOCKED |
| Output Permit expires | Real Python timer/Gate + Go/Python file-sink crash probe | Real WebRTC/RTMP BLOCKED |
| Stop concurrent with Recovery | Real SQL Stop tombstone race; old lifecycle-event isolation | Physical mute BLOCKED |
| Product switch vs old work | SQL context checks; authoritative product version changes deny claim/start | Actual live product switch NOT TESTED |
| Provider Binding expires | Real SQL expiry rejects; no credential reuse | New physical Session BLOCKED |
| Duplicate segment completion | Real PG Manager/drain/CONTROL commit test, no duplicate attempt/cursor | Real sink source BLOCKED |
| UNKNOWN then operator Skip | Real PG proof required, immutable decision/gap, completion prefix stays behind | Guardian proof source BLOCKED |
| Next segment after recovery | TestPostgresUnknownGapAndStopPriority, new term + second/third script via SQL | Actual TTS/GPU resume BLOCKED |
| Entire host restart | No isolated full-host deployment exercised | BLOCKED |

Go Backend, Python Runtime, PostgreSQL and Redis probes kill/stop only owned test resources. The runner requires unused 55462/56382 ports and `/tmp/astralive-agent2-agent4-*` ownership markers, preserves data, and stops its services in finally. An initial Agent 4 directory-prefix mismatch was safely rejected by the existing probe; the probe was not weakened. Production/shared services were not touched.

The new SQL-backed completion coordinator only commits a current-epoch, currently owned slot whose LOCAL_MEDIA_DRAINED chain is already applied and whose run is still LIVE/not stopped. It never completes PLAYING/UNKNOWN or accepts a 202 as playback. Older Session lifecycle events are observation-only in Service.ApplyEvent, including direct calls outside Redis, so SESSION_READY cannot launch legacy Start after Stop.

Whole-machine boot reconciliation, actual new Provider Binding capture + physical LiveSession creation, trusted Runtime registration, guardian shutdown/stop callbacks and production sink observations remain unimplemented/unvalidated integration gates. Main installs persistent legacy-mode exclusion and authenticated manual recovery, but does not start the blocked durable deployment.
