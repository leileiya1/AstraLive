# Narration Continuity — Agent C

Contract: **v0.5-frozen-1**. This branch implements the optional Go/PG business
orchestrator and Python segmented execution, using Agent A persistence and
Agent B §5 MediaTimeline. The implementation is **CONDITIONAL**, not complete
SoulX/product release acceptance. No branch is merged into main here.

## Enable and compatibility

The frozen canonical flag is `ASTRALIVE_CONTINUITY_ENABLED=false` in both
services. The earlier prompt spelling `ASTRALIVE_NARRATION_CONTINUITY_ENABLED`
is not an approved alias: its presence is a startup error, even when false or
both values agree (CCR-C-002). Unset/false preserves ordinary Speak/Utterance.
Empty/invalid canonical values are errors.

Continuity requires `ASTRALIVE_DURABILITY_ENABLED=true`, authenticated captured
Session binding, PostgreSQL migrations supplied by A, the dedicated journal
and control credentials, and `ASTRALIVE_MEDIA_TIMELINE_ENABLED=true`. Keep
existing binding/security configuration; do not pass secrets in request bodies.
The initial BEGIN_RUN captures feature flags. Runtime binds a Timeline only for
a captured continuity run and before starting its output. Output sinks must be
ready and their actual incarnation IDs captured before starting a plan.

Once bound, an output rejects untimed ordinary speech before its first segment,
during an answer and after the plan finishes. There is no implicit Timeline
unbind or same-output legacy handoff. Ordinary mode uses a new, clean captured
Session/output. Public operator FORCE cancels automatic continuation and returns
the existing **202 `{utteranceId,status:"FAILED"}`** response. The failed request
(`DEPENDENCY_UNAVAILABLE`), FORCE_INTERRUPT Outbox command, SQL barrier and
operator override commit in one public idempotency transaction. It creates no
SPEAK/media/provider job and no fabricated Runtime completion event. 202 proves
that durable disposition; actual sink fencing is asynchronous. Non-FORCE is409
with no effects. Stop and expired authority reject requests before cache hits.

## Authored plan and cursor

`backend/internal/narration` owns immutable NarrationPlan/Beat/Segment, Semantic
Cursor, InteractionTurn and ResumePoint. Beat and segment IDs are stable hashes
of narration/script version/order/content, not TTS token positions. PostgreSQL
`v05_narrations.document_json`, normalized segments/turns and A's attempt/epoch/
commit tables are the source of truth. `beatProgress` is a derived required/
completed/pending-fact projection of that same cursor.

Authors supply complete semantic statements and explicitly map fact IDs. Missing
or duplicated required facts are rejected. Short fact-free sentences can be
packed to an approximate2–4-second target; prices, units and models are never
cut by character count. A whole indivisible statement may be longer. Runtime
measures complete PCM and rejects artifacts above8 seconds; it never truncates
a claim to fit the cap. One active segment/attempt executes per Session. Text
planning can describe60 seconds or10 minutes, but it does not enqueue a long
TTS/GPU job or all remaining media.

Known dynamic facts require trusted placeholders (`{{price}}`, `{{stock}}`,
`{{name}}`, `{{description}}`, `{{sizes}}`, `{{currency}}`) and a matching fact ID.
Go reads the current authorized product through the immutable Session binding,
hashes decimal strings and rechecks before selection, READY/commit, answer,
bridge and resume. A changed fact snapshot or mismatched Room product makes a
durable whole-Session Stop/barrier and seals the old plan/media. App's
`AttachNarration` hook calls the existing `durableControl(STOP_SESSION)` inside
the same borrowed transaction. Both identity and fact-hash invalidation take
this conservative route; no narration-only Stop is represented as Session cleanup.
The persisted lifecycle command has `segmentId:null`, lane OPERATOR, and the
existing Session/run STOPPING disposition. Binding/output release still awaits
normal Runtime cleanup proof. A new product requires a new captured Session;
no hot product replacement. Without that composed retirement hook Start fails503.
The initial implementation commit06b182f contained a reproduced SQL/Scheduler
lock cycle in this retirement hook. The follow-up removes synchronous memory
Stop/Override from `durableControl`: borrowed Commit is a no-op, and only the
actual outer commit grants authority to cancel the local queue. The existing
Interaction worker reads committed control disposition before its idle shortcut,
outside both mutexes, and projects Stop/Force. It tracks runEpoch/commandSeq so
an old FORCE is not reapplied after a permitted local mode change. The business
operator-override barrier remains authoritative for narration; this introduces
no automatic continuation permission. Durable-mode polling is bounded and legacy
non-durable mode retains its receipt-driven behavior.

Scheduler evaluates advisory Gate outside its mutex, then rechecks Stop, mode,
in-flight admission, selection interval and TTL. C Gate is a nonlocking MVCC
snapshot; Select still validates actual owner/binding/lease/product/revision and
Stop under the shared SQL authority locks. Product retirement and a concurrent
operator Stop reuse the first immutable STOP_SESSION envelope rather than
conflicting on its original reason. See the [locking review evidence](evidence/agent-c/locking-review/README.md)
for the original failure, populated production-worker rollback/concurrency tests,
new native short recording and final regression.

