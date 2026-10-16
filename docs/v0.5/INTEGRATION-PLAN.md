# Agent 4 integration plan

Baseline verified by fresh `git fetch origin --prune` and GitHub PR queries on 2026-10-16.

| Source | Full SHA | Verified state |
| --- | --- | --- |
| main / PR #4 merge | 7fe5d24810e2df348c58dd7748e97ffbe5cff384 | main; PR #4 MERGED |
| Contract delivery | ae28144d15afcf0e5f5ea8fa425fc42d27fc047b | ancestor of main |
| PR #6 Agent 2 | 55c4dad81545a04946b4d58b706fc6abb14e67fa | OPEN |
| PR #5 Agent 3 | ed2ebb235cb89e4b10b8a6f9670c6a1be00b1511 | OPEN, DRAFT |

The existing dedicated worktree was clean, on `integration/v05-durable-live`, exactly at latest main. It is reused without changing other worktrees. Original deliveries are retained through merge commits, Agent 2 first. No experimental branch is consumed.

1. Read architecture, both handoffs, protocol/schema, SQL, journal, planner/manager, shared patches and production Session/media implementations.
2. Merge Agent 2, run its isolated PG/Redis/process suite and legacy regression before merging Agent 3. Evidence: `evidence/agent-4/stage-agent2/`.
3. Merge Agent 3, run complete baseline regression before shared wiring.
4. Submit CCR-ADL-001 for answer preparation. Preserve `durable-live-1` and COMMENT START rejection until explicit Agent 1 and affected-owner ACK. Do not add an unofficial endpoint.
5. Implement schema-preserving Store adapter and authorized, revision-consistent policy projection. Test actual SQL with both modules, including source identities, fairness, cursor, CAS, Stop and UNKNOWN. Missing/oversized projections must fail closed.
6. Apply reviewed shared seams, isolate session scheduling modes and default-off feature admission. Supply exact-text execution separately from legacy LLM rewriting. Runtime output cannot use legacy OR-drain as all-required evidence.
7. Establish a production Guardian compatibility/deployment plan. Actual publisher credentials, FFmpeg connections and WebRTC peers must be outside untrusted Runtime. No boolean/environment assertion may manufacture isolation. If unproven, reject durable LIVE with OUTPUT_FENCE_UNPROVEN.
8. Run isolated failures only on owned processes/services; separately record missing whole-host, production Guardian and GPU coverage. Never stop a shared Worker/service.
9. Run Go/race/vet, Runtime/Journal, schema, migrations, PG/Redis faults, planner/manager, frontend and frozen-v1.1 checks. Capture commands, raw logs, skips and resource observations.
10. After safe gates, short authorized real GPU/Chrome/RTMP acceptance. If prerequisites block it, retain counts as zero and statuses BLOCKED/NOT TESTED; no synthetic latency substitutes.
11. Publish reports and code on the independent integration branch and a reviewable PR. Do not merge main. Final acceptance requires every P0 gate.

## Conflict register

| ID | Finding | Resolution |
| --- | --- | --- |
| C-001 | Two mechanically generated Go DTO packages | Lossless typed adapter, validated by authoritative Store schema; no wire changes |
| C-002 | RestoreSnapshot omits candidates/history | Authorized in-process SQL projection at the same run revision; never assume empty |
| C-003 | No frozen answer-prepared operation | CCR-ADL-001; COMMENT fail-closed pending approval |
| C-004 | Agent 2 handoff references `integration/agent-2-shared.patch` | Actual tracked file is `docs/v0.5/integration/agent-2-shared.patch` |
| C-005 | Legacy fanout drain accepts any successful sink; GPU consumption credit uses OR | Preserve legacy behavior; no durable completion inferred from these APIs |

Additional resolved conflicts:

- C-006: Agent 3 admits WAITING comments but Agent 2 only accepted READY. Store now persists WAITING and performs WAITING→READY→DISPATCHING in the same guarded slot/attempt transaction.
- C-007: Agent 3 source-member cap altered legacy overflow counters. Strict source admission is now opt-in through Controller's PreserveSources=true; legacy continues its prior merge counting while the new member array stays bounded at 128. Both modes have explicit regression coverage.
- C-008: A retained boundary from the previous epoch caused new-epoch Yield to fail after a legitimate Skip/recovery. Activation clears only that stale free-slot boundary; history remains intact. Manager accepts genuinely completed later segments after an authorized gap without advancing completedPrefix across the gap.
