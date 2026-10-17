# Agent 5 Output Guardian safety acceptance

**OUTPUT GUARDIAN BLOCKED** — production admission remains closed.

Baseline: Draft PR #8, `integration/v05-durable-live` at `01a752baf79c25d4d268167d016c8c62e754cfdf`. Delivery branch: `feat/v05-output-guardian`; PR target is the integration branch, never main. Verification date: 2026-10-16, macOS arm64, CPU synthetic media only.

## Verified implementation

Guardian is a separate runnable service with scoped CONTROL/producer Unix IPC authentication, read-only PostgreSQL validation and Room advisory exclusion, fsynced local Stop/fence metadata, child PID/incarnation recovery, independent local/child expiry, a trusted MediaMTX controller, and Guardian-owned RTMP/WebRTC resources. No Runtime boolean or Runtime-supplied close callback establishes a fence.

| Resource / authority | Owner in the candidate |
| --- | --- |
| Ephemeral publish key and separate read/API credentials | Guardian memory; private FD to the appropriate child only |
| FFmpeg/libav encoding process | Guardian/Supervisor process group |
| Real RTMP publishing Socket and final chunk handoff | Guardian's private transparent relay |
| WebRTC Peer, tracks, DTLS/SRTP sockets | Guardian process; track guards installed before addTrack |
| Binding version, Run/Session/Epoch, Stop and Permit truth | Existing PostgreSQL tables; Guardian independently validates exact scope |
| Local frame authorization | Immutable full Attempt identity, both clocks, barrier and current short Permit |
| Restart admission | Always closed; reap known owned children, recheck SQL ownership and server absence before a fresh fence |

Every handoff matches tenant/owner/Room/Run/Epoch/Session/output binding/producer/Attempt/utterance/command/generation. Runtime cannot install a fence, self-register a producer or bind a new generation. The publisher child repeats the complete identity check; queued old writes capture their actual process and pipe. No per-frame SQL query is made. Polling, local expiry and child expiry are separate; expired/late authorizations cannot revive a retired output. Attempt replay and nonzero initial video PTS are rejected.

RTMP drain is based on exact ordered compressed-packet coverage plus independent decoding. Server recordings cover a prefix; a real network reader begins its reported video suffix at an IDR. The union must have no gaps, and decoded counts must still cover the complete source range after overlap subtraction. AAC mapping is checked against the encoder's 1024-sample frame size. The evidence hash includes complete Attempt/binding identity, Guardian identity and barrier.

FFmpeg's terminal unpublish/delete commands previously let MediaMTX discard queued tail media. The Guardian relay now holds only those terminal commands until the trusted decode barrier, then closes the real socket. Stop or expiry interrupts this wait and closes immediately. No filler frames, fixed silence, A/V offset, GPU PTS rewrite, timeout growth in the Worker, or Credit changes were used. Observer startup follows actual server readiness instead of exhausting a time-based retry budget during MediaMTX's track analysis.

## Actual commands and results

Raw captured outputs use `.txt` filenames for version control; output bytes were not summarized or filtered. JUnit includes all Guardian cases. Package versions, binary hash, source hashes and scope-boundary verification are included in [evidence](evidence/).

| Verification | Result | Evidence |
| --- | --- | --- |
| `.venv-guardian/bin/python -m pytest output_guardian/tests -q -s --junitxml=...` | **22 passed**, 0 skipped/failed | [raw output](evidence/guardian-tests.txt), [JUnit](evidence/guardian-junit.xml) |
| `PYTHONPATH=runtime:. .venv-guardian/bin/python -m unittest discover -s runtime/tests -p 'test_*.py' -v` | 169 tests, OK, 11 existing opt-in skips | [raw output](evidence/runtime-regression.txt) |
| `.venv-guardian/bin/python -m unittest tests.test_contracts tests.test_durable_live_contracts -v` | **17 passed** | [raw output](evidence/contracts.txt) |
| `go test ./...` from backend | All default package gates passed; DB-gated tests retain their normal skips | [raw output](evidence/go-regression.txt) |
| `ruff check --isolated --select E4,E7,E9,F,I ...` | PASS for new Guardian and adapter files | [raw output](evidence/lint.txt) |
| Baseline scope diff | No changes to backend/contracts/GPU/legacy Session or output implementations | [scope check](evidence/scope-boundary.txt) |

Guardian tests provision a new dedicated PostgreSQL 17 cluster, apply the unchanged 000001–000006 migrations and use a unique `guardian_test_*` database per test. Fixture SQL supplies backend activation/Permit state; this is not a test of Agent 4's formal bridge. MediaMTX v1.21.1 uses dynamic loopback ports, with all unrelated protocols disabled. No paid GPU, real Worker, real Runtime, external platform or existing livestream was stopped or reconfigured.

