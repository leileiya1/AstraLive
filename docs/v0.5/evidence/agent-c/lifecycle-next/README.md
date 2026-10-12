# C post-integration lifecycle gate

Final implementation source: **b028f5aeec0b929a9779f5f50def8cebce25c98a**.
Preceding guard565993e and configuration helper43a4140 are retained in history.
C normally merged F48eb038 at99d8d72 before these changes. No main merge,
frozen contract change, default enablement or cloud/GPU operation occurred.

| Gate | Result | Evidence |
| --- | --- | --- |
| Same lifecycle fault oracle on immutable F48eb038 + test-only overlay | Expected FAIL, exit1, two failures | pinned-before-result.json and pinned-before.log |
| Immutable guard565993e archive module gate | PASS | gate-565993e/result.json |
| Immutable finalb028f5a archive module gate | PASS | gate-b028f5a/result.json |
| Final native-cleanup/release guard plus retained binding regressions | PASS,18 tests | retained-session.log |
| Final Runtime archive suite | PASS,212 tests,11 skipped | gate-b028f5a/runtime.log |
| Final frontend tests/build | PASS,40 tests/build exit0 | gate-b028f5a/frontend-test.log and frontend-build.log |

The module gate executes full Go and Go race suites with an owned real
PostgreSQL cluster, additive migrations, ownership/authentication, ordinary
interaction regressions, actual PostgreSQL outage, twelve durability Python
tests, frozen v1.1 validator, full Runtime discovery and frontend tests/build.
It archives the exact Git source, isolates process environment and owns cleanup.
The result JSON records commands, tool versions, log hashes and exit codes.
The manifest records final source hashes and raw artifact hashes.

`TestPostgresCapturedRetirementNativeCleanupAndFreshSession` runs actual Go
Narration/App/JournalRouter/Binding DELETE and SQL Release with a Python child
using production NarrationCommands, SegmentExecutor, B MediaTimeline and
BoundSessionManager. Separate changed-price and changed-product cases finalize
the old Session/run/Narration and admit a fresh SQL-captured fixture Session/plan
with no inherited completion cursor. The native-cleanup-failure case preserves
STARTED/UNKNOWN, Stop tombstone and Worker reservation and forbids reuse.

Binding DELETE and control receipt deliberately wait while SQL events are
processed, reproducing production event ordering. Neither an early ENDED event
nor SQL STOPPING can finalize before both control proof and release exist.
Private HTTP authentication uses independent temporary fixture token roles.
Captured binding GET packets and providers/native outputs are explicit doubles;
this is not production encrypted-provider resolution or actual GPU/media Stop.

A independently ACKed the565993e SQL/event seam on its own immutable archive and
owned PostgreSQL/race gate, in A evidence commit578037e. F acceptance remains
independent. Follow-upb028 only retains the same Session context through LLM
close/release ACK before removing the Runtime map entry.

Reproduce the final archive gate from repository root:

```sh
python integration/v0.5/module_gate.py --repo . \
  --source b028f5aeec0b929a9779f5f50def8cebce25c98a \
  --output /private/tmp/astralive-c-lifecycle-review-NEW \
  --python /Users/sapiece/innovationProject/AstraLive/runtime/.venv/bin/python \
  --pg-bin /opt/homebrew/opt/postgresql@17/bin \
  --frontend-modules /Users/sapiece/innovationProject/AstraLive/frontend/node_modules
```

Earlier moving-tree pg-full.log also runs the existing narration HTTP/crash
fixtures via NARRATION_TEST_PYTHON. Its two setup failures are retained separately:
the new child initially omitted repository root from PYTHONPATH, causing the
private token helper import to fail before execution. They are fixture setup
failures, not native lifecycle results. runtime-with-duplicate-fixtures.log and
after.log predate correction of an imported-TestCase discovery duplication;
use the final212/18 counts above. before.log is the initial moving-tree negative
diagnostic; the immutable pinned-before files replace it as the reproducible
negative oracle. Raw logs were not trimmed to make gates pass.

Remaining P1: failed STARTED control finalization retry, cross-restart old-sink
cleanup proof, operator UNKNOWN mutation/audit and thirty-event-retry exhaustion.
See [recovery proposal](../../../NARRATION-RECOVERY-PROPOSAL.md). Native Chrome,
RTMP, SoulX, real LLM/TTS, human naturalness and busy SLA were NOT TESTED for these
lifecycle commits; earlier native long evidence is not assigned to this source.
