# Agent4 first v2 production-module review — 2026-10-18

PR13 **BLOCKED** at `0230d93cbcb1a353ba2270670d26fcf467cd1c21`; PR12/11 preliminary review only, neither merged. Reviewed on original `AstraLive-agent-4` / `integration/v05-durable-live`, starting at official DTO delivery `e3302f6b2bb19e0184cde3a6cbbcaf3ea4371565`. Temporary `git archive` source snapshots are not worktrees/branches. No other Agent worktree was edited.

PR12 pin: `3c5c6343391b0c1264cf6aad3848666a7c369294`; PR11 pin: `d8eb05e79661b859547242575e0ac6d1d7303aa1`. All three PRs target integration and remain Draft. No configured PR13 CI checks were present; independent checks are recorded below.

Approved freeze: `c7fd46209d3cbc6f58541dba8b4e1c85609c823e`; digest `3c0c317ed00f6fa4d2cf15ef3f61fc002d4bb22bf02d53ee9f1b407458bb28b1`. Independently verified all22 normative hashes at integration and all three PR pins; migrations000001–000006 retain their bytes. No normative file was changed during review.

## PR13 findings

Ownership is additive migration000007 + `backend/internal/durablelivev2/authority/` + handoff/evidence/unapplied shared patch. It imports the sole Agent4 wire package; does not redefine wire types or register routes. Internal `Document` is a repository-domain representation, strictly checked at `Handle`/`Call`; Actor must still be authenticated composition-root data. Actual transport and process authorization are not implemented by those DTO checks.

Read the complete v2 handoff/shared patch, migration and Authority source. Real SQL regression independently exercised empty/000006 upgrade, four concurrent migration runners, prior product bytes/v1 revision preservation, low-privilege SELECT/INSERT denial, concurrent Prepare/CAS, sixteen-connection single consume latch, Stop/registration/Consume competition, rollback, exact-ticket and cross-scope rejection, persisted answer text/hash/fact/snapshot identity, owned commit-then-SIGKILL, fresh Backend false/null, UNKNOWN audit/retained slot and Unit2 drain. Those tests passed with synthetic assertion/physical source/Observer callbacks. This does not validate real installation, fact extraction, Guardian or Runtime TTS.

**P0-R13-OUTPUT-DEADLINE — current output authority is not carried through final time checks.**

`store.go:state.registered` requires `dl05_room_outputs.expires_at > clock_timestamp()` but SELECTs only `true`; that deadline never enters `st.limit`. The later `Call` pre-commit check verifies `st.limit`, which includes other deadlines but excludes this one. `answer.go:permit` derives expiry from that incomplete limit; `consume.go:snapshot` publishes Permit expiry/remainingProofMs without the earlier output expiry. Thus the module's own current-output eligibility predicate can become false before a positive response, or while the recipient still holds the advertised proof budget.

Independent PostgreSQL17.11 race-mode reproductions using the official validator and existing fixture:

1. Prepare/Permit/START normally; set Room output expiry to DB time+150ms; pause only `CommitReceiverConsumeResponse` validation for220ms (same pre-commit fault pattern as the submitted late-validation test). Result: **true returned with output expired, one durable latch**. No TTS or actual media was invoked.
2. After START, shorten Room output expiry to+250ms; QueryReceiverAuthority advertises **786ms** remaining proof and validUntil after that output deadline.
3. Before AcquireOutputPermit, set Room output expiry to+250ms; newly minted Permit TTL is **800ms**, expiry after output deadline.

All three fail tests asserting conservative behavior. Reproductions ran only on newly created loopback test clusters; source and raw JSONL are saved in evidence. They identify an Authority eligibility gap, not a demonstrated real-media output bypass. A later Guardian query may reject an already expired output, but does not repair an overlong valid proof or a stale positive Backend decision.

Minimum Agent2 repair, within the approved protocol: read/retain the current output deadline under the existing Run/shared-output lock domain; consistently cap issued Permit/Grant/proof validity and current Authority timing by all relevant current deadlines; final positive publication must not survive that bound. Refreshing current proofs must never extend the immutable original Grant or resurrect a consumed/UNKNOWN execution. Add the three regression cases plus normal Unit1/Unit2/ongoing renewal and existing Stop/unique-latch tests. Define/document the existing output mirror lifetime consistently with the trusted Registrar composition; do not invent a new wire field or weaken the current-output predicate. Agent2 edits its own Authority/test files in its existing worktree; Agent4 does not patch that exclusive implementation here.

## Shared migration assertion (Agent4-owned, staged only in candidate)

Actual migration source set is exactly000001–000007 with no duplicate prefix or missing version. Reproduced the submitted original test failure (`got7`, expected6). Reviewed Agent2's 6→7 patch. Candidate instead compares the **explicit seven sorted migration filenames**, checking unexpected/missing versions rather than only count. Existing upgrade/data-preservation/repeated-Migrate assertions remain. Saved patch has zero context (`git apply --unidiff-zero`); it must only be applied together with000007. The patch is [agent4-migration-versions.patch](../evidence/agent-4/pr13-review-2026-10-18/agent4-migration-versions.patch).

This correction was physically written into the isolated candidate source; full Go test/race/vet used no overlay. **Not applied to integration**, because000007 is not merged and PR13 is blocked.

An additional Agent4 integration gate is exposed: the non-normative historical `protected-files.json` inventory records the old shared test hash. Candidate contracts therefore have136 PASS/1 FAIL at that precise file, and the candidate validator rejects the same change. Exact unmodified PR13 has137 PASS. Before a future controlled merge, Agent4 must preserve the historical preimage and audit this authorized strengthened-test change against an explicit expected postimage in the protection inventory/checking workflow, then rerun all137; never ignore the failure or refresh unrelated hashes. No protection inventory/checker or22 normative files were changed in this review. Agent2 is not asked to edit the shared test or protection policy.

