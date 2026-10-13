-- Worker wire generation is a positive signed BIGINT, distinct from business
-- run/timeline/generation IDs bounded by 2^53-1. Preserve numeric JSON and 000007.
-- PostgreSQL BIGINT itself rejects 2^63 and larger; do not downcast or rewrite IDs.
ALTER TABLE v05_segment_attempts ADD CONSTRAINT v05_worker_wire_generation_positive
 CHECK(worker_generation_id IS NULL OR worker_generation_id > 0);
ALTER TABLE v05_segment_attempts ADD CONSTRAINT v05_worker_incarnation_nonempty
 CHECK(worker_epoch IS NULL OR worker_epoch <> '');
