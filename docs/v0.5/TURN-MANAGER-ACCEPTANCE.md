# Turn Manager integration acceptance

Production natural comment interruption and explanation resume: **BLOCKED**. Source integration and CPU/real-SQL evidence are separate below.

Implemented source: `durableintegration.Adapter` supplies all 11 generated operations through Store.Call with fixed authenticated principal and schema validation; it does not change hashes, timestamps, IDs, CAS or epochs. `ReadPolicyState` reads authorized SQL candidates, the complete budget since the last completed script, active turns, binding/lease readiness and attempt-linked gap decisions under the same run revision. Revision mismatch or more than 1024 projection rows rejects; missing history is never an empty list. Current product source/version covers exact product facts with decimal-string price. Fact revalidation runs outside transactions and current product is rechecked inside claim/start transactions.

`Controller` composes the original interaction Scheduler, SelectionAdapter and the real SQL Manager. A short-lived atomic gate cache prevents SQL under Scheduler mutex. It is currently limited to the existing mock platform ingress mapping; production platform ingress/receipt mapping and application activation remain gated. Merged source identities are preserved. Strict 128-member admission is enabled only for durable Controller; legacy overflow merge counters remain unchanged and its stored new member list is still bounded. TestDurableSourceCapPreservesLegacyMergeCounters covers both modes. The Controller does not create physical Sessions, publish media or grant fencing.

Agent 2's admit now accepts a COMMENT WAITING as specified by the common contract. Claim transitions WAITING→READY→DISPATCHING atomically only after slot/epoch/lease/TTL/plan checks. New commands refresh validated same-value fact timestamps without altering the plan or any previously issued command. New-epoch activation clears stale boundary references only when no active slot exists; historical evidence is retained. Manager skips genuine later completions after an authorized gap while completedPrefix remains unchanged.

Real PostgreSQL integration tests (media facts below are injected test evidence):

- TestPostgresManagerBoundaryCommentResume: current script retains slot; comment waits; full drain and CONTROL business commit precede answering; restart Manager; next script is sequence 2, not sequence 1; stale planning facts refresh; duplicate completion does not create another attempt.
- TestPostgresRealSchedulerSelectsMergedCommentsDuringScript: actual existing Scheduler merges three XL questions, persists all three identities, admits one WAITING turn while script remains the only media slot.
- TestPostgresFairnessBudgetSurvivesManagerRestart: five persisted selected comments, two completed answers, then mandatory script; restart cannot reset the budget.
- TestPostgresProjectionAuthorizationRevisionAndProduct: real owner/revision/product checks and consistent nonempty candidates.
- TestPostgresUnknownGapAndStopPriority: UNKNOWN blocks; Skip without proof rejects; authorized gap is not completion; a new term resumes sequence 2 then 3; Stop cannot revive.
- TestPostgresManagedSessionLateLifecycleCannotAutoStart: old lifecycle events archive only and legacy Start/Speak/FORCE reject for a durable Session.

COMMENT tests first prove unprepared START rejection. They then use Store.RecordAnswerText **only inside the Go test process** to exercise downstream SQL arbitration. This is not a production cross-process operation and does not resolve CCR-ADL-001. No Fake is used as production storage.

Existing Agent 3 planner/policy tests and added Runtime Gate/retention and UI decision retry tests are CPU/Mock. The UI uses owner-authenticated public routes, requires reason/attempt/revision, keeps exact decision identity/body on ACK loss and exposes WAIT/SKIP/new-turn intent plus durable Stop. A new-turn decision records intent; it does not automatically re-answer a comment or start media. `VITE_DURABLE_RECOVERY_ENABLED=true` exposes the recovery panel; it does not enable durable LIVE.

Actual SCRIPT_TEXT→XiaoYa→SoulX output wrapper, COMMENT fact/DeepSeek answer preparation over approved wire, all-required real drain observers, automatic formal Session lifecycle and Guardian ownership are still release blockers. The authenticated recovery HTTP test also ran against actual PostgreSQL: missing login rejected; cross-owner Session read/Stop/decision denied; CSRF denied; owner Stop and identical retry persist exactly one intent. No real busy-speaker sample has been collected.

2026-10-17: PR9 candidate review withheld Agent4 ACK for valid drain-before-next-prepare ordering and Grant-renewal semantics. PR10 source is staged disabled; its Attempt-scoped IPC/SQL does not yet implement v2 artifact/grant fencing. No production comment/segmented speech/resume or latency gate changed. See PR-9-10-REVIEW.md.
