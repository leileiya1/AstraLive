# Committed-control and Scheduler locking correction

Supersedes the shared Go implementation/gates in initial candidate
`06b182f840e0dc110a150a687e7ce016744edb3b`. Frozen contract, inherited A core,
migrations, B Timeline/sinks, Worker format and Runtime source are unchanged.
[Manifest/source/launch hashes](manifest.json); conditional product acceptance
and existing SoulX/recovery/human/SLA gaps remain in the main delivery document.

## Reproduced problem and correction

A's independent immutable06b182f reproduction is retained as
[gzip failure log](initial-a-repro-failure.log.gz) and
[original test overlay](initial-a-reproducer.go.txt). Scheduler held its mutex
while Gate waited for the Session SQL lock. Product retirement held that lock
while borrowed `durableControl` called Interaction.Stop and waited for the
Scheduler. Borrowed Commit was a no-op, so cancellation of the in-memory queue
could precede and survive outer rollback. Another Room's snapshot was also blocked.
That original overlay deliberately expects the old locking shape and is failure
provenance; it is not claimed to pass unchanged on the corrected implementation.

Correction:

- Gate is an advisory nonlocking MVCC snapshot. Select still rechecks actual
  owner/binding/lease/product/revision/Stop under the shared SQL transaction.
- Scheduler releases its mutex around Gate and rechecks context/TTL, Stop, mode,
  in-flight admission and selection interval when it reacquires it.
- `durableControl` performs no synchronous in-memory Stop/Override. Existing
  Interaction worker reads committed SQL control before its idle shortcut,
  outside both mutexes; actual committed Stop/Force then updates its local queue.
  It remembers runEpoch/commandSeq to avoid reapplying historical FORCE after a
  permitted local mode change. Narration's durable override remains authoritative.
- Concurrent product retirement/manual Stop reuse the first immutable
  STOP_SESSION command, preserving its reason and envelope. No A transaction
  helper, general idempotency middleware or migration was changed.

Durable-mode committed-state polling uses the existing configured PollInterval,
with2-second bounded read context. Non-durable legacy idle/receipt behavior is
unchanged. Local queue projection is eventual; SQL barrier/Outbox is authoritative
and no synchronous sink-cleanup or release is inferred from HTTP acceptance.

## Recorded verification

[Focused real-PG/race log](focused.log.gz), exit0:

- Session SQL lock held while advisory Gate and real production Scheduler Tick
  remain responsive; Stop remains responsive during an externally blocked Gate.
- Populated production Ensure worker with queued viewer comment: borrowed Stop
  and FORCE return without acquiring Scheduler locks, outer rollback preserves
  LIVE SQL/queue/mode, actual outer commit is projected even while idle.
- Historical FORCE is not reapplied after an allowed local mode change.
- Independent price/product invalidation with active Scheduler and concurrent
  manual Stop: same immutable Stop command, SQL STOPPING, no answer/resume;
  another Room snapshot remains responsive.
- Protected HTTP FORCE response-insertion failure actually rolls back with the
  production worker/queue populated. Queue/mode survive; same-key and changed-body
  behavior and Stop winning retain their existing gates.

[Final full Go/race log](full-go-race.log.gz), exit0, all packages, owned actual
PostgreSQL and Python child process fixtures enabled. This includes retained
normal answer/resume, expiry, five Runtime SIGKILL windows, public FORCE and
legacy packages. Exact environment command is in the manifest; database/auth
credentials are not included. [Contract log](contract.log.gz), exit0.
Runtime source is unchanged; the initial210-test /11-skip regression remains the
Runtime gate and is not relabelled as a newly executed Python run.

The first new focused run failed because its fixtures assumed immediate
EXECUTING after Start, omitted a required product description and addressed a
nonexistent SQL `lane` column. [Failure log](fixture-errors.log.gz) is retained.
The fixtures were corrected; Gate eligibility is compared with its committed
baseline and lane is read from `payload_envelope`. An earlier product Stop test
had ignored the SQL Scan error and could retain an old count. That assertion now
requires successful SQL and checks the complete null-segment/OPERATOR envelope.
This corrects a coverage defect rather than claiming the original envelope test
had independently proved that field.

## Fresh native run on corrected source

[Native log](native/run.log.gz): PASS69.12s, real headless Chrome/local RTMP,
20×3-second synthetic source plan, one selected question around10s, answer/bridge/
resume,21 media commits and normal Stop. The
[launch source manifest](native/launch-source.json) was captured before this run;
all21 Go/Python file hashes still match delivery. It supersedes the older short
run's missing launch hash and predates no later source change.

[Raw Chrome/RTMP result](native/media.json.gz), [recording](native/continuity.flv),
[raw SQL proof](native/sql-proof.json.gz), [proxy metrics](native/metrics.json),
[receipt audit](native/receipt-audit.json). All21 commits have84 exact matching
named audio/video receipts for `peer_296bfc9305c74217aaaac7b701638584` and `rtmp:1`.
Terminal identity run1/epoch3/generation22, both sinks' final audio/video interval
`[2880000,3024000)` at48000Hz.20 required facts are accounted for, no pending
required facts; SQL commit status SEALED5/ELIGIBLE16. Audience audibility remains
false. Audio is a synthetic pulse, not spoken product text. Native result does
not prove real-provider quality or production bound SoulX staging.

The previously archived660.69-second seeded random long run is retained as
historical evidence; it was not repeated after this locking correction. Final
pin is supplied to A/F for independent review, not assumed to be their approval
or a main merge.
