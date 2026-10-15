# F premerge integration harness

This package reproduces missing A/B/C seams before any branch merge. It is a negative gate, not an implementation of Narration or a real-media acceptance test. It makes no change to frozen contracts or owner worktrees.

`premerge_probe.py` archives exact A/B commits into owned disposable directories, copies F's Go fixture into the **temporary A checkout**, migrates an owned PostgreSQL cluster, runs actual Go journal and Python HTTP Runtime with CPU fixture providers, checks missing schema/handlers/receipt adapter, and calls B's Timeline. No durable ACK is faked. Known core gaps yield exit1/result FAIL and are retained. C has no implementation to exercise. Production Backend auth/public-resource/Session creation is not emulated as passed; the fixture seeds a known owned test run directly.

Requirements: local installed PostgreSQL binaries, Go, Python3.12+ with Runtime dependencies, and both source SHAs in the Git object store. Existing validated Runtime Python can be borrowed without installing/changing dependencies. Never supply a production DB; the script creates its own local cluster automatically.

```sh
/path/to/runtime-python integration/v0.5/premerge_probe.py \
  --a-sha e5f14a14a04fdd4968af3c8dc3530bb22202e8b6 \
  --b-sha cf43e2d3dd6a9223648eaced2526d13e0ccbf8e1 \
  --pg-bin /opt/homebrew/opt/postgresql@17/bin \
  --output /tmp/new-unique-f-output
```

Output must not already exist. All child processes/cluster are owned by this run and cleaned in finally. Secrets are freshly generated private files in the disposable directory, never serialized in the result. Logs contain static fixture text/IDs only. A future version must add real C plan/cursor tests and a genuine persistence adapter; do not turn these failures green by returning `{durable:true}` from a test double.

Independent module checks use an isolated archive of each pin so concurrent owner edits cannot invalidate evidence:

```sh
mkdir /tmp/new-unique-a-source
# Substitute B or D SHA for their respective checks; never overlay implementation files.
git archive e5f14a14a04fdd4968af3c8dc3530bb22202e8b6 \
  backend runtime contracts gpu_worker tests integration | tar -x -C /tmp/new-unique-a-source
# From this archive, run exact commands in docs/v0.5/CHAOS-TEST-REPORT.md.
```

Do not run old scripts that write historical docs/v0.4 outputs without redirecting/isolating their evidence. No branch merge occurs in this harness. More Golden fixtures/faults/Chrome/RTMP measurements are pending C and actual integration; unexecuted cases are NOT TESTED.

## Retained C Scheduler draft review

`fixtures/scheduler_review/scheduler_review_test.go` adds CPU-only boundary/deferred-expiry/legacy-busy/operator/product checks alongside the original Scheduler tests. The preserved draft patch and source hash are in `docs/v0.5/evidence/integration-f/scheduler-review-1/`. This patch is reviewed evidence, not an F edit to C-owned production source. Reproduce in a disposable archive, not an owner worktree:

```sh
mkdir /tmp/new-unique-c-scheduler
git archive 7924f7f74c303fada428885bf01a1ca915aecf64 backend | tar -x -C /tmp/new-unique-c-scheduler
cd /tmp/new-unique-c-scheduler
git apply /path/to/AstraLive-agent-f/docs/v0.5/evidence/integration-f/scheduler-review-1/scheduler.patch
cp /path/to/AstraLive-agent-f/integration/v0.5/fixtures/scheduler_review/scheduler_review_test.go \
  backend/internal/interaction/f_scheduler_review_test.go
go -C backend test -race -count=1 -v ./internal/interaction
```

These tests do not validate C's production dispatcher, flag wiring, SQL cursor, media readiness or naturalness. The reviewed C Runtime flag differed from the frozen canonical name and requires an owner correction; race PASS does not pass that separate compatibility gate.
## Pinned module and postmerge gate

### Optional private staging wire observation

