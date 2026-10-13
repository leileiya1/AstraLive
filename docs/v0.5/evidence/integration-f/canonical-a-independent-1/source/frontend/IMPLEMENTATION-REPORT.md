# AstraLive Frontend Implementation Report

## Scope

Implemented under `frontend/**` only, in the requested order:

1. Vite, React, TypeScript 7 native preview, Bun, Tailwind, TanStack Query, Zustand, Zod, shadcn style UI primitives, and locked `bun.lock`.
2. Generated API types from `contracts/control-api.openapi.yaml`; centralized typed Go Control API client with envelope errors and idempotency keys.
3. Responsive application layout and navigation.
4. Dashboard with Go readiness and selected session status.
5. Avatar list, create, prepare, delete, and job polling.
6. Voice list, create, and delete.
7. Product list, create, and update; KnowledgeBase contract limitation shown.
8. Live Room list, create, and update.
9. Live Console with session creation, start, stop, speak, status, and error panels.
10. Unified SSE hook with reconnect, heartbeat timeout, cleanup, event validation, and deduplication.
11. Utterance timeline driven by SSE events.
12. Interrupt command that waits for an SSE fact before changing utterance status.
13. Development-only mock COMMENT publisher through Go.
14. WebRTC receive-only preview wrapper with peer cleanup and injectable signaling adapter.
15. API, session start, SSE reducer, timeline, interrupt, runtime error UI, and WebRTC wrapper tests.

## Verification

- `bun install`: passed; `bun.lock` generated.
- `bun run build`: passed, including OpenAPI type generation and `tsgo --noEmit`.
- `bun run test`: passed, 4 files and 9 tests.
- The handwritten API client and UI make no `/internal/v1/**` calls. Generated OpenAPI types include Go-owned internal Tool paths because they are present in the source contract.

## Historical v1.0 contract limits

At the initial implementation, the control contract did not define SDP/ICE signaling. Contract v1.1 now defines the public offer/answer route, and the frontend migration below uses it. A connected browser media preview still requires integration acceptance. The contract also lacks KnowledgeBase creation fields and list route, Dashboard aggregate session/error routes, and public Runtime health/metrics. These views state their limits instead of inventing routes or data. Backend and Runtime are not implemented in this workspace snapshot, so a live end-to-end run was not performed.

## Contract v1.1 Migration (2026-10-06)

- Regenerated `src/api/generated.ts` from the frozen `contracts/control-api.openapi.yaml` v1.1.0. The centralized client now uses generated `WebRTCOffer`, `WebRTCAnswer`, and `Utterance` types; dev COMMENT requires HTTP 202 and preserves standard error envelope details, including HTTP 409 `SESSION_NOT_RUNNING`.
- LiveRoom create/edit now loads the Product list and supports optional `activeProductId`. Save sends `activeProductId`, `knowledgeBaseId`, and `systemPrompt` together.
- Live Console creates a receive-only browser peer for a `LIVE` or `DEGRADED` Session, waits for local ICE gathering to finish, sends the complete SDP offer through the public Go route, and applies the returned answer. Peer/media cleanup and signaling errors are handled. No internal Runtime Control API is called; media uses the browser peer to reach Runtime.
- The existing SSE hook already listens for explicit `event: heartbeat`; a new fake-timer test confirms it resets the 45-second timeout and never enters the business Timeline. Interrupt continues to wait for an SSE fact before changing utterance status.
- Dev COMMENT displays the accepted `QUEUED` utterance ID while its Timeline waits for SSE. Standard 409 errors are shown through the shared error component.

Verification: `bun run build` passed; `bun run test` passed (6 files, 18 tests). Tests cover LiveRoom create/edit payloads, heartbeat timing and Timeline exclusion, complete ICE offer exchange, signaling failure, COMMENT 202/409, and the existing Interrupt/SSE behavior. A live browser to Runtime media connection was not exercised in this frontend-only migration.
