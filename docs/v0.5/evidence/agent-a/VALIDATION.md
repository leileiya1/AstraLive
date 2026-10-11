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
