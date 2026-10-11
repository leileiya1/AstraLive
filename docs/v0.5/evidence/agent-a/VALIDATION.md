# Agent A validation — 2026-10-11

Final verification completed by 05:35 UTC / 13:35 Asia/Taipei, on this branch's implementation before its delivery commit. Subsequent source changes were gofmt only. Platform: macOS arm64, Go 1.27.2, Homebrew PostgreSQL 17.11, Python 3.12.13. No Redis client/service, paid GPU or real provider was required for the durability acceptance tests.

## Commands and results

1. `DURABILITY_TEST_PYTHON=/Users/sapiece/innovationProject/AstraLive/runtime/.venv/bin/python backend/scripts/test-durability-faults.sh` — exit 0. The script provisioned an owned temporary PG cluster, then ran real-database `go test -p 1 ./... -count=1`, `go test -race -p 1 ./... -count=1`, owned PG stop/start, six Python durable tests and v1.1 contract validation. Both `CONFIG_TEST_DATABASE_URL` and `DURABILITY_TEST_DATABASE_URL` were set inside the script. [Full output](faults.log).
2. Additional verbose durability run with a separately owned localhost PG cluster and the same CPU Runtime Python — exit 0, 18 top-level tests passed, including actual Go/Runtime SIGKILL and transaction before/after-commit child processes. PG outage was excluded here because it requires the script ownership marker; it passed in command 1. [Named tests and process assertions](durability-verbose.log).
3. From `runtime/`: `PYTHONPATH=.. /Users/sapiece/innovationProject/AstraLive/runtime/.venv/bin/python -m unittest discover -s tests -v` — exit 0, **165 tests run, 11 skipped**, 9.152 seconds. Thus 154 executed tests passed. The skips are opt-in real LLM/TTS/avatar/full-chain/WebRTC integration; they are not accepted real-service evidence. [Full output and skip reasons](runtime-unittest.log).
4. `go -C backend vet ./...` and `git diff --check` — exit 0.
5. sqlc regenerated using `go -C backend run github.com/sqlc-dev/sqlc/cmd/sqlc@v1.30.0 generate`; frozen v1 contract source and generated OpenAPI DTOs were unchanged.

The additional verbose invocation used `DURABILITY_TEST_DATABASE_URL=postgres://sapiece@127.0.0.1:55435/astralive_a?sslmode=disable` and this regex, with `-count=1 -v`:

```text
Test(Canonical|Shared|Postgres|Two|Recovery|Event|Different|Migration|Transaction|Control|Force|Stop|Media|Accepted|Bounded|Unknown|Runtime)
```

The Runtime full-suite command initially omitted the parent PYTHONPATH, causing four import errors for existing `gpu_worker` modules. It was corrected to the repository's import layout and rerun to completion; the retained log is that successful final run. No tests were removed to pass the gates. The only old test change fixes fixture cleanup order for an existing foreign key (receipt before utterance).

## Evidence boundaries

- Actual operating-system processes and PostgreSQL are exercised, but CPU Runtime uses synthetic TTS and a logging sink. Counts prove invocation behavior, not audible output or remote device delivery.
- Go stays alive when Runtime is SIGKILLed; Runtime stays at the same PID when Go is SIGKILLed. Test assertions include stable HTTP logical JSON replay, one Utterance, one synthetic initial sequence, UNKNOWN after lost Runtime incarnation, and Stop reaching ENDED.
- Redis is deliberately unreachable / an invalid configuration in those isolated tests. No shared Redis was stopped.
- Database outage test stops and starts only its own marked cluster. Python spool restart/outage unit tests and the Go-restart process test separately verify retained pending events and redelivery. There is no claim of a full real-media PG-outage soak.
- Whole-file power loss, loss of the persistent spool volume, real sink ACK/Timeline ledger, continuous Narration recovery, SoulX/GPU, RTMP, browser playback and viewer audibility are outside this acceptance. They require B/C/F integration and their own evidence.

## Log SHA-256

```text
ca66f25c95353d58032c4178c1a67f0ae9b6bc646d9151f2fa3611eab6bb5f99  durability-verbose.log
c3c665ab8f3c3b38f8e2a86371cc933188ca4dd749d37446a0a5338739f4de47  faults.log
cd7f4e11ab61fd32375793d2b36394e7f3af4ce529d82cdb657488e256d873be  runtime-unittest.log
```

The fault script cleaned its temporary clusters on exit. The separate Agent A manual test cluster is stopped before delivery; Homebrew's default PostgreSQL service was never enabled. Existing services and shared Runtime virtualenv contents were not changed.

## Continuity seam increment — 2026-10-11 11:05 UTC

Minimal source input pin: `ee5500b132302dbdd365b401d705e4fc47b75b12`, parent `e5f14a14a04fdd4968af3c8dc3530bb22202e8b6`. The supplemental source/evidence commit extends this pin with disk-persistent Timeline observations and additional recovery fences. This section supersedes the earlier “Timeline ledger outside acceptance” wording only for A's repository/HTTP transaction and synthetic proof fixtures; it does not accept B/C production media or continuity recovery. The branch remains independent and main is not merged.

