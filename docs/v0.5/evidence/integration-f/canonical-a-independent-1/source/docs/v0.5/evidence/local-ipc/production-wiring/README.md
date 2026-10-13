# D production wiring review (2026-10-12)

Dependency F `48eb0387f4e0f7db08ca8b64d3ae02c2207a9f57` (A+B+C core `6095989`), normally merged into D as `b6f65bd`. C's approved Timeline flag parser source `43a41403a887ef31f7b3ecf165a9aff7302bb5d8` was cherry-picked as `bc46a20`. Frozen contracts and migrations unchanged. F is final merge owner; C startup/config and A auth/Dispatcher scoped ACKs are recorded below.

Shared-file changes are now actual source rather than an unapplied patch:

- `backend/cmd/server/main.go`: capture validated local transport; retain token wrapper outside dialer; command and protected probe transport share startup choice. Use C's precise `narration.TimelineEnabled()` prerequisite parser. A PostgreSQL-only/journal/dispatcher/recovery and C coordinator wiring retained.
- `backend/internal/userconfig/{service,environment,session_binding,provider_probe,local_transport}.go`: protected provider-status and TTS calls also use captured transport; control token reread remains in existing TokenTransport. Worker and Python-to-Go journal transports unchanged.
- `runtime/app/production_launcher.py`: feature-off preserves exact original TCP exec/18000 command; opt-in routes through private listener while retaining existing publisher lock and preflight. This launcher remains Linux-specific.

New actual cmd/server + real PG + Python production-listener subprocess gate uses existing CPU fault fixture providers, not real inference. It checks PostgreSQL-only startup, authenticated public Start/Speak/Stop, idempotency and Backend SIGKILL/restart separately on TCP and UDS. Protected secondary probe transport tests use explicit HTTP protocol fixtures; synthetic responses do not verify XiaoYa synthesis. Launcher tests stub only bootstrap lock path, preflight and runner to verify branch selection/lock cleanup; they do not establish Linux preflight execution.

Linux production rerun and Windows runtime are NOT TESTED until recorded actual execution. Previous Linux standalone evidence is historical and is not promoted to integrated-source acceptance. No GPU/cloud access, shared service reconfiguration or default enable occurs in D.

## Fixed-source results

Final tested source `ecc43dd2a829fff80620b060519a1336527d6e39` retains production implementation `3a571fb`; its extra changes only skip Unix fixtures on unsupported platforms. Raw `final-full-faults.log`: full Go and full race using real PostgreSQL and actual Python subprocesses exit 0; both TCP/UDS production entry tests, protected transport fixture, original A/C regression, owned database outage, twelve durable Python checks and v1.1 validator pass. `final-runtime.log`: 223 tests, 12 skipped, exit 0. The additional skip versus core is the root-required foreign-owner socket test; provider/media integrations remain opt-in skips.

Windows compilation log uses `-exec=true` and does not execute a Windows binary. Linux integrated production launcher/preflight, Windows actual runtime/auth, real XiaoYa/SoulX, UDS browser/media/narration and speedups are NOT TESTED. Historical standalone Linux evidence is retained separately. No default changes.

Reproduce final core gate with the existing installed Runtime Python (the test script creates and destroys only its own PostgreSQL):

```sh
GOFLAGS=-v ASTRALIVE_IPC_TEST_PYTHON=/absolute/path/to/runtime/python DURABILITY_TEST_PYTHON=/absolute/path/to/runtime/python bash backend/scripts/test-durability-faults.sh
PYTHONPATH=runtime /absolute/path/to/runtime/python -m unittest discover -s runtime/tests -v
```

`manifest.json` records immutable source SHA, all exact log hashes, source file hashes, command scopes and remaining tests. Initial logs are retained with their source-mutation note; final logs are a fresh fixed-source run. This does not claim live media or audience acceptance.

## Scoped owner ACKs

C ACKed exact production `3a571fb` startup/config: approved Timeline helper, continuity prerequisite and original AttachNarration worker wiring retained. A finalized scoped ACK `3a571fb` / evidence delivery `1a73eff`; its independent immutable archive ran full real-PG Go/race/outage/durable12/validator and a second focused verbose race gate for both TCP/UDS production Backend public Start/Speak/Stop, Backend restart/idempotency, actual Python listener auth/lifecycle, socket safety, redirects/cancellation and protected helpers—all exit 0. A reviewed `ecc43dd` as unsupported-platform test guards only, with unchanged production source. A-owned evidence commit: `6ca40cba5fd0d384ce753370dabdc8c6ca2f9867` (`docs/v0.5/evidence/agent-a/d-production-review/`). No owner ACK elevates Linux/Windows/GPU/real providers/SLA or substitutes F independent integration acceptance.
