# D focused source review 2026-10-14

Exact source 8fa0eb27b132234be9bd2afcccfeb8980ad4ca7a. Sanitized environment, immutable git archives, owned temporary PostgreSQL, existing actual Python subprocess tests. No repository source modifications, SSH, cloud GPU or shared service access.

Go race config/runtime/userconfig, actual Backend TCP/UDS PG-only public Start/Speak/Stop/idempotency/Backend SIGKILL restart plus original A startup, and existing feature flag tests all pass. Python corrected selection:47 tests/1 skipped passes. Go browser opt-in and root-only foreign UID checks remain skips, not waived.

run-1 preserves Python3.9 orchestration tarfile setup failure before PG/tests. run-2 preserves Go PASS plus Python fixture-import invocation error. run-3 adds runtime/tests to PYTHONPATH and uses matching standalone unittest names on unchanged source; pass. No code/test removed or assertion masked. Aggregate is software scope across independent checks; no continuous live session or performance claim.

result.json includes all check commands, raw hashes, source hashes for final-pin dependency mapping, versions and NOT TESTED platforms/media scopes. Runner sources are provided for inspection; their fixed output paths must be changed for a fresh reproduction because outputs refuse overwrite.
