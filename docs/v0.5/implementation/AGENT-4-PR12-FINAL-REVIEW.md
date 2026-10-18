# Agent4 PR12 Streaming PostgreSQL integration review

**AGENT 4 ACK — PR12 STREAMING POSTGRESQL INTEGRATION** for full HEAD `c0f36e1bf1f060286eedd733cd222cfa6c7941f3`. [Formal ACK](https://github.com/leileiya1/AstraLive/pull/12#issuecomment-6246590751). Review starts at integration `235258ad75f7d271a279ea89fd88ddf80e797f31`, with Authority `a4a57fcc0effd5dd5ea9689b355a963b007c20f3` and sole DTO `e3302f6b2bb19e0184cde3a6cbbcaf3ea4371565`. Original Agent4 worktree and integration branch retained; no new Agent, worktree or development branch. No overlays, reset, clean, stash or force push.

## Scope and source audit

PR12 was independently fetched and read, including full handoff/report, real SQL projection adapter, official-wire Authority adapter, domain modules and all PostgreSQL fixtures/tests. HEAD/base were re-read immediately before integration: correct base, mergeable/clean, no hosted check runs or status contexts. Draft was converted to Ready only after ACK. A plain git archive supplied the isolated candidate; it is not a registered worktree. Agent3 additions stay in its two answerstream directories and handoff/evidence documents. Existing Scheduler, fairness/TTL/FORCE, v1 domain and all shared production entrypoints remain unchanged. No v2 production route is registered.

The22 normative files and manifest are byte-identical to frozen `c7fd46209d3cbc6f58541dba8b4e1c85609c823e`; independently recomputed digest `3c0c317ed00f6fa4d2cf15ef3f61fc002d4bb22bf02d53ee9f1b407458bb28b1`. All1619 unchanged base files match, including313 protected hashes/inventory, official DTO/generator, Authority tree `e15385d5f983ab47d226b160a9c218f34d30752e`, all seven migration files and000001–000006 preimages. No new protection exception. [Source audit](../evidence/agent-4/pr12-final-2026-10-18/candidate/source-audit.json) retains per-file hashes and exact names. Durable LIVE remains default-off and true admission still rejects OUTPUT_FENCE_UNPROVEN.

## Independent safety conclusions

- One COMMENT identity spans Turn/Attempt/Utterance/Generation, with one global START. Unit2 receives a distinct Artifact/Grant/execution/latch using Continuation after trusted Unit1 Drain. Prepare-before-Drain and Drain-before-late-Prepare both work. Normal Unit Finish never writes Run Stop. No COMMENT operation advances a SCRIPT Segment cursor.
- First complete trusted semantic unit prepares/starts before provider EOF. The pull-based closed-language scanner rejects unsafe incomplete prices, sizes, negation, comparison and conditions. Unknown assertions are not repaired from LLM claims. Rule vocabulary is deliberately narrow: only trusted current SQL facts and explicit supported templates. No free-form LLM semantic verification or SLA is claimed.
- AuthorityFacts first obtains an authorized Store.ProductProjection for the exact command/product/snapshot. Literal price/currency/stock reads must hash identically to that projection. Source updates between the two reads reject; subsequent Authority transactions independently revalidate current facts/version under locks. Full actual text, textHash/artifactHash and every dependency/assertion must match. Deleted PRICE or rehashed forged value/version/snapshot does not bypass review. Runtime gets no DB credentials.
- Verify is scoped to the bound command and actor. A different command fails closed. Production shared Store requires Agent4's authenticated command dispatcher; it must not install a last-Session-wins callback. Supplementary tests exercise two commands/tenants with both denial and explicit trusted routing; that dispatcher is a test, not delivered production wiring.
- Official DTO metadata/roles/paths/encode are used for every mutation through actual Authority Store.Handle. Scoped SQL revision reads are not replacement state mutations. Prepare CAS retries are bounded and reuse immutable Artifact/key; duplicates/aliases/original receipts never mint execution. START/Continuation ambiguity and consumed-ACK loss retain UNKNOWN and the original durable latch; tickets are not replayed. Expiry, Stop, epoch/Generation/Binding/product changes deny late authorization.
- Original grant issuance limits are distinguished from ongoing same-execution proof renewal. The current output deadline bounds authority even when older Permit/Grant expiry is later. Future Receiver must subtract elapsed time from the original pre-RPC anchor and apply a fresh final gate; domain SQL success does not replace that check.
- Seal, every required trusted unit drain, aggregate LOCAL_MEDIA_DRAINED and independent CONTROL COMPLETED gate Slot release. Missing any of these leaves it held. One active plus one lookahead,32 units, bounded scanner/token buffers and cancellable Provider backpressure are retained. The source adapter must honor context and nonblocking Close. Domain Stop alone is not Backend Stop or a physical fence; outer orchestration must do all three.

## Actual independent evidence

[Summary with every SKIP/reason](../evidence/agent-4/pr12-final-2026-10-18/summary.json). Raw command arrays/exit codes, JSONL, PostgreSQL inventory, migration rows, original logs, CPU deltas/cumulative Darwin child peak RSS and cleanup are retained separately. Gzip only preserves whitespace of initdb/psql tables; it is lossless. Resources are not a production benchmark.

Candidate command: `python3 backend/internal/turnmanager/answerstream/run_postgres_interop.py --full --output /tmp/agent4-pr12-review`, on the exact PR archive. New loopback PostgreSQL17.11 with fsync/synchronous_commit/full_page_writes on, three new owned databases and seven actual migrations. All dropped and the owned server stopped; shared/production services untouched.

| Gate | Exact PR candidate |
| --- | --- |
| Streaming real PostgreSQL race |18 PASS /0 FAIL /0 SKIP |
| Complete Go test -count=1 |229 top-level PASS /0 FAIL /13 SKIP |
| Complete Go race -count=1 |229 top-level PASS /0 FAIL /13 SKIP |
| Go vet |PASS |
| Frozen/v1/v2/Receiver/Stop contracts |137 PASS |
| Runtime Journal |11 PASS |
| Official cross-language wire |13 PASS |
| Both validators / generator --check |PASS |
| Migration set |Exactly000001–000007 |

The13 Go skips are retained verbatim: Redis stream/outage opt-ins, isolated outage/helper entrypoints, browser/provider/userconfig/event/export fixtures and app diagnostic opt-in. They are not PASS. Real streaming/Authority tests ran with owned DB URLs; the full runner does not configure the optional Redis or unrelated browser/service test harnesses.

Independent supplementary run on a second newly owned server: **25 top-level PostgreSQL race PASS /0 FAIL /0 SKIP**, comprising original18 plus7 Agent4 probes. [Exact additional source](../evidence/agent-4/pr12-final-2026-10-18/agent4_review_test.go.txt) was physically added only to the temporary candidate, run without an overlay, then removed. Agent3 production/test code remains unchanged. Added tests cover scoped facts/command dispatcher, price/stock read race, expired Binding before Unit2, fully rehashed text/dependency/version/snapshot mutations, actual32-unit completion/33rd refusal, blocked Provider cancellation, concurrent Consume at most one latch. All source/logs and no failures are retained; sample counts are not added to the full-suite total.

The normal integration commit preserves PR12 HEAD as a parent. Its exact SHA and subsequent committed-source regression are published in the delivery comment and follow-up audit; the merge commit records candidate evidence only. Candidate results are not represented as post-merge results.

## Production boundary and next handoff

Registrar/physical installation, Receiver/Guardian ACK and Observer/required Sink evidence in SQL tests are explicit synthetic fixtures. Real PostgreSQL is verified; production authenticated IPC, Guardian fsync/Runtime once-TTS assembly, TTS, physical Publisher/Decoder/Sink, GPU, RTMP/WebRTC/Chrome/audience and first-sentence P50/P95 remain NOT TESTED/BLOCKED. No false physical drain or production claim is inferred. No new P0/P1 issue blocks this isolated default-off module integration.

PR11 `d8eb05e79661b859547242575e0ac6d1d7303aa1` remains Draft/unmerged this round. Its handoff/ports/acceptance were read; [next wiring dependencies](AGENT-4-GUARDIAN-WIRING-PLAN.md) assign shared assembly to Agent4 and physical adapter/isolation work to Agent5. No additional protocol is authorized. Keep PR8 Draft and main unchanged. No LIVE, GPU or real push-stream test. **ASTRALIVE V0.5 BLOCKED.**
