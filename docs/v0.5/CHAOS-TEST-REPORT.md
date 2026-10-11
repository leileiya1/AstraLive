# v0.5 F chaos and integration-gate report

Status: **PARTIAL SEQUENTIAL INTEGRATION — A+B merged; both postmerge software gates PASS**. Initial failures below remain historical pinned evidence. Current [merge ledger](evidence/integration-f/merge-ledger.json) and [CONTINUITY-SEAM-REVIEW](CONTINUITY-SEAM-REVIEW.md) govern remaining gates. Revision `v0.5-frozen-1`; baseline `5a24478`. Review environment macOS arm64, Go1.27.2, Python3.12.13, PostgreSQL17.11. New runs use immutable source/actual merge archives and disposable owned PG; owner worktrees and historical artifacts are preserved.

## B actual merge gate

B final tip dda7936 normally merged as10b74ca (no conflicts), after A postmerge PASS. F reran the actual merge archive: complete Go/race/owned-PG faults/migrations/auth/interaction/contract PASS, durable Python12/12; Runtime202 total (191 pass,11 skips); frontend40/40 and build PASS. [Exact commands and hashed raw logs](evidence/integration-f/merge-b-1/result.json). This retains A regression and tests the integrated B source; real native Chrome/local RTMP evidence is pending a separate run. C06b182f delivery remains premerge; its historical native evidence is synthetic providers and lacks exact launch hashes, so it is not final-source integrated acceptance.

## A actual merge gate

A source tip a28a409 normally merged as89179c7 (no conflicts). F ran `module_gate.py --source 89179c7 --frontend-modules <matching-lock node_modules>` on that actual merge archive: full Go/race/owned-PG faults/migrations/auth/interaction/contract PASS; durable Python12/12; complete Runtime171 total (160 pass,11 skips); frontend40/40 and build PASS. [Commands, environment, durations and SHA256 logs](evidence/integration-f/merge-a-1/result.json). Frontend uses Bun1.3.14 and recorded matching lock, Vitest3.2.7, Vite7.3.7; retained third-party annotation build warnings do not indicate a failed build. A's typed Worker fix now passes F's original B→A diagnostic, including2^53 and2^63−1; the old FAIL below remains scoped to edd4e1e. This is software/real-SQL/CPU-process acceptance, not real inference, integrated C recovery or physical audience hearing.

Historical premerge A edd4e1e independently passes full Go/race/owned-PostgreSQL fault tests and durable Python11/11, plus full Runtime170 total (159 passed,11 skipped). [Result/hashes](evidence/integration-f/a-spool-1/result.json). A separate pinned B→A Worker ID diagnostic **FAILS** for valid wire IDs2^53 and2^63−1; actual B DTO accepts them and A SQLite staging rejects them. [Result](evidence/integration-f/worker-id-1/result.json). The spool suite PASS does not override this contract gap. C's FORCE Speak transaction-return direction is conditional pending authenticated route/SQL tests; no successful operator speech or Runtime interrupt completion is inferred from202 FAILED. Details and owner fix requirements are in the seam review.

[Verification index](evidence/integration-f/verification.json) records exit codes, test counts, environment, frozen/source checks and SHA-256 hashes of retained raw artifacts. Frozen contract bytes match all four pins; C had zero baseline delta at that initial review pin. Python harness syntax, Go fixture formatting, documentation links and diff whitespace checks PASS. These artifact checks do not change the failed core result.

## Executed independent gates