1. `DURABILITY_TEST_PYTHON=/Users/sapiece/innovationProject/AstraLive/runtime/.venv/bin/python backend/scripts/test-durability-faults.sh` — exit 0 on final supplemental production source. Real PG full Go and full race suites, actual CPU Runtime/Go SIGKILL scenarios, independent owned PG stop/start, 11 Python durability tests and frozen v1.1 validator pass. [Final log](continuity-faults.log). Migration-related process fixture cleanup deletes epoch rows before run rows; no production FK was weakened.
2. `DURABILITY_TEST_DATABASE_URL=postgres://sapiece@127.0.0.1:55435/astralive_a?sslmode=disable go -C backend test -race ./internal/durability -run 'Test(Continuity|PreparedEpoch|NarrationAdmission|UnknownProbe|TerminalSession|RecoveryStop|StopConcurrent)' -count=1 -v` — exit 0; **9 named tests** passed. This final targeted run includes the additional old durable ACK versus FORCE-barrier assertion. [Assertions](continuity-seam.log).
3. `PYTHONPATH=runtime:. /Users/sapiece/innovationProject/AstraLive/runtime/.venv/bin/python -m unittest discover -s runtime/tests -v` — exit 0; **170 tests run, 11 skipped**, 9.119 seconds, 159 executed tests passed. [Full log and skips](continuity-runtime.log). Opt-in real services remain NOT TESTED.
4. `go -C backend vet ./...` and `git diff --check` — exit 0. sqlc regenerated using pinned v1.30.0 after 000007; frozen public OpenAPI/generated DTOs are unchanged. No published migration is rewritten by the supplemental commit.

Additional observed boundaries:

- C admission plan, Segment, InteractionTurn, cursor CAS, Outbox and attempt roll back together or commit together. The 006→007 upgrade preserves an old completed Utterance and run sample cursor. Text/product/plan mutation and overlapping intervals are rejected. Composite C transitions may increment revision multiple times inside one CAS; A does not impose a new narration FSM.
- Intent creates PENDING_INSTALL with unchanged cursor. Installed proof advances timeline cursor/revision. Every required sink needs contiguous audio and video over the full interval, matching immutable identity and paired Worker mapping. Missing video, gaps and mismatched generation fail. C callback failure rolls back proof, receipt, cursor and next-command Outbox; duplicate immutable proof does not call it again. These are synthetic server-sink receipts, not device observations.
- Prepared epoch is not media authority. Token guessing, future media admission and stale reservation fail. Concurrent Stop and activation leave a sticky Stop barrier and all epochs SEALED; late activation/proof cannot mutate them. Terminal Session and UNKNOWN-budget recovery also fence narration/attempts/epochs. An already durable ACK cannot bypass a new FORCE barrier.
- The Timeline sender subprocess is actually SIGKILLed while entering its HTTP test double, after FULL SQLite WAL commit. A new sender recovers the original packet/incarnation and sends only the observation. Separate tests cover ACK loss, changed-proof conflict, old local spool migration, shared pending capacity, explicit fresh-Go checks and retained FENCED audit records. HTTP and sink responses in these Python tests are declared test doubles.
- Background observation ACK never unblocks B, re-executes media or hydrates a volatile Timeline. Missing disk spool fails closed. A process that dies after output but before forming/journaling proof still leaves UNKNOWN; persistent-volume loss, whole-machine power loss, real Worker READY staging/credit, actual sink playback and audibility remain NOT TESTED.
- C reported a real-PG/Python/B synthetic workflow separately. It is cross-agent feedback, not a test executed or accepted in this A branch. B/C/F must retain their own integration evidence.

Supplemental log SHA-256:

```text
858fa8ad6df21bd91c2daa5eeb31051dfe702b7df749cb8beb17e2baef3c4687  continuity-faults.log
dc46296b41963c0eac0d3fbc97be4f6b13afc296e4014de510ac3621e549fce8  continuity-seam.log
d77149e7de2184732204c240c0d07f5ffde2a161c3ff8c016737fba58fde6e16  continuity-runtime.log
```

The final fault script removed its own temporary cluster. The separately owned manual PG cluster is stopped before final handoff. Shared services and the read-only Runtime virtualenv are unchanged.

## Frozen Worker wire identifier correction — 2026-10-11 11:47 UTC

F's `18e4ba4` review correctly found that edd4e1e rejected valid Worker IDs above the business safe-JSON maximum. This increment fixes that existing-contract incompatibility. It does not amend the frozen field to a string, change the Worker allocator/credit, expand business integer domains, or modify 000001–000007. The SQL change is additive 000008; the typed proof serializer/hash is field-aware.

