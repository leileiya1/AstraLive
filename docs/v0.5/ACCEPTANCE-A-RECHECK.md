# A acceptance recheck — 2026-10-15

**Scoped software PASS; experimental defaults remain off.** Reviewed and tested
source is `aab062f024fa28202a7255179c5089c1dc9bdbbd`, isolated worktree
`/private/tmp/astralive-v05-acceptance-a-20261015-1`, branch
`review/v0.5-acceptance-a`. No production bug was reproduced in this scope;
this delivery changes only this report and A-owned review evidence. It changes
no core code, migration, frozen contract, default, timeout or oracle criterion.
It does not push or merge main. F owns integration and subsequent real runs.

The fixed source includes C's constructor-only production repair
`ee22e1e9f1c1dbc58c7505e3cd5a238d979f9aaa`: new bridge creation sets
`FactIDs: []string{}` before its first persistence/command construction. Save,
read, historical rows and SQL immutable guards remain unchanged. This is a
correction to the existing empty-fact-list representation, not a new receipt,
identity or completion semantic; no CCR or DDL change is needed. A gives a
scoped source/persistence ACK for that repair as included in the reviewed pin.

## Tests actually rerun

The reproduction script archives the pinned backend/Runtime/Worker/contracts
sources, starts its own PostgreSQL 17 on a disposable loopback port, and runs
five **focused** Go commands with `-race -count=1`. These are existing tests;
no C test or core source is modified. All **19 top-level tests and 5 subtests
passed, with zero skips**. Owned PostgreSQL final stop exited **0**. No cloud,
SSH, real LLM/TTS provider, native GPU, browser or external service was used.
The subprocess credentials are synthetic, generated within the existing tests;
no private credential files or ambient provider environment were consumed.

| Gate | Actual evidence and limit | Result |
| --- | --- | --- |
| Durable identity, attempts, ACK loss, two dispatchers, Stop/recovery/epoch/barrier races | 13 focused top-level tests; PostgreSQL with injected HTTP/Runtime fixtures, conservative UNKNOWN, no second execution of STARTED | PASS |
| Duplicate/conflicting/reordered events | Actual A event ingestion and Go projection keep terminal state; conflicting envelope rejected | PASS |
| Redis-off Backend restart | Actual `cmd/server` process SIGKILL/restart, same CPU Runtime, public idempotency stable, one logical utterance/sequence, Stop ENDED and event spool flushed; invalid Redis URL/no Redis client | PASS in CPU process scope |
| Redis-off Runtime restart | Actual CPU Runtime SIGKILL/restart; STARTED becomes UNKNOWN and replay of same command creates no additional synthetic sink writes | PASS in CPU process scope |
| New bridge empty facts | Real Go/A/PostgreSQL plus child production Runtime READY code with **controlled boundary, TTS/avatar/sinks/journal**; document/SQL/COMMIT/READY all `[]`, exact duplicates/reload stable | PASS in software proof scope |
| Historical bridge null / nonempty facts | Historical JSON `null` stays `null`; narration `name` and answer `price` remain nonempty and unchanged | PASS |
| Strict failed-create Stop | Actual Go journal/Binding DELETE and CPU Runtime: known prephysical proof yields ENDED/SEALED/control receipt; injected DELETE503 leaves STOPPING without completed/ENDED | PASS in controlled provider scope |
| Authorization | Public owner/foreign-user/room/anonymous/Origin controls, pinned binding/product checks; cleanup does not authorize ordinary released-binding execution | PASS in local HTTP/SQL scope |
| PostgreSQL outage | Owned PostgreSQL fast stop rejects admission, restart restores stable idempotent acceptance; sequential with all other tests | PASS in local journal scope |

Exact commands, exit codes, durations, file hashes and unabridged logs are in
[the evidence manifest](evidence/acceptance-a-recheck/manifest.json),
[result](evidence/acceptance-a-recheck/result.json) and
[test counts](evidence/acceptance-a-recheck/test-counts.json). This run does not
repeat F's complete `module_gate` or broaden the list to frontend/all Runtime.

## Stop, authority and UNKNOWN review

