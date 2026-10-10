# Comment Scheduler v0.4

## Pipeline and defaults

Adapter → Normalize → source dedup → user/text suppression → candidate queue → explainable merge/rank/TTL → Selection → trusted SpeechDispatcher → existing Go Service speech admission → bound Runtime.

The dependency-free scheduler takes a clock, Dispatcher, Gate function and shared Limiter. It does not import LLM, TTS or GPU packages. Go configuration validates environment overrides:

| Variable | Initial value | Meaning |
| --- | ---: | --- |
| INTERACTION_CAPACITY |64| candidates per Session/Room |
| INTERACTION_TTL_MS |20000| maximum age from first local receipt |
| INTERACTION_MERGE_MS |8000| topic merge/user repeat window |
| INTERACTION_INTERVAL_MS |2000| minimum selection interval |
| INTERACTION_USER_WINDOW_MS |10000| user limiter window |
| INTERACTION_USER_LIMIT |3| admitted distinct comments per user/window |
| INTERACTION_GLOBAL_LIMIT |100| admitted events/sec across this controller |
| INTERACTION_CACHE_CAPACITY |4096| bounded dedup/user/repeat state |
| INTERACTION_ALLOW_PRIORITY_PREEMPTION |false| explicit controlled script preemption |

These are initial conservative values, not measured optimums. Controller capacity is64 entries, with at most one active scheduler per internal Room. Ended snapshots are reclaimed on subsequent admission after one minute. Source identities expire at2×TTL; user/repeat/fairness maps are pruned and bounded. Merged audience membership is capped at128. Recent display is20 comments; percentile history is256 selections.

## Topics and fairness

Rules distinguish `size_option:XL`, `size_stock:XL`, `overall_stock`, price/name, product questions and normalized chat. “有 XL 吗/主播 XL 码有吗/这款提供 XL 吗” merge; explicit SKU inventory never merges with overall stock. General complex wording merges only when normalized text is equal. Numeric sizes are conservatively left unmerged unless identical wording; this avoids speculative semantic equivalence.

Score starts at40, adds10 for a question and30 for product relevance, rewards up to5 additional viewers (4 points each), subtracts45 for recently served users, subtracts estimated reply seconds and comment length, and adds age seconds for bounded waiting fairness. Duration hints (3/4/6/8s by topic) are not provider benchmarks. TTL remains based on the original candidate, so repeated viewers cannot perpetually refresh stale questions. Full capacity drops new candidates; irrelevant content is filtered. Gift spend is absent.

## Interaction state and interruption

The separate modes are PRODUCT_EXPLAINING, COMMENT_INTERACTION, IDLE, OPERATOR_OVERRIDE; Live Session FSM is unchanged. COMMENT_INTERACTION lasts through admitted speech until the next gate observes completion. Default auto speech uses NONE and waits for the existing full utterance/media-drain boundary. This is a conservative paragraph boundary; it is not sub-sentence interruption.

Operator Speak/Interrupt takes control and requires explicit mode resume. Optional preemption only applies in PRODUCT_EXPLAINING to product priority≥80, at least3 viewers, an active lower-priority AUTO_SCRIPT, using INTERRUPT_LOWER_PRIORITY. It cannot preempt OPERATOR or PLATFORM_EVENT speech and never emits FORCE. After successful preemption, OPERATOR_OVERRIDE pauses further automation. Resume policy: operator resubmits the desired remaining paragraph through existing Speak, then restores mode; no claim of automatic word-position reconstruction or blind full-script repetition. Accepted operator FORCE retains existing Runtime semantics. Auto FORCE count is zero.

A Room product change drops old candidates and requires a new Session because Runtime context is capture-time pinned. This avoids silently answering the new Room product with old bound context. Session Stop clears queue/cache/recent content and cancels scheduler/replay; failure/terminal events do the same.

## Formal integration and failure behavior

`app.InteractionController` is created in server/main. `/api/v0.4/interaction/{sessionId}` separately requires ProductAuth (even in development), exact Origin on mutations, Session AND Room ownership. Caller cannot supply room/session/platform mappings. Mock mutation routes only exist outside production; snapshot/mode routes are protected. APIs: GET `/`, PUT `/mode`, dev POST `/mock` (text/users1..100), dev POST `/replay` (rate0/1/5/20,count1..1000), dev DELETE `/replay`.

Before every selection dispatch, owner, Session state, product and speech gate are rechecked. Existing Service.Speak admission is reused via its private shared implementation under the same command mutex; Stop/operator/Speak are serialized within this Backend process. A DB receipt keyed by Session+trace is reserved before creating an Utterance; duplicate/restarted selection fails closed. Runtime rejection becomes FAILED on the Utterance/receipt; scheduler records a delivery failure. Ambiguous network results are not automatically retried, avoiding duplicate speech. A crash after RESERVED can lose a response; manual investigation is required. Pending candidates are intentionally lost on restart. Separate Backend replicas do not have distributed scheduling/command locks; run one interaction controller per Session.

Legacy POST `/api/v1/dev/platform-events` remains direct priority80/INTERRUPT_LOWER_PRIORITY, always creating a task when accepted and keeping202/409 semantics. It bypasses the new selector by design for frozen compatibility.

## Real integration follow-up (2026-10-10)

[Acceptance](AGENT-B-REAL-ACCEPTANCE.md) now includes actual provider/receiver admission, operator FORCE, Worker recovery and replay cancellation. Question ranking also recognizes explicit audience requests (`帮我`, `请介绍`, etc.) with no extra LLM classification call; ordinary ambient statements remain filtered. Snapshot clears an old Utterance ID when a new selection begins and exposes monotonic receipt/selection/dispatch-ack observation. These v0.4-only fields do not modify the frozen legacy COMMENT behavior.