Custom authored fact IDs remain the author's responsibility; numeric labels alone
are not an independently verified product database.

Authenticated opt-in routes: `POST /api/v0.5/narration/{sessionId}/start`,
`GET /api/v0.5/narration/{sessionId}/`. Both check Session AND Room ownership.
Start202 means durable plan and first command intent, not audible playback.
Repeat `requestId` with identical input returns the same plan; changed input409.
Example body (replace required sink IDs with the actual captured incarnations):

```json
{
  "requestId": "product-demo-1",
  "scriptVersion": "script-1",
  "requiredSinks": ["peer_actual_incarnation", "rtmp:1"],
  "policy": "AT_BOUNDARY",
  "style": "自然亲切",
  "beats": [
    {"title":"商品定位","requiredFactIds":["name"],"statements":[
      {"text":"这款是{{name}}。","factIds":["name"]}]},
    {"title":"水箱容量","requiredFactIds":["description"],"statements":[
      {"text":"{{description}}","factIds":["description"]}]},
    {"title":"购买说明","requiredFactIds":["price"],"statements":[
      {"text":"这款目前价格是 {{price}} CNY。","factIds":["price"]}]}
  ]
}
```

## Suspend → answer → bridge → resume

Use the frozen states PLANNING, NARRATING, SUSPEND_REQUESTED, SUSPENDED,
ANSWERING, BRIDGE_READY, RESUMING, STOPPING/STOPPED, RECOVERY_REQUIRED and FAILED.
The request's alternative PREPARING/FINISHED labels do not replace the freeze:
language preparation is an Outbox/inbox attempt; completion is STOPPED/FINISHED
reason. All consequential state/cursor transitions are SQL transactions with
revision CAS and fresh run/lease/binding/owner checks.

The existing InteractionController and Scheduler retain priority, deduplication,
merge, fairness, TTL, capacity and expiry. A small optional gate defers new
comments during suspension, answering and resume. There is no second Scheduler.
The normal selected-comment path is AT_BOUNDARY, never FORCE; NEVER rejects it
and automatic IMMEDIATE is rejected. Merged normalized source IDs persist with
adapter/platform/Room scope. A128-ID overflow is explicitly dropped and counted,
not reported as a merge whose source mapping disappeared. Internal selection/
status JSON adds `sourceIds`; frozen platform event fields remain unchanged.

1. Selection rechecks LIVE, owners, product, TTL and permitted narration state.
   Turn, SUSPEND_REQUESTED and SUSPEND_AT_BOUNDARY Outbox commit together.
2. Runtime accepts suspension independently of its current segmented media task.
   It completes the current natural statement. Required named contiguous audio
   **and** video sink receipts and the installed suspension jointly establish the
   boundary. A late suspension acknowledgement uses the exact saved checkpoint.
3. Go saves ResumePoint before answering; INVALIDATE_AFTER fences old media and
   a reserved BEGIN_EPOCH becomes ACTIVE through A/B's durable journal.
4. Fresh authorized answer text enters lane **AUDIENCE_ANSWER**. Price/stock
   answers and name answers are deterministic Go facts. Unsupported suitability/
   calculation questions get the exact fresh short description and an explicit
   limitation; absent/long descriptions get a conservative inability to confirm.
   Free-form LLM answers cannot inject prices/specs or suitability quantities.
   Relevance and usefulness of these limited answers still need human evaluation.
   Preparation is bounded8 seconds and100 characters without a
   mid-sentence truncation. No completion is inferred from language generation.
5. After answer completion, bridge context includes goal, last completed text,
   question, actually committed answer, completed/pending facts, next Beat,
   latest product facts and style. LLM selects approved fact-free wording or an
   empty bridge. Only neutral headings can enter spoken transitions. It cannot
   change the cursor or invent facts. A bridge is at most two short sentences.
6. Go explicitly maps a deterministic committed answer to pending narration
   only when the complete original statement appears in the answer under the
   same fact version and all its fact IDs are covered. SATISFIED_BY_ANSWER then
   skips that exact pending statement. Labels/LLM memory/partial overlap never
   skip it. Resume fences into a new epoch, optionally speaks RESUME_BRIDGE,
   then executes the exact next Segment. An expired selected question skips the
   answer and uses one new resume epoch; it does not stick waiting for a missing
   answer epoch or suddenly speak the expired question later.

## Media and recovery evidence

Runtime uses A's PostgresTimelineJournal through the same-client SQLite WAL
proof spool. Stable observations persist before POST and retry their original
body/producer. B installs a blocked commit before durable COMMIT_INSTALLED ACK;
publication checks session/run/timeline/generation/segment/utterance/lane and
physical output eligibility, rather than trusting coroutine cancellation.
Explicit serialization preserves derived PTS. Flat named audio/video receipts
come from B's actual contiguous consumed ranges, never a Python task's success.