| Gate / exact command | Result | Proven scope / artifact |
| --- | --- | --- |
| A `DURABILITY_PG_BIN=/opt/homebrew/opt/postgresql@17/bin DURABILITY_TEST_PYTHON=/Users/sapiece/innovationProject/AstraLive/runtime/.venv/bin/python bash backend/scripts/test-durability-faults.sh` | exit0 | real owned PG; full `go test -p1 ./... -count=1` and race; auth/SQL/interaction/migrations; Go/Python restart/ACK/duplicate/epoch/recovery cases; PG stop/start; Python durable6/6; frozen v1 validator. [log](evidence/integration-f/a-independent-faults.log) |
| B `PYTHONPATH=runtime:. <python> -m unittest discover -s runtime/tests -v` | exit0;187 total,176 passed,11 opt-ins skipped | standalone B and legacy Runtime regressions; no A/C SQL media binding or new real provider run. [log](evidence/integration-f/b-independent-runtime.log) |
| D `ASTRALIVE_IPC_TEST_PYTHON=<python> go -C backend test -race -count=1 -v ./internal/config ./internal/runtime` | exit0 | actual macOS Go→Python subprocess health/auth, token rotation, TCP/UDS lifecycle/restart; fixture HTTP parity/cancellation/errors/race. [log](evidence/integration-f/d-independent-go-race.log) |
| D `PYTHONPATH=runtime:. <python> -m unittest runtime.tests.test_local_listener -v` | exit0;10 total,9 passed,1 skipped | socket/private-parent/inode/lifecycle; foreign-owner root-only case skipped. [log](evidence/integration-f/d-independent-python.log) |
| A+B `git merge-tree --write-tree --name-only <A> <B>` | exit0 | no text conflict; no branch updated or code merged. [log](evidence/integration-f/a-b-merge-tree.log) |
| D `git apply --check <D>/runtime/tests/local_ipc/shared-wiring.patch` on pinned A snapshot | **exit1** | actual patch context failure `backend/cmd/server/main.go:53`; patch never applied. [log](evidence/integration-f/d-wiring-on-a-check.log) |

`<python>` is `/Users/sapiece/innovationProject/AstraLive/runtime/.venv/bin/python`. Each source snapshot comes from its full pinned SHA; reproducible snapshot instructions are in [harness README](../../integration/v0.5/README.md). Borrowed virtualenv is not modified. A script creates only a marked temporary PostgreSQL cluster and cleans it; no shared PostgreSQL/Redis/Worker/cloud service is stopped. Its process tests prove synthetic software-side effect counts, not audible speech.

## Actual cross-service negative probe

```sh
/Users/sapiece/innovationProject/AstraLive/runtime/.venv/bin/python \
  integration/v0.5/premerge_probe.py \
  --a-sha e5f14a14a04fdd4968af3c8dc3530bb22202e8b6 \
  --b-sha cf43e2d3dd6a9223648eaced2526d13e0ccbf8e1 \
  --output /tmp/unique-f-probe-output
```

F result: **exit1**, expected failing integration gate. [raw result](evidence/integration-f/seam-1/result.json), [driver](evidence/integration-f/seam-1-driver.log), [Go journal](evidence/integration-f/seam-1/go-journal.log), [Python Runtime](evidence/integration-f/seam-1/python-runtime.log). The harness builds/runs actual A Go Store+JournalRouter, actual migrated PostgreSQL, actual A Python uvicorn HTTP Runtime, and invokes B CommitSegment with supplied A client. It has no Narration implementation, fake durable ACK, GPU, Chrome or RTMP. Its fixture bypasses ordinary Go public Session setup to seed an owned test run; it is not a full production Backend/owner/browser acceptance.

| Observation | Result / interpretation |
| --- | --- |
| ordinary BEGIN_RUN with real PG journal, unreachable Redis URL |202; prerequisite PASS, not Narration/real-media acceptance |
| six frozen Narration/Timeline tables after A migrations | all absent; core persistence FAIL |
| diagnostic START_NARRATION / COMMIT_SEGMENT dispatch |422 INVALID_ARGUMENT, Inbox STARTED; no implementation handlers. Payloads probe registration and are NOT a fully authored NarrationPlan test |
| diagnostic future BEGIN_EPOCH |409 LEASE_LOST, no Inbox state; missing reservation machinery means no valid reserved-epoch success case was tested |
| committed proof to A ordinary receipt endpoint |409 COMMAND_CONFLICT; intentionally ordinary-only seam, no supplied B adapter |
| B CommitSegment with A DurabilityClient |AttributeError, journalHasRecord=false; committed sample remains0; no silent memory fallback |