The zero-origin 4-second synthetic RTMP test proves all **64,000 source PCM samples** and **100 source video frames**, including the full 0–3,960,000µs video PTS list. A second test exercises the real Runtime adapter through authenticated Unix HTTP, encoding, RTMP reception and the same independent range receipt. WebRTC tests use real local aiortc peers and receive both audio and video before actual Peer closure on expiry. These are not Chrome/official-platform/audience observations.

## Requested fault matrix

PASS below is limited to the stated local component evidence, not a production isolation declaration.

| # | Scenario | Observed result / scope |
| --- | --- | --- |
| 1 | Guardian start, Stop, cleanup | PASS: real processes, server connections, tombstone and cleanup |
| 2 | Old Epoch frames | PASS at local identity/SQL guard: mismatched epoch/binding/Session/producer/Attempt/utterance/command rejected; formal multi-Epoch Session reconstruction NOT TESTED |
| 3 | Permit expiry | PASS: independent watchdog kills publisher, removes server connections and closes real WebRTC peers; late renewal rejected |
| 4 | Two publishers in one Room | PASS: real second publisher denied; separate SQL advisory-lock competitor denied |
| 5 | Guardian SIGKILL | PASS: **3 independent real SIGKILL cases**, Supervisor exit 70, owned child dead |
| 6 | Guardian restart | PASS: same persistent state restarts closed, old Runtime cannot renew, stale child registry reconciled |
| 7 | Old FFmpeg remains alive | PASS: real legacy FFmpeg paused with SIGSTOP remains alive while trusted server kick proves its connection gone |
| 8 | Old Runtime reconnects | PASS: real old publishing credential rejected after SQL lease expiry of an actively publishing stream; expired local authorization cannot be renewed |
| 9 | PostgreSQL disconnect | PASS: real PG backend termination retires output; unavailable startup cannot grant authorization; read-only role cannot write |
| 10 | Stop races activation | PASS at Guardian boundary: in-flight install and delayed renewal cannot beat the fsynced Stop barrier; formal backend activation bridge NOT TESTED |
| 11 | WebRTC/RTMP isolation | PASS for real local publishing/Peer shutdown; WebRTC full-range completion remains BLOCKED |
| 12 | Real local RTMP decode and full A/V drain | PASS for finite zero-origin 4-second CPU streams and real Unix adapter; short/continuous Session timelines remain BLOCKED |
| 13 | Exclusive publication lost | PASS: trusted server kicks the active publisher; Guardian retires further admission |
| 14 | No bypass credentials or publishing ports | **BLOCKED / NOT TESTED** at OS/container boundary; templates and source inspection are not proof |

## Remaining production blockers

1. The macOS host lacks Docker/Podman in the inspected paths. Separate-UID Linux/systemd, container namespace/egress, host socket/PID inheritance and negative credential/port reachability tests have **not** run. The committed templates must be deployed and tested from an adversarial Runtime. `RestrictAddressFamilies` does not revoke inherited sockets: do not pass TCP descriptors through socket activation or permissive Unix proxies. Runtime must have neither publishing keys nor a broad proxy to the production target.
2. The current finite publisher is per Attempt. MediaMTX's pinned reader analyzes a two-second timestamp window. A 400ms case intentionally returns UNKNOWN and closes output. Long-lived publication with independent per-Attempt checkpoints is not implemented. The finite path requires first video PTS=0 and starts audio at zero; existing Session-wide PCM/PTS origin alignment is not established. Nonzero origins fail closed without rewriting source PTS.
3. WebRTC's existing consumption counters are not a complete decoded-peer receipt. Required WebRTC finish is deliberately UNKNOWN. Trusted receiver completion, external ICE/TURN and Chrome acceptance are outstanding.
4. Agent 4 still must connect authenticated Session/Provider Binding lifecycle, Backend OUTPUT_GUARDIAN fence submission, trusted checkpoint mapping, current generation and unchanged GPU Credit. The original production main/Session/binding and durable LIVE rejection remain unchanged.
5. A legacy process retaining an external production-platform key outside this controlled ingest namespace cannot be fenced by these local tests. Key ownership/revocation and the actual external connection must be proven before LIVE. No external audience or cross-host/platform recovery is claimed.

Do not remove `OUTPUT_FENCE_UNPROVEN`, enable durable LIVE, merge main, or convert these local tests into a production Guardian PASS. The concrete next integration steps and private IPC schemas are in [Agent 4 HANDOFF](AGENT-4-HANDOFF.md).

## Primary references used during implementation

- [MediaMTX HTTP authentication](https://mediamtx.org/docs/features/authentication) and [Control API](https://mediamtx.org/docs/references/control-api).
- [Pinned gortmplib v1.0.3 reader](https://github.com/bluenviron/gortmplib/blob/v1.0.3/reader.go) for the two-second track-analysis behavior.
- [systemd execution sandbox documentation source](https://github.com/systemd/systemd/blob/main/man/systemd.exec.xml) for address-family restrictions and inherited-socket limitations. Templates remain NOT TESTED here.
