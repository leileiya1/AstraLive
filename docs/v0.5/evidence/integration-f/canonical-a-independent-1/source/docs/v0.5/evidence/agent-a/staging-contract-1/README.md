# staging-contract-1 review candidate evidence

This pin publishes exact DTOs, canonical/hash projections and pure lease/proof validation helpers; it does not implement production staging. F must freeze after B/C scoped review. Base d691664, source file SHA256 and raw artifact hashes are in manifest.json.

Commands actually run:

- `python3 -m unittest gpu_worker.tests.test_staging_contract -v`: 15 tests PASS; schema equality, five hash vectors, strict shape/float/duplicate/integer rejection, resource null discrimination, integrity, installed-reference requirement, all-required pose proof, reduced-ratio rejection, precommit null/UNKNOWN release, capture/negotiation gate and explicit renewal accounting.
- `go -C backend test ./internal/durability -run '^TestStagingCanonicalGoldenVectors$' -count=1 -v`: actual Go full-object canonical bytes and hashes match the five Python domain vectors.
- With an independently provisioned owned PostgreSQL17 cluster and DURABILITY_TEST_DATABASE_URL: `go -C backend test -race ./internal/durability -run '^(TestStaging.*|TestContinuityProofAndCursorAtomic)$' -count=1 -v`: installed ACK observationHash equals authoritative stored TimelineHash and response_json, producerIncarnation equals verified producer, duplicate ACK stable; legacy int63 worker proofs at maxsafe/maxsafe+1/maxint63 unchanged. Cluster stopped/removed after command.

Minimal shared A change is existing RecordTimeline ACK construction only: observationHash and producerIncarnation are additive, existing keys/states/transaction/DDL unchanged. Older stored ACKs missing these fields remain legacy-compatible and fail staging arming closed. Scope/reason authorized by F before edit. Original frozen ARCHITECTURE-CONTRACTS bytes unchanged.

Real GPU/native safe-boundary/pose history, production Runtime orchestration, eight-second profile, live renewal, real Chrome/RTMP/providers, human naturalness and SLA are NOT TESTED here. Keep default flags OFF.