1. `DURABILITY_TEST_PYTHON=/Users/sapiece/innovationProject/AstraLive/runtime/.venv/bin/python backend/scripts/test-durability-faults.sh` — exit0 on corrected production source: real-PG full Go, full Go race, process SIGKILL/ACK-loss/Redis-off scenarios, owned PG restart, 12 Python durability tests and frozen validator. [Log](worker-domain-faults.log).
2. `DURABILITY_TEST_DATABASE_URL=postgres://sapiece@127.0.0.1:55435/astralive_a?sslmode=disable go -C backend test -race ./internal/durability -run 'Test(TimelineWorker|WorkerWire|Continuity|Migration)' -count=1 -v` — exit0; five named top-level tests, including four full proof/cursor atomic subcases: no Worker, `2^53−1`, `2^53`, `2^63−1`. The final targeted rerun adds paired Worker epoch/ID, empty epoch, bool/string/zero/overflow and business-overflow assertions after the full regression; production source was unchanged. [Log](worker-domain-go.log).
3. `PYTHONPATH=runtime /Users/sapiece/innovationProject/AstraLive/runtime/.venv/bin/python -m unittest discover -s runtime/tests -p test_durability.py -v` — exit0,12 tests. [Log](worker-domain-python.log). Both languages check the same canonical UTF-8 bytes and SHA-256 vectors in `backend/internal/durability/testdata/worker-proof-v05.json`. Exact pending JSON preserves signed BIGINT values and the original producer. Changed Worker proof conflicts rather than replacing its identity.
4. `PYTHONPATH=runtime:. /Users/sapiece/innovationProject/AstraLive/runtime/.venv/bin/python -m unittest discover -s runtime/tests -v` — exit0, **171 tests run,11 skipped**,9.019 seconds,160 executed tests passed. [Full log](worker-domain-runtime.log).
5. `go -C backend vet ./...`, sqlc v1.30.0 regeneration and `git diff --check` — exit0. No generated DTO/model or frozen public contract delta.

The PG fixture validates READY→intent→installed→completed, C callback/next-Outbox rollback, original proof replay, canonical producer/identity hashing, exact Worker `BIGINT` and JSONB readback, full required audio/video receipts, FORCE and Stop fences at all three Worker boundaries. SQL rejects0,−1 and2^63; its paired-null constraint remains in effect. Go/Python reject wrong proof carrier, duplicate Go JSON keys, bool/string/float/exponent/overflow IDs and business generation overflow. Optional absent/null Worker mappings retain their original representation. Generic command canonicalization and legacy event hashing retain their old behavior.

These are logical persistence/serializer and synthetic server-sink proofs, **not a new real Worker/GPU or audibility PASS**. C's independent Chrome/local-RTMP and five-process-crash reports remain C-owned evidence, not executions on this A branch. F's independent acceptance of the corrected pin is still its own gate. Rollback retains 000008 and journal history, disables Continuity, stops active Sessions and performs the existing isolated deployment checks; do not rewrite published migrations or reinterpret existing IDs.

Log SHA-256:

```text
f63cf2b51f4e508cc469549474b7411d336c6e576d0897aa0bae984f3261bfa0  worker-domain-go.log
b0c993132c0eccf987ab5c2c23c1bbec76e2e0327bf293ba2eabd7afcb9acc6c  worker-domain-python.log
6e8d0f1609f8fd834fe75816b4161a03367c85dd95a2dd5c141512586d2911f2  worker-domain-faults.log
b99d4cb4a6fb1d7e3c6edcb7bb358b30927f69b3d16364e4b7c109c5c72e15e6  worker-domain-runtime.log
```

F's original immutable-source diagnostic was also reproduced by A after the source commit, using unchanged B pin dda7936 and corrected A pin `a2f0be19f1d2fc4c71c8bcefee771b7685b8d6e3`:

```sh
/Users/sapiece/innovationProject/AstraLive/runtime/.venv/bin/python \
  /Users/sapiece/innovationProject/AstraLive-agent-f/integration/v0.5/worker_id_probe.py \
  --repo /Users/sapiece/innovationProject/AstraLive-agent-f \
  --a a2f0be19f1d2fc4c71c8bcefee771b7685b8d6e3 \
  --b dda7936faba56efe01659b6393a4d32a93322508 \
  --output /tmp/astralive-agent-a-worker-domain-probe.json
```

Exit0 / PASS:2^53−1,2^53 and2^63−1 accepted by actual B identity and A disk staging;2^63 rejected by B. [Diagnostic JSON with pinned imported-source hashes](worker-domain-f-probe.json). This execution is an A reproduction of F's CPU serializer probe, not F's independent approval and not HTTP/PG/GPU acceptance; the separate PG tests above provide the database evidence.

```text
9afcb2e032599d7e71e37d404605bd304939479e2f93a77115b80b92f11a029c  F worker_id_probe.py
9b022dc9520acab97d4f2ff40509d8e97a0dd2789d3b3e06910aa14471d7e8b0  worker-domain-f-probe.json
```

The following evidence-only commit adds this reproducible result; production source is identical to a2f0be1. The owned manual PG cluster is stopped and the workspace is clean before handoff.
