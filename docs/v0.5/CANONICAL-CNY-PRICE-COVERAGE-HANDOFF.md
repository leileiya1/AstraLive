# Canonical CNY price answer coverage

Production source: `df213ca4074dfb8d9b962f19d3e1d252bc5764f3`. Test-only extension: `54e4e79be947b77312f768e388e9bd7e8c39583d`. C owns narration Controller/model/private policy and its tests. A independently reviews authority/hash/transaction compatibility; F owns final merge, fixed fixture and real Golden decision. Public DTOs, frozen contracts/helpers, A migrations/journal, media and provider algorithms are unchanged.

The real tcp-9 price answer completed but the subsequent narration repeated price because its equivalent wording was not an exact substring. The fix gives a narrow, auditable additional permission to newly authored plans captured with staging enabled and CNY currency. Before substitution, a statement must have exactly `factIds=[price]` and be one of these complete original templates:

- `本商品当前标价是人民币{{price}}元。` (`price-subject-1`)
- `这款目前价格是人民币{{price}}元。` (`price-answer-wording-1`)

There is no whitespace normalization, number parsing, currency conversion, regex subject matching or LLM semantic coverage. Extra clauses, qualifications, category claims, custom facts and multiple facts do not receive this permission. Raw SQL decimal spelling is preserved. The historical electronic-manual category sentence is excluded; F's next fixture must be separately versioned and TTS-measured before real testing. Historical failed evidence remains intact.

Start inserts a reserved `_cnyPriceCoveragePolicy` in immutable `v05_narrations.plan_json`. It binds policy revision `canonical-cny-price-1`, captured Session/run/narration/product/hash/version and exact target segment/TextHash/template revision. It is not a public typed Plan/Document field. Existing plans with no private policy retain the original substring behavior and are never upgraded on load/restart.

After the original fresh deterministic ANSWER_PREPARED validation, the same business transaction stores a private `_cnyPriceCoverageDecision` in the existing Turn JSON. It binds the original preparation command, actual A receipt observation hash, answer segment/TextHash, same captured product version and target policy. Ordinary saves preserve only this reserved key. Public Turn fields are unchanged.

Only actual A SEGMENT_COMPLETED projection, full required sink proof, a fresh SQL product check, matching captured staging and matching immutable decision may mark the exact PENDING singleton-price target SATISFIED_BY_ANSWER. Cursor and Resume target use the existing state transitions. The same transaction records FULFILLED with actual A `v05_timeline_commits.completion_hash` (the original canonical TimelineHash), checkpoint identity/evidence and applied targets. Receipt/decision/cursor rollback together; duplicates return the original A ACK and do not reapply. A different fact, amount/currency/version, Stop, UNKNOWN, stale identity, partial media or conflicting private decision cannot authorize a skip.

Validation:

- Production immutable full module gate PASS: Go tests/race/PostgreSQL migrations, authentication/ownership/outage and existing interactions/compatibility, Runtime 273 tests (12 skips), frontend 40 tests/build.
- Latest test pin: 21 actual owned PostgreSQL/race scenarios PASS, including different pure wording, actual A prepared/final hashes, duplicate ACK, rollback, Controller reload, subsequent Stop metadata preservation, immutable-policy rejection, flags-off, USD, custom/extra/category/multi claims, exact legacy plan without policy, partial, UNKNOWN, stale epoch, product changes and Stop.
- Private model/provenance policy tests PASS. No old regression was removed. Pre-pin fixture failures are preserved and labeled in the manifest.

The PG tests use real production Accept/StartAttempt/StartMedia/RecordTimeline transactions, while the earlier semantic boundary and sink receipt content are explicit controlled fixtures. They are not real Runtime physical cleanup, GPU, browser speech or audience playback acceptance. Natural continuity, actual no-repeat Golden, AV/SLA, Linux/Windows and default enablement remain NOT TESTED by C at this pin.

Evidence: `evidence/agent-c/canonical-cny-price/manifest.json` and logs. Reproduce the full gate with `integration/v0.5/module_gate.py --source df213ca4074dfb8d9b962f19d3e1d252bc5764f3` and the recorded owned PG/media Python arguments. Reproduce the test extension against a private PostgreSQL database using `go -C backend test -race ./internal/narration -run 'TestCanonical|TestPostgresCanonicalCNYPrice' -v -count=1`. Never point this fixture at a shared or production database.

Rollback: revert this narrowly scoped Controller/model/private-helper change to retain legacy conservative substring coverage. Preserve stored private JSON and existing SATISFIED_BY_ANSWER ledger; do not rewrite immutable plans, receipts or replay speech to manufacture a rollback result. A plan/Turn lacking this policy continues along the old route. All original experimental defaults remain off.
