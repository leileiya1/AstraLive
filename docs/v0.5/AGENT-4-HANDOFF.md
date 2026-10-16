# Agent 4 handoff

Final conclusion: **ASTRALIVE V0.5 BLOCKED**. Integration branch: `integration/v05-durable-live`. Do not merge/enable as accepted v0.5.

Read INTEGRATION-REPORT.md, RELEASE-GATES.md and CONTRACT-CHANGE-REPORT.md first. CCR-ADL-001 is submitted to Agent 1/affected owners at https://github.com/leileiya1/AstraLive/issues/7; pending explicit ACK, keep durable-live-1 unchanged and COMMENT fail-closed.

## Implemented entrypoints

- `backend/internal/durableintegration/`: schema-preserving 11-operation Adapter, real Product Tool Facts, real SQL Manager + existing Scheduler Controller. No Fake production store.
- `backend/internal/durablelive/policy.go`, `product.go`, `completion.go`: authorized consistent projection/fact source and CONTROL completion from trusted applied drain evidence only.
- Actual Backend/Runtime main: durable LIVE=true refuses OUTPUT_FENCE_UNPROVEN. Backend always recognizes persistent durable Session membership after restart/rollback and blocks legacy control. Old v1 lifecycle events archive only for managed Sessions.
- `/api/v0.5/durable-live/sessions/{sessionId}` GET: owner-authenticated read; unmanaged returns managed=false. `/runs/{runId}/decisions` POST: existing frozen decision seam with explicit attempt/revision/reason and server-derived operator identity; `/runs/{runId}/stop` POST: durable tombstone, not proof of physical mute. Browser uses normal product authentication, never internal role tokens.
- `VITE_DURABLE_RECOVERY_ENABLED=true` displays the recovery panel. It does not authorize LIVE. WAIT records knowledge; SKIP needs an independent barrier and records a gap; CREATE_NEW_TURN records intent and does not dispatch a new comment automatically. No Resume-live button while release is blocked.

## Reproduce

Use an isolated Python 3.12 environment with runtime/tests dependencies and local PostgreSQL >=16 / Redis / Go / Bun. Run from repo root:

```sh
PATH="/opt/homebrew/opt/postgresql@17/bin:$PATH" /tmp/astralive-agent2-python/bin/python scripts/durable-live/run_agent4_acceptance.py --python /tmp/astralive-agent2-python/bin/python --evidence-dir /tmp/astralive-agent4-reproduction
```

The supplied interpreter path is the test environment used here; another host must supply its own. The runner creates disposable databases/services, never reads project .env, requires unused loopback ports, records raw JSON/logs/resources and cleans up only its own services. Full Go packages run sequentially because intentional database outages must not race unrelated package tests. The runner enables real isolated configuration/Provider Binding/formal CPU-chain regressions. Latest successful raw evidence is `evidence/agent-4/verified/`; summary is `verification-summary.json`. Go/race each 141 PASS/0 FAIL/3 SKIP; Runtime 158 PASS/11 SKIP; Journal 11 PASS; contracts 17 PASS; frontend 45 PASS/build PASS. Additional legacy local aiortc has 4 PASS and is not Chrome/GPU acceptance. Logs from earlier patch-only checks refer to temporary snapshots, not current production acceptance.

## Outstanding work

Approve and implement CCR with coordinated contract upgrade and additive answer-fact artifact migration. Build/verify isolated Guardian credential/socket/FFmpeg/WebRTC ownership. Implement trusted principal registration plus complete formal Session/Binding/Worker lifecycle, correct real ingress mapping and production SCRIPT/COMMENT executors with real drain observations. Wire Deployment.Run/Controller only after those gates. Run the full production crash matrix, real GPU/Chrome/RTMP and latency/mixed load. No production credentials or GPU access were used in this integration.

Tested integration code commit: `5652ad44a77b42e961a31d8613b631935afb3fe9`; its 360 source-file hashes match verified/source-manifest.json. The verification summary records that match. Final evidence/metadata SHA and PR URL are in the PR and final delivery. Main is not changed by this handoff.