The harness retires owned Go/Python processes and stops its own cluster in finally. No actual model inference or speech output occurs in the seam probe. Failures are kept as failures; a successful ordinary prerequisite does not pass the core.

## Fault coverage and omissions

| Requirement | F current status |
| --- | --- |
| duplicate commands/events; lost ACK; old run/generation; ordinary Stop/recovery race | A standalone real SQL/CPU-process suite PASS; not joint Narration/Timeline proof |
| Backend/Runtime SIGKILL/restart; PG transient outage | A standalone PASS with scoped CPU effects; media playback/semantic resume NOT TESTED |
| Redis absent at startup and Go restart | A standalone PG-only PASS with invalid/unreachable Redis configuration; a running Redis process kill and combined A+B+C continuation NOT TESTED |
|10min continuous narration, five audience questions, natural correct resume | NOT TESTED / C NOT IMPLEMENTED |
| Audience/bridge/next-beat fact ledger, product-switch race, combined Stop/FORCE | NOT TESTED in integrated core |
| real Worker disconnect/reconnect, stale frames at real outputs, FFmpeg crash | NOT TESTED by F this phase |
| real Chrome/WebRTC+RTMP AV/PTS/drift; browser device switching/stalls | NOT TESTED by F this phase |
| Linux/macOS integrated UDS, Windows loopback | macOS standalone D PASS; full host A/C wiring, Linux rerun and Windows actual runtime NOT TESTED |
| frontend test/build and complete joint flag-off live regression | NOT EXECUTED this premerge stop; no frontend/production files changed in F |

B archive contains independently reported real-GPU clock/ledger media evidence; its journal was TEST_DOUBLE. It remains inspectable on B, is not overwritten or promoted to F's integrated Golden result. No new AV latency/drift metrics were measured by F, and no busy P50≤5s/P95≤8s claim is made.

## Follow-up source reviews (original evidence above retained)

- C's uncommitted Scheduler gate was tested in an isolated dependency archive at7924f7f with the exact retained patch and F probes: full interaction package `go test -race -count=1 -v` PASS, exit0. Proves boundary selection, answer deferral+TTL, legacy busy gate, operator and product-switch precedence; no production C dispatcher/SQL/media acceptance. [Patch/hash/result/log](evidence/integration-f/scheduler-review-1/result.json). C's draft Runtime used a different flag; frozen canonical `ASTRALIVE_CONTINUITY_ENABLED` correction remains required in this reviewed draft.
- B fixed installed-proof ordering in85bec11. F independently tested09f06f2 Runtime:190 total,179 passed,11 skipped, exit0. [Result/log hash](evidence/integration-f/b-postinstall-1/result.json), [log](evidence/integration-f/b-postinstall-1/runtime.log). Latest evidence-only dda7936 has identical Runtime/Worker source; no repeat run or GPU PASS inferred.
- [CONTINUITY-SEAM-REVIEW](CONTINUITY-SEAM-REVIEW.md) records scoped ACKs and CCR-BC-001 NOT APPROVED: early staging Credit updates native published-pose history. No frozen amendment, implementation merge or new Golden/media measurement occurred.
- A delivered ee5500b persistence/Timeline journal increment. F reran its pinned full Go/race/owned-PG fault/durable Python8/frozen validator suite: exit0; full A Runtime167 total,156 passed,11 skipped, exit0. [Result and artifact hashes](evidence/integration-f/a-continuity-1/result.json), [fault log](evidence/integration-f/a-continuity-1/faults.log), [Runtime log](evidence/integration-f/a-continuity-1/runtime.log). Six-table/adapter absence is resolved in this newer source; C's actual production callback/media/recovery remain pending final delivery. No standalone SQL suite is promoted to natural continuity or strict SoulX acceptance.
