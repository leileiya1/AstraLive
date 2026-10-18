# Agent4 PR13 Authority final integration review

**AGENT 4 ACK — PR13 AUTHORITY FINAL INTEGRATION REVIEW** for `7140881c5103e6bc0a33b743f6e726c4b1b7b474`. [Formal ACK](https://github.com/leileiya1/AstraLive/pull/13#issuecomment-6244160740) supersedes the earlier BLOCKED only at this new source pin. Starting integration was `e9698923c6ed367ef31befc1e137811624b9ef20`, on the same original Worktree/branch. No new Agent, Worktree or development branch was created. PR13 base/HEAD and ownership were re-fetched before review and merging.

The merge uses normal non-ff history with PR13 HEAD as a parent, including Agent4's shared migration/protection correction in the same commit. All final source tests were executed on the actual merged Agent4 worktree before commit/push, without overlay, rather than inferred from the candidate. The full merge/integration SHA is published in the PR13 delivery comment; consumer pins refer to that commit, not the floating branch. PR12/11 are not merged in this step.

## Frozen source and protection authority

Frozen SHA `c7fd46209d3cbc6f58541dba8b4e1c85609c823e`; full digest `3c0c317ed00f6fa4d2cf15ef3f61fc002d4bb22bf02d53ee9f1b407458bb28b1`. The task message omitted part of the digest; manifest/22 individual hashes and the original manifest bytes were independently verified. No normative or manifest changes. Sole DTO dependency stays `e3302f6b2bb19e0184cde3a6cbbcaf3ea4371565`; generated SDK and public production hotspots remain unchanged.

The actual migration set is000001–000007 with distinct contiguous versions and exact filenames. Files000001–000006 retain original bytes. The shared legacy-upgrade test now compares the explicit sorted seven filenames in schema_migrations, preserving prior upgrade/data/repeated-Migrate assertions. It does not merely accept any count7. The old six-version failure and preceding protection-hash failure remain in the historical first-review evidence; they are not erased.

Preimage SHA256 of `backend/internal/durableintegration/integration_test.go`: `4319b70c98d9e9f5100f6d9692b1c139eb732bae8c8137581e940e84d93865bd`.

Postimage: `d35857602e3c88c880db91242dae10d30a5b6cc41d5395b594eaa2be78197fa5`.

The user explicitly authorized this test enhancement and exact protection registration. Existing README scopes `protected-files.json` to preserving source during the design PR; that inventory/README are outside the22 normative manifest. No rule prohibits this authorized implementation-stage update. Exactly **one of313 expected hashes** is changed, with `authorizedImplementationChanges` pointing to the [audit record](protection-changes/PR13-MIGRATION-TEST.json). Original inventory/test bytes, exact postimage, prior diff and approval quotes are retained. The other312 entries remain unchanged. Validator source and per-file check logic remain unchanged; nothing is disabled/skipped or broadly refreshed. Deliberately mutating either the new test postimage or an unrelated protected Runtime file still causes validator rejection, and restoring bytes returns PASS. The inventory README now documents this single audited adjustment.

## Independent safety re-review

The original Agent4 A/B/C source was matched byte-for-byte against the newly included test file, then independently executed on new loopback PostgreSQL17.11 with fsync, synchronous_commit and full_page_writes on. A rejects expired Consume and the extra check verifies rollback of consumption/execution while Grant remains ISSUED; B bounds current Authority validUntil/remainingProofMs after shortening; C bounds newly issued Permit. All three pass unchanged.

Source review confirms real `expires_at` is read under the existing Run/output locks, retained in state.limit, and intersected with lease/Binding/command/answer/current Permit/Observation. New Grant bounds follow that intersection. Final response validation precedes a new DB-time check and relative-budget computation; first true issuance/Consume keeps the100ms margin. Existing consumed Grant/initial proof deadlines remain immutable audit references rather than truncating fresh ongoing same-binding proof.

Additional real-SQL race cases pass: exact DB equality rejects; expiry during response preparation rolls back; shortening committed before a waiting call is observed; a later output writer cannot cross the held shared lock before Commit; concurrent Consume/revoke preserves a unique latch; ACK loss/UNKNOWN/Stop/old identity never regain execution; Unit2 uses its own Grant/execution after trusted Drain; continuous proof refresh crosses both original Grant and initial fact metadata deadlines without another START.

Locks serialize authority/source writers, **not wall time or network delivery**. Commit/WAL/network can take time after the final clock read. Receiver must retain original pre-RPC monotonic/suspend anchors, subtract elapsed time, enforce current validUntil/timing, apply Stop/barrier/lineage at final ACK/media edges and reject late/ambiguous responses. A committed latch is retained on ACK loss; it must not be rolled back/reissued to recover speech.

An actual SQL Query snapshot and consumption record were validated through the official Python DTO and replayed through PR11's real Gate/Budget. Current proof293ms was shorter than the immutable Permit expiry; after the current budget elapsed the final gate rejected, and replay against the original sent anchor also rejected. This is a serialized-document/gate replay with relative time deliberately replayed; it is **not live authenticated IPC, real Receiver assembly or production media proof**. The replay harness's two initial SDK API misuse errors are preserved and corrected without changing SDK/Authority code.

## Actual results

Candidate and final production/shared source hashes match. Both phases ran separately on newly owned services; source snapshots were plain git archives, not worktrees. Additional Agent4 private-fixture probes were run physically in the temporary candidate only and removed afterward; no overlays were used. Final full regressions run the committed module test suite on the actual worktree.

| Gate | Candidate | Final merged worktree |
| --- | --- | --- |
| Original A/B/C |3 PASS |3 PASS |
| Authority PostgreSQL race |47 PASS /1 owned helper SKIP |47 PASS /1 owned helper SKIP |
| Full Go test -count=1 |189 top-level PASS /0 FAIL /12 SKIP |189 top-level PASS /0 FAIL /12 SKIP |
| Full Go race -count=1 |189 top-level PASS /0 FAIL /12 SKIP |189 top-level PASS /0 FAIL /12 SKIP |
| Go vet |PASS |PASS |
| Retained contracts |137 PASS |137 PASS |
| Runtime Journal |11 PASS |11 PASS |
| Official cross-language wire |13 PASS |13 PASS |
| Both validators / generator check |PASS |PASS |
| Extra independent rollback/budget/SQL snapshot probes |3 PASS |Same tested source hashes; not added to permanent module tests |
| Unauthorized protected-file mutations |Both rejected; restored validator PASS |All313 expected hashes independently checked |

[Summary and full skip reasons](../evidence/agent-4/pr13-final-2026-10-18/summary.json), separate candidate/final raw commands/logs, PostgreSQL settings, owned-service cleanup, pre/post source manifests and CPU child-resource records are retained.12 Go skips cover optional browser/provider/formal/userconfig/event/export fixtures, helper entrypoints exercised by their parent tests, and fixed-port whole PostgreSQL/Redis outage opt-ins. Dedicated Redis stream/reclaim ran; whole-server outages did not. CPU deltas/cumulative Darwin child peak RSS are not a production performance benchmark. Only owned new services/child processes were stopped; data/logs retained.

## Consumer handoff and remaining gates

Agent3 may now begin real PostgreSQL Authority integration tests using this exact integration merge SHA: sole Go wire + authority.Store/Handle, trusted fixture Actor/source/assertion/Observer boundaries, ProductProjection→Rule/Facts mapping, Prepare CAS/receipt, single global START, Unit2 Continuation, Drain/Seal/CONTROL completion and ACK loss/Stop/UNKNOWN. Keep all modifications in Agent3-owned answerstream test/adapter files and its existing worktree. This enables domain SQL interoperability work, not actual Runtime speech or a merged PR12 claim.

Agent5 must consume current Authority validUntil/timing with pre-RPC anchors and immutable execution identity through the sole Python SDK adapter. Real restricted Authority transport, trusted Registrar/process/install/Session/Generation/Binding and Runtime once-TTS/public entrypoint wiring remain Agent4 composition work. No new auth protocol or copied Schema is authorized. PR11 real Linux/old-publisher exclusivity and RTMP/WebRTC required-sink proof remain blocked.

Production Registrar/fact extraction/Observer, actual authenticated HTTP/IPC, physical Guardian/credential and old-output isolation, real Runtime/TTS/GPU/Publisher/Decoder/Sink/Chrome/RTMP/WebRTC/audience, host recovery and whole-server outage remain NOT TESTED/BLOCKED. Authority ACK does not approve those layers. Durable LIVE remains default-off/OUTPUT_FENCE_UNPROVEN, PR8 stays Draft without auto-merge, main stays `7fe5d24810e2df348c58dd7748e97ffbe5cff384`. No main/PR8 merge, LIVE or GPU startup. **ASTRALIVE V0.5 BLOCKED.**
