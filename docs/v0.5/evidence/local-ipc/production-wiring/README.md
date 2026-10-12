# D production wiring review (2026-10-12)

Dependency F `48eb0387f4e0f7db08ca8b64d3ae02c2207a9f57` (A+B+C core `6095989`), normally merged into D as `b6f65bd`. C's approved Timeline flag parser source `43a41403a887ef31f7b3ecf165a9aff7302bb5d8` was cherry-picked as `bc46a20`. Frozen contracts and migrations unchanged. F is final merge owner; A auth and C startup scoped review requested, not inferred.

Shared-file changes are now actual source rather than an unapplied patch:

- `backend/cmd/server/main.go`: capture validated local transport; retain token wrapper outside dialer; command and protected probe transport share startup choice. Use C's precise `narration.TimelineEnabled()` prerequisite parser. A PostgreSQL-only/journal/dispatcher/recovery and C coordinator wiring retained.
- `backend/internal/userconfig/{service,environment,session_binding,provider_probe,local_transport}.go`: protected provider-status and TTS calls also use captured transport; control token reread remains in existing TokenTransport. Worker and Python-to-Go journal transports unchanged.
- `runtime/app/production_launcher.py`: feature-off preserves exact original TCP exec/18000 command; opt-in routes through private listener while retaining existing publisher lock and preflight. This launcher remains Linux-specific.

New actual cmd/server + real PG + Python production-listener subprocess gate uses existing CPU fault fixture providers, not real inference. It checks PostgreSQL-only startup, authenticated public Start/Speak/Stop, idempotency and Backend SIGKILL/restart separately on TCP and UDS. Protected secondary probe transport tests use explicit HTTP protocol fixtures; synthetic responses do not verify XiaoYa synthesis. Launcher tests stub only bootstrap lock path, preflight and runner to verify branch selection/lock cleanup; they do not establish Linux preflight execution.

Linux production rerun and Windows runtime are NOT TESTED until recorded actual execution. Previous Linux standalone evidence is historical and is not promoted to integrated-source acceptance. No GPU/cloud access, shared service reconfiguration or default enable occurs in D.