`staging_wire_observer.py --upstream-port <existing-local-SSH-forward> --output <new-private-jsonl> --ready-file <new-private-json>` opens an extra loopback-only TCP hop. Read its selected `listenPort` and pass that port to `golden_gate.py --worker-port`; management keeps its original independent port. It forwards original framed bytes and records only schema-validated, allowlisted control metadata (including physical StageReleased native-safe/zero-retained proof). Auth, raw audio/video, grants and arbitrary payloads are not recorded. Both new files use mode0600 and exclusive creation. Stop this owned observer after Golden cleanup and retain its log/hash with the test topology.

Optional `--frame-metadata` additionally records validated StageVideo/StageReceived/StageReceivedAck identity, sequence, hashes and payload size, with local monotonic read-complete, forward-drain-complete and validation-complete anchors. Raw pixels remain excluded. This allows observer-local frame/credit timing; a forwarded credit ACK is not the instant the remote Worker actually replenishes its four-frame window. The original default records control metadata only.

This is acceptance instrumentation, not a production transport change or performance optimization. A logged ACK alone proves neither Runtime correlation/acceptance, durable SQL terminal state nor audience audibility. Invalid/partial/foreign control messages cannot become validated observer proof; original bytes are still subject to production validation. Eight local synthetic/TCP tests verify forwarding/privacy/rejection/EOF/frame bounds and opt-in trace timing. They do not establish real GPU release. When used, report the additional TCP hop in latency comparisons.

`module_gate.py` archives the supplied immutable source or actual F merge commit, runs A's owned temporary PostgreSQL/full Go/race/process-fault/migration/auth/interaction/contract gate and complete Runtime discovery, and records exact commands, exit codes, durations, environment and SHA256 logs. It never starts real providers/GPU. The optional frontend argument runs tests/build using installed dependencies only after confirming the donor and archived `bun.lock` match. Source archives and the owned PG cluster are disposable; owner worktrees are not changed.

```sh
python integration/v0.5/module_gate.py --repo "$PWD" --source <commit-sha> \
  --output <new-evidence-directory> --python <runtime-python> --pg-bin <postgres-bin> \
  --frontend-modules <matching-frontend-node_modules>
```

Omit `--frontend-modules` for a premerge module check only; the result marks frontend NOT TESTED. Each postmerge gate must include it. A PASS covers the executed software/SQL fixtures only; opt-in media skips and real GPU/Chrome/RTMP/naturalness/host acceptance remain separate gates. Never reclassify an independent source-pin run as a test of an actual merge commit.

F's evidence-directory `.gitattributes` preserves exact captured raw log bytes and recorded SHA256, including native tool trailing whitespace/blank lines. Source/docs whitespace validation stays enabled. This F-owned evidence-only rule depends on the postmerge runner and changes no test result or historical log.

## Immutable native narration gate

`narration_gate.py --repo <F-repo> --source <exact-SHA> --output <new-owned-directory> --python <media-python> --pg-bin <PG-bin> --mode short|soak` archives the exact source, owns a disposable PostgreSQL cluster, and runs C's explicit native Chrome/local RTMP opt-in. `soak` is one continuous600-second source with five seeded questions; its20-minute Go harness deadline does not alter service queues/timeouts. The Go controller, authenticated HTTP journal, PG, Python Timeline and physical browser/FFmpeg are real, inference is deterministic language/synthetic pulse TTS/Lightweight2D. Never claim SoulX, human naturalness or physical audibility from this gate. Failure logs, per-run source/versions/dependencies/media hashes and owned cleanup disposition remain separately recorded.

A dedicated F media Python requires existing `runtime/requirements-real-media.txt`, `requirements-real-avatar.txt`, `requirements-personal-avatar.txt`, plus playwright/psutil and validator dependencies; native Chrome and FFmpeg must be installed. Do not mutate shared owner environments. Module gate now also sets NARRATION_TEST_PYTHON so enabled PG tests cannot silently skip their Python HTTP fixtures.

`narration_gate.py --mode control --overlay-test integration/v0.5/fixtures/borrowed_stop/borrowed_stop_test.go` runs the real-SQL Scheduler/retirement rollback oracle on an immutable source; it records the overlay hash separately. C06b182f intentionally fails this gate. A fast corrected hook must leave Scheduler running when the outer transaction rolls back and must not block unrelated-room snapshots. This is control-plane fault evidence, not media acceptance.