Current A command acceptance derives both Session and Room ownership plus the
captured binding, then checks current run/lease/barrier and exact immutable
command. STOP alone uses the existing cleanup authority path that permits a
released binding; ordinary commands, lease renewal and automatic resume do not.
The completed control receipt must match the original STARTED executor
incarnation and current run. There is no generic absence-to-completion rule.
The existing prephysical marker is not a cross-restart physical cleanup proof.

Stop's `sealed_at` timestamp may be written while status is still STOPPING.
Acceptance must require actual Session **ENDED**, run **SEALED**, binding
released and durable control cleanup evidence together, rather than treating
that timestamp or HTTP202 as completion. Session cleanup does not complete an
uncertain speech tail, move the semantic cursor, or authorize another Worker
generation. Lost cleanup ACK/old incarnation still requires explicit evidence
reconciliation; the tests do not introduce a general STARTED control retry API.

A also ran 13 read-only consistency checks against the repository-retained
**historical source8f** short-stop component. Its actual SQL has one ENDED
Session, a SEALED matching run, released binding, STOPPED narration/sticky
barrier, positive control cleanup evidence, six completed commits and one
UNKNOWN tail with no completion hash. The UNKNOWN segment is absent from the
semantic completed-segment cursor. This is historical metadata consistency,
not a new run on aab062f or proof of future live no-replay behavior.

The same check **requires** the old completed bridge's `descriptor.factIds=[]`
versus SQL JSON `null` mismatch and old full-artifact oracle **FAIL** to remain
visible. No old SQL, command hash, descriptor or verdict is rewritten. See
[historical check and input hashes](evidence/acceptance-a-recheck/historical-stop-check.json).
The first version of this small evidence checker incorrectly accessed root
`status` instead of the actual `automatedEvidenceStatus` field and raised
KeyError. Its original source/error are retained separately; correcting the
checker schema did not alter any historical input or criterion.

## Remaining acceptance gates

| Gate | Current decision / next required proof |
| --- | --- |
| PostgreSQL-only durability | CONDITIONAL/default off: local startup, process restart, duplication, PG outage and no-replay gates pass; integrated real live fault matrix remains incomplete |
| Final-source normal Stop with GPU/sinks | NOT TESTED here. Historical source8f short component passed; source88 full hour still failed final Stop. Neither is reassigned to aab062f |
| Final-source full Golden with bridge repair | NOT TESTED here. F must run one fresh pinned Session/peer and retain all comments, resumes, Stop and exact strict artifact audit; software READY fixtures cannot establish it |
| Redis kill during live narration | NOT TESTED. Redis-off/no-client tests do not kill a running Redis or prove live Redis recovery |
| Live Backend/Runtime/GPU/FFmpeg/network/PG fault recovery | NOT TESTED by this recheck. Real native sinks and supervised fault/restart evidence are required; CPU SIGKILL proof stays separately labelled |
| Physical audibility, human naturalness and busy-comment latency SLA | NOT TESTED here; do not infer from completed sink metadata or this local suite |
| Cross-restart ambiguous cleanup / operator UNKNOWN disposition | P1 integration/product gap: keep unknown media and closed old binding; require reviewed disposition and proven old-owner retirement before a fresh authorized run |

No new P0 was reproduced by this focused review; that is not a claim that all
P0s are absent. F may proceed to controlled real acceptance after its merged
local gate, with all unrun items labelled NOT TESTED. Do not default-enable
PostgreSQL-only, Timeline, Continuity, UDS or QUIC based on this report. Preserve
additive journal/evidence, Redis and TCP rollback paths and every historical
failure. Retire/fence old runs safely before a fresh compatible Session; never
replay UNKNOWN speech as part of rollback.

## Reproduction

Use Python 3.12, Go and PostgreSQL 17. Run the pinned-source script with a new,
nonexistent output directory (it owns only that temporary cluster):

```sh
/private/tmp/astralive-f-media-venv-1/bin/python \
  docs/v0.5/evidence/acceptance-a-recheck/reproduce.py \
  --repo /private/tmp/astralive-v05-acceptance-a-20261015-1 \
  --output /private/tmp/astralive-a-acceptance-focused-rerun
```

The exact executed invocation and historical-check command are preserved in
[invocations.json](evidence/acceptance-a-recheck/invocations.json). Only selected
logs/manifests/scripts are committed; no pgdata, full archive, socket, private
binding, vault or credential is included.