Lightweight2D stages complete immutable PCM **and video** before READY, with
8-second and160MiB per-artifact limits. Source-sample-paced publication releases
20ms PCM chunks with at most40ms lead and matching video first. This prevents a
precomputed READY artifact from bursting through B's independent bounded sink
queues. It is not an artificial A/V delay or enlarged queue/timeout. The three
earlier burst failures are preserved as fail-closed evidence, not discarded.
Global multi-Session memory/admission and provider resource soak are not yet
accepted.

**SoulX/native staging is fail closed before TTS/commit.** Existing Worker Credit
also commits pose history and cannot be used early to privately stage all video.
CCR-BC-001 remains NOT APPROVED. This branch does not modify Worker wire frames,
credit windows/history, or dilute READY to PCM-only. The default authenticated
`session_binding.bundle_factories` constructs StrictSoulX; it has no production
complete-media staging adapter. The exercised CPU path uses an injected
Lightweight2D bundle in the fixture/library integration. Enabling flags alone
therefore does not make the default bound provider executable. CPU staging and
B's separate historical GPU experiments do not establish continuous SoulX
acceptance.

Recovery distinguishes generated, queued, sink-consumed/committed, and audience
heard/seen. Only required-sink proof advances the semantic ledger. Sink proof
does not prove physical audibility; all evidence retains `audienceAudible:false`.
RTP/decoder/device residual buffers cannot be retroactively retracted. No
exactly-once audible playback is claimed.

A Recovery Coordinator seals retired effects and installs a fence-only new run.
Five tests SIGKILL the actual Python process at SUSPEND_REQUESTED, SUSPENDED,
answer preparing, ANSWERING and resume preparing; SQL state at the window is
asserted. A fresh recovery owner retains the completion cursor byte-for-byte,
marks ambiguous attempts UNKNOWN and enqueues no new answer/resume/media.
Model recovery additionally distinguishes EXECUTING/UNKNOWN from PENDING and
keeps completed facts. Automatic Timeline hydration/unblock or replay of unknown
tails is not implemented. Operator reconciliation needs normalized attempt and
proof records as well as the semantic document; the old document can retain its
retired run/EXECUTING label while A's attempt ledger is UNKNOWN. Retire the old
Session and explicitly author remaining facts in a new captured Session after
review. An operator reconciliation/continuation UI/API and automatic recovery
bridge remain a delivery gap. Backend-process/PG-outage injections are A-owned;
the C five-window evidence is Runtime SIGKILL, not a claim to have killed every
component in those windows.

## Validation and evidence

See [evidence index](evidence/agent-c/README.md) and its manifest for exact commands,
exit codes, source/dependency pins, raw logs and recording hashes. Native Chrome
and localhost FFmpeg RTMP tests use synthetic pulse/sine audio, deterministic
language selection and Lightweight2D. They run real A HTTP/PG/SQLite journaling,
B Timeline/sinks and production Scheduler/InteractionController. They do not
contain spoken product narration and cannot pass human naturalness/relevance.

The short native test executes a20×3-second source plan with a comment at about
10 seconds. The long test executes200×3-second narration with five interruptions
and209 media commits, including answer/bridge segments and one exact price
statement satisfied by the answer. A seeded random repeat records seed and
positions. Both require both real sink proofs before semantic completion.
The v1.1 validator and full Go/race + Runtime regression suites retain ordinary
flag-off behavior. Eleven Runtime opt-in real-service tests remain skipped in
the default discovery; the explicitly run native tests have separate evidence.

Metrics distinguish clock domains. Unique decoded Chrome video markers and
chronological equal-count synthetic audio pulses give a same-browser-clock
selected-comment→answer proxy. Pulses have no unique audio ID; missing coverage
remains null. RTMP packet PTS/decoder onsets are audited separately. The fixture
also proves logical5/5 resume and zero missing/duplicate required-fact IDs, not
zero repeated spoken claims from a real LLM. The five answers intentionally
repeat current price/stock when asked; ledger deduplication counts narration
coverage, not a ban on answering the same fact again. Decision→stop, actual answer end→
resume audio, production correlated semantic metrics, process resource series
and real-GPU stale-frame count remain uncollected. The P50≤5s/P95≤8s busy Chrome
SLA,30–60-minute random load, real LLM/TTS/SoulX, official platform, remote GPU,
Windows, transport matrix and human quality are **NOT ACCEPTED / NOT TESTED**.

## Rollback

Normal authorized Stop must durably seal the old Session/run and finish output
cleanup first. Keep PG receipts/cursors and SQLite proof spool for reconciliation;
do not delete unknown evidence or replay it. Set `ASTRALIVE_CONTINUITY_ENABLED=false`
in both services, remove the unsupported alternate name, then restart services
and create a new ordinary Session/output. Keep the additive A schema and its
existing durability/binding configuration; C owns no down migration. To return
all the way to v0.4, follow A/B's sealed-run rollback instructions rather than
toggling flags on an active bound output. Default-off ordinary regression and
new clean RuntimeSession tests pass; same-output unbinding remains unsupported.
