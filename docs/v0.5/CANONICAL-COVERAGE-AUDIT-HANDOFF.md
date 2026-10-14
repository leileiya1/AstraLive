# Canonical CNY coverage audit handoff

Owner: F acceptance; implementation author: delegated B.
Source pin: `7d10c314aa690caf8325815139d7b8be05a1fcff`.
Branch: `exp/v0.5-canonical-coverage-audit`.
Base: F `394749e16028b56a244e6bded005f0d3d4ec8b57`.
Module SHA256: `d0c2f07bc1e697b7ca2b017c3250585895f913f34040fdd6372139ee78c7ed1a`.

Only new independent acceptance code and synthetic rejection tests were added.
No production, frozen contract, Go, Runtime, GPU Worker, media sinks, or existing
`real_golden_audit.py` files changed. F owns the final normal merge, safe SQL
projection, and main oracle integration. No SSH or GPU operations occurred.

## API and actual evidence inputs

```python
validated_cny_price_coverage(
    narration_row, turn_rows, commit_rows, observation_rows,
    receipt_rows, answer_prepared_commands,
    product_snapshot=product_snapshot,
) -> {target_segment_id: [turn_id]}
```

Module: `integration/v0.5/canonical_coverage_audit.py`.
Failure: `CoverageAuditError(code, status='FAIL')`, safe codes without raw records.

- `narration_row`: actual SQL narration row with `session_id`, `narration_id`,
  `run_epoch`, `tenant_id`, `user_id`, `plan_json`, `document_json`. Private policy
  comes only from `plan_json._cnyPriceCoveragePolicy`; current segment statuses
  come from `document_json.plan`.
- `turn_rows`: actual SQL turns with those owner/session/narration columns and
  `turn_id`, `state`, `document_json._cnyPriceCoverageDecision` plus actual public
  turn/answer projections. Turn SQL rows have no invented `run_epoch` column.
- `commit_rows`: actual SQL Timeline commits, identity/descriptor, installed and
  completed timestamps, completion hash, required sinks and actual sink receipts.
- `observation_rows`: existing safe SQL observation keys plus `tenant_id`,
  `user_id`; only `ANSWER_PREPARED` needs `preparedProof`, exact keys `text`,
  `factIds`, `productSnapshotHash`. Actual ACK fields remain `response_json`.
- `receipt_rows`: actual SQL journal receipts with owner/session/run,
  `command_id`, `receipt_seq`, `producer_incarnation`, `state`, `evidence_type`,
  `evidence_ref`, `observation_hash`. Bind `ANSWER_PREPARED`, `COMMIT_INSTALLED`,
  `SEGMENT_COMPLETED` separately to their actual ACKs; no need to export payload.
- `answer_prepared_commands`: safe original `START_AUDIENCE_ANSWER` projection:
  `commandId`, `sessionId`, `runEpoch`, `traceId`, `commandType`, `narrationId`,
  `tenantId`, `userId`, `interactionTurnId`, `answerText`, `factIds`,
  `productSnapshotHash`. No token, lease profile or full command payload.
- `product_snapshot`: exactly seven **string** keys `productId`, `name`,
  `description`, `price`, `currency`, `stock`, `sizes`, represented like Go's
  `Controller.product`. Recompute sorted UTF-8 JSON SHA256 like Go
  `durability.Hash`, preserving Unicode/HTML. The final safe SQL projection is
  only evidence if its recomputed hash equals the immutable captured version;
  changed final values fail. It proves no product switch history.

F must select the exact matching narration and scoped snapshot before calling.
The function checks owner, run, narration/turn/answer/target bindings and excludes
duplicate target mappings; it does not replace the full media 17-tuple oracle.

## Evidence rule

Accept only the privately recorded revision `canonical-cny-price-1`, one authored
singleton `price` NARRATION target, CNY captured snapshot and these exact templates:

1. `本商品当前标价是人民币{{price}}元。` / `price-subject-1`
2. `这款目前价格是人民币{{price}}元。` / `price-answer-wording-1`

No whitespace, added claims, text similarity, generic fact labels or custom
template revisions grant coverage. The target text and SHA must match immutable
and current plan projections. The deterministic answer must exactly equal
`这款目前价格是人民币` + captured price + `元。`, with singleton fact mapping.

A decision must be FULFILLED, have the same recorded policy and captured product,
and reference the real prepared command, safe proof, observation and receipt.
The actual answer must be COMPLETED with every required sink's exact audio and
video interval and final markers. Installation and completion ACKs must be
durable, match receipts/hash/producer and advance the **same command's** receipt
sequence. Prepared and media commands have separate sequence domains; the oracle
does not compare their local receipt sequence numbers as a global ordering.

The recorded completion command/hash and checkpoint must match actual SQL
identity, attempt, start/final positions, PTS arithmetic, all sink ranges and
answer text/version. Applied target IDs must be unique and SATISFIED_BY_ANSWER;
a target cannot also have a committed narration media segment. Empty applied
targets grant no coverage. Old plans without private policy return `{}` and gain
no inferred canonical coverage; orphan private decisions are rejected.

The original authenticated TimelineHash cannot be recomputed from intentionally
limited safe projections. Its recorded hash must instead match the actual SQL
observation, receipt and decision/commit. This is database evidence consistency,
not cryptographic database authenticity or hardware attestation.

## Validation and limits

Run from the B branch:

```sh
/private/tmp/astralive-b-staging-venv/bin/python -m unittest discover \
  -s integration/v0.5/tests -p test_canonical_coverage_audit.py -v
/private/tmp/astralive-b-staging-venv/bin/python -m unittest discover \
  -s integration/v0.5/tests -p 'test_*audit.py' -v
```

31 new synthetic oracle tests PASS. All existing 27 fact/domain/numerical oracle
tests remain and PASS; total 58. Rejection tests cover noncanonical resigned
claims, generic/multiple facts, old/missing policy, unfulfilled/UNKNOWN/partial
proofs, missing/duplicate audio/video receipts, changed final product version,
foreign owner/run/turn, forged private hash, receipt hash/producer/sequence
mismatch, mismatched completion/checkpoint, nonfinite price, Boolean IDs, missing
safe projection, duplicate mapping across two distinct complete turns, duplicate
targets, and target already committed. Explicit canonical byte representation
tests Unicode/HTML and key order; execution of a new Go/Python cross-language
snapshot vector is left to F's actual SQL/Go projection gate.

PostgreSQL projection integration, actual new canonical business live playback,
GPU, Chrome, RTMP, ten-minute Golden and human naturalness: **NOT TESTED here**.
F will wire the validated map into `selected_turns` as an optional proof input,
preserving the old substring path for old plans without this policy. Metadata
coverage PASS alone must never be reported as natural continuation or audible
speech PASS.

Rollback: remove the two new oracle files and this handoff or revert the source
commit. There are no production side effects, feature flag changes or migrations.
