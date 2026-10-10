# Platform Adapter v0.4

Baseline: `f2f6bdbdc291c2587cdf2eb5b2359b20db2c1696`. Frozen v1.1 schemas, generated DTOs, Session FSM and the legacy development COMMENT endpoint are unchanged.

## Existing capability and gap audit

Agent A provides owner-checked Go control, immutable user Provider Binding, bound Runtime bundles, priority speech admission, FORCE/generation fencing, SoulX streaming/credit, WebRTC/RTMP, degradation and recovery. Runtime already streams LLM tokens and incrementally synthesizes TTS. `fact_answer.py` already protects deterministic product answers. The legacy developer adapter always submits a COMMENT directly at priority80. It has no candidate scheduler, platform transport abstraction or bounded audience queue. Agent B adds those layers; it does not replace inference or media protocols.

## Boundary

`backend/internal/platform` defines idiomatic Adapter (Start/Stop/Health/Capabilities), EventSink, normalized Event, trusted Mapping and classified errors. Start runs until EOF/cancellation/failure; Stop cancels the active context. Health reports connection, reconnect, heartbeat and receive counters. Mock transport performs bounded replay/reconnect; a future authorized official transport supplies its own heartbeat, backoff and authentication policy rather than inheriting a universal WSS/CDP assumption.

Every adapter gets a server-owned platform-room → internal-room/session mapping. Normalize verifies the entire mapping, rejects unsupported event types and invalid UTF8/oversize/control content, and stamps receipt time on the Go clock. Source time stays separate and optional; it never controls rank/TTL. IDs and trace supplied by a caller are discarded. An actual source ID remains unchanged; its scoped hash is an explicitly internal receipt/trace identity. With no source ID, an internal receipt ID is generated and short-window user/text suppression is the weaker fallback. Hash identity excludes transport, so primary/backup delivery shares identity. There is no fabricated upstream event ID.

COMMENT is implemented. LIKE/GIFT/FOLLOW/ENTER are typed reservations and rejected until a payload/adapter extension is implemented. No consumer spending/gift amount affects scoring. Raw comments enter only the existing user-content input; no System Prompt mutation. Prometheus labels contain bounded outcomes and existing fixed operation/route dimensions, never comments, cookies, rooms or audience identity.

## Implemented adapters

`platform/mock` is the only connected adapter in this delivery. Its platform is always `mock`; source transports are MOCK_REPLAY/MOCK_BACKUP. Start refuses production platform labels, concurrent starts and >1000 records. Records can carry synthetic source timestamps, relative arrival delays, heartbeats, disconnect/reconnect and duplicated source IDs. Replay input is bounded to1MiB, strict JSON and at most1000 records; cancellation interrupts waits. Stop before Start is also observed.

Douyin/Taobao/Bilibili/Kuaishou adapters, official credentials, actual upstream reconnect behavior and production transport metrics are NOT TESTED. No private protocol/signature/cookie extraction is included. The framework is ready to host independently authorized adapters; it is not a claim those platforms are online.