## Independent checks and limits

| Code under test | Result |
| --- | --- |
| Exact PR13 isolated native PostgreSQL Authority runner |30 top-level PASS /0 FAIL /1 owned-child helper SKIP; real SQL, fixture physical adapters |
| PR13 + on-disk explicit migration-set correction, full Go test -count=1 |172 top-level PASS /0 FAIL /12 SKIP |
| Same candidate full Go race -count=1 |172 top-level PASS /0 FAIL /12 SKIP |
| Same candidate go vet |PASS |
| Agent4 additional output-deadline cases |0 PASS /3 FAIL → merge BLOCKED |
| Original shared migration test against000007 |1 expected reproduced FAIL |
| Exact PR13 retained contracts |137 PASS |
| Candidate with strengthened shared test, contracts/validator |136 PASS /1 protected-file hash FAIL; validator FAIL at same path |
| Official wire / Journal / v1 validator / generator check |13 PASS /11 PASS /PASS /PASS |
| PR12 contentplan + turnmanager domain race |60 top-level PASS /0 FAIL /1 optional export SKIP |
| PR11 v2 CPU/IPC/libav/process/fsync tests |69 PASS /0 FAIL /0 SKIP; mocked Authority/Registrar/codec/evidence registration |

All skip identities/reasons and exact commands/cwd/exit codes appear in [summary](../evidence/agent-4/pr13-review-2026-10-18/summary.json) and the adjacent raw logs. Twelve Go skips include two owned helper entrypoints (parents exercise their child scenarios), optional browser/provider/formal CPU/userconfig/event fixtures, optional export, whole Redis outage and whole PostgreSQL outage. New dedicated Redis stream/reclaim ran; no shared service was stopped. Whole-server outage tests were left opt-in because their old restart paths assume dedicated fixed ports; no claim that those outages passed. The initial extra cluster launch failed on Darwin's locale startup requirement; raw log retained, subsequent isolated runner explicitly sets LC_ALL=C. Owned PostgreSQL/Redis processes were stopped; data/logs retained. CPU deltas/cumulative child RSS are recorded, not steady-state performance or GPU measurements.

## PR12 preliminary compatibility

Official Go DTO dependency is the delivered e3302f6 pin; ownership stays in two additive answerstream subpackages. The coordinator owns no Turn allocation/DB/cursor, distinguishes first START and continuation, serializes start ownership, prepares a bounded lookahead and waits for trusted drain before Unit2 START. Scanner releases a recognized complete trusted-language production without provider EOF; facts/rules are required from trusted Tool projections, not model-authored assertion declarations. Seal alone cannot complete the business Turn or advance product cursor. Stop/uncertain ACK paths are conservative.

Still required: a real Agent2 Store/Handle-backed Executor/Completion test and production adapter, authoritative ProductProjection→Rule/Facts mapping, CAS/Prepare retry/drain/Seal interop with actual SQL and real once-TTS receiver ACK. Current Executor callbacks are mocks. Agent3 should add that interop in its existing owned answerstream test/adapter files after Agent2 fixes/repins Authority; Agent4 owns shared source/provider/Runtime/authentication wiring. No final production ACK or merge of PR12 this round.

## PR11 preliminary compatibility

The short gate, irreversible Run tombstones, fsynced deny-only journal, two ACK/Stop rechecks, immutable queued lineage and continuous CPU codec/decoded-sink edges are consistent with the intended isolated stage. Source separates blocking fsync/RPC/Observer work from the gate. Native CPU tests exercise actual sockets, owned children, filesystem operations, lossless FFV1/PCM decoding and sink ranges; fixture Evidence registration is explicitly synthetic. Normal Finish keeps the publisher/Session clocks and closes only its unit.

PR11 predates the official SDK dependency and still requires Agent4's adapter for the sole Python DTO (its injected Wire currently expects domain mappings), actual authenticated Backend Authority transport, trusted installation/keys/process scopes and receiver Runtime client. Adapter work must preserve opaque SecretString and typed validation/intentional wire serialization without copying Schema; no permissive dict codec or test reference implementation may enter production. These are composition dependencies, not approval for a new authorization protocol. Agent5 retains only its owned `output_guardian/v2/`, tests and `infra/guardian/v2/` extensions. Agent4 will own the shared DTO/Registrar/transport glue.

Production Linux distinct UID/network/cgroup/old-publisher credential revocation and room exclusivity, real RTMP/AAC tail and WebRTC required received ranges, true GPU/Worker execution and audience latency remain NOT TESTED/BLOCKED. CPU FFV1/PCM is not those transports. Standalone v2 entry remains exit78/OUTPUT_FENCE_UNPROVEN. No PR11 merge or OUTPUT GUARDIAN PASS this round.

## Next controlled order

Agent2 fixes P0-R13-OUTPUT-DEADLINE first. Agent4 then independently reruns exact revised SQL + migration-set/protection reconciliation + full Go/race/contracts before any normal-history integration. Agent3 can prepare owned real-Authority interop against the revised pin; Agent5 can prepare its owned concrete output adapters and Linux isolation evidence. Agent4 follows with sole SDK adapters, trusted Registrar/Session/Generation/Binding and common entrypoints. Do not reverse the order by enabling routes to make mocks run.

Durable LIVE remains default-off/OUTPUT_FENCE_UNPROVEN. PR8 remains OPEN Draft with no auto-merge; main remains `7fe5d24810e2df348c58dd7748e97ffbe5cff384`. This review merges no production module, modifies no public production source and starts no GPU. **ASTRALIVE V0.5 BLOCKED.**
