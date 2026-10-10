# Agent A Acceptance — v0.4

Status: single-operator MVP integration implemented; real short business-path and native browser playback accepted on2026-10-10. This is not multi-user SaaS or a commercial-release claim.

Baseline/main/origin/main were rechecked as e70274b8781a6c4076e3b35609108f46bac9f768. Original main worktree has only untracked pyproject.toml; tracked source remains unchanged. The worktree uses its own ignored dependency installation. Worktree: ../AstraLive-v04-session. Branch: codex/v0.4-session-integration. First delivery8bc89bf contains integration hooks/design. No Agent B code is imported or merged. Frozen contracts/generated1.1 DTOs, GPU Worker model/weights/protocol and media algorithms remain unchanged.

## Changed files and core logic

- backend/internal/userconfig/{login,ownership,session_binding,provider_probe}.go: real one-operator login using existing hashed DB sessions, tenant-and-user ownership, immutable business Session capture/resolve, physical Worker ACL, safe actual summary, real supported-provider probes and release/reconciliation.
- backend/db/migrations/000004_session_integration.sql: additive resource owners, private Session binding/room snapshot and DB login limiter. No historical resource ownership is assigned automatically.
- backend/internal/httpapi/{authorization,resources,sessions,server}.go: authenticate before request validation/idempotency, owner-filtered collections and references, CSRF exact Origin, SSE revocation checks and frozen error compatibility. Tests exercise same-tenant separate trusted A/B identities.
- backend/internal/app/{session_integration,service}.go and backend/cmd/server/main.go: private lifecycle hooks, cleanup/failure projection, production gate, distinct authenticated Runtime transport. cmd/operator-bootstrap provisions private bcrypt login data via stdin.
- runtime/app/session_binding.py: immutable per-Session real DeepSeek/XiaoYa/SoulX factories, selected physical registry, strict initial readiness, explicit later degradation/recovery, lease watchdog, one-Worker admission, cleanup/retry and static errors. main.py provides authenticated integration/probe endpoints. providers.py disables environment proxy/redirect use. session.py has only small per-Session/failure-propagation hooks.
- frontend features/settings: genuine login/logout, API URL/API Key/model form, real probes, authorized logical Worker/Avatar choices and physical health. No browser credential readback.
- frontend features/live-console: actual versus future defaults, versions/capture/expiry, REAL/DEGRADED/UNAVAILABLE, safe preview errors, fill/full-image switch and fluid Flex layout. App.tsx/motion-features.ts/package.json/bun.lock and the Tailwind import-only index.css additionally changed at the user's request for full-width Tailwind layout and Motion transitions respecting reduced-motion preference. No new CSS file.
- docs/v0.4: design/security/operation/acceptance documents, separate public/private0.4 machine contracts and sanitized evidence. Frontend generated0.4 types consume only the public extension.

## Automated checks actually executed

| Check | Result | Classification |
| --- | --- | --- |
| go test ./... | PASS with explicit disposable PostgreSQL URL | real SQL/bcrypt/encryption + mock upstream/unit |
| go test -race ./... | PASS, including httpapi/userconfig | race + isolated real SQL + mock adapters |
| Runtime unittest discovery |135 tests,11 skipped, PASS | unit/mock; optional media/network skips retained |
| New binding/probe tests |14 PASS | Mock only; not GPU/LLM inference evidence |
| bun run build | PASS after responsive/Motion changes | generated types, TypeScript and production bundle |
| bun run test |37 tests,8 files, PASS after UI changes | jsdom/fetch fixtures |
| tests.test_contracts + tests.test_acceptance_guards |5 PASS | frozen schemas + mock lifecycle/fact guards |
| Frozen files / git diff --check | unchanged frozen DTO/schema paths; whitespace check PASS | repository audit |
| Authentication, cross-user owner/profile/Worker ID, CSRF, logout | TestProductAuthorizationAndPinnedBindings + scoped probe tests PASS | real trusted A/B test sessions on isolated SQL; not interactive SaaS accounts |
| Expiry, release retry, failure cleanup, Worker disconnect/recovery | dedicated Runtime/Backend tests PASS | Mock/time-controlled; not a24h GPU soak or real disconnect/recovery claim |

Logs were retained outside Git in private temporary acceptance files; committed JSON evidence below contains no keys/tokens/SSH endpoints.

## Real security and user configuration

[security.json](evidence/security.json): unauthenticated live API401; public internal v0.3/v0.4/Runtime paths404; missing/hostile Origin POST403; Runtime rejects no token, binding-role token and Tool token401, accepts distinct control token200. Public profile responses have no plaintext Key, Worker token/file/port projection. Browser login/configuration succeeded with the real operator adapter; the user confirmed all Provider tests succeeded. SQL/HTTP A/B ownership is tested separately from this single interactive operator.

[local-probe.json](evidence/local-probe.json): real XiaoYa nonzero PCM synthesis, physical GPU READY probe and matched SoulX Avatar binding check all returned200 VERIFIED/UP through the public configuration API. GPU/Avatar probes prove health/cache readiness; actual rendering is established by Sessions below.

[rotation.json](evidence/rotation.json): real DeepSeek configuration v1 verified/default. While the old Session retained v1, replacing its profile Key with an intentionally invalid synthetic Key produced v2 and actual upstream PROVIDER_AUTH_FAILED; default selection returned CONFIG_NOT_VERIFIED. Restoring the same user-authorized valid Key produced verified/default v3. A new Session used v3. This does not claim rotation between two different valid keys. No experiment/global Key was used; a user-supplied Key was transmitted only to the authorized Backend/DeepSeek flow.

## Real formal Session and media

[short-session.json](evidence/short-session.json): formal Go create/start -> bound Runtime -> selected real DeepSeek + XiaoYa + SoulX on the existing RTX3080. Session session_4b4f4175af7ef0c8a05e1c45396fddb5 lasted254.933s. One COMMENT traversed the Go development platform-event adapter (COMMENT input is simulated, inference/media are REAL), then completed real LLM/TTS/Avatar media. FORCE interrupted the previous utterance and completed the new generation. The aiortc receiving peer connected, decoded10537 audio/5270 video frames, counted471 nonzero audio/5222 changed video frames. Sample PTS were monotonic; audio209.94s/video209.96s. This is a decoded timeline check, not a speaker-loopback/lip-sync error measurement.

[next-session.json](evidence/next-session.json): next formal business Session session_16b5ab7e2936e03cfb227cd0d33ec0a8 captured LLM v3 and the same verified local bundle. Duration26.545s; real COMMENT completed; receiver995 audio/499 video frames,437 nonzero audio/451 changed video frames; monotonic audio19.08s/video19.12s. Both Go Stops202 -> ENDED. Direct isolated DB query confirmed released_at set and encrypted provider_bindings rows removed for both Sessions.

[browser.json](evidence/browser.json): native Chrome, genuine HTTPS login, Room control panel, Go Session create/start and Speak. The first preview failed before an HTTP offer because the user's WebRTC privacy extension blocked peer creation. The user disabled it; the next Session session_de7ca968f35dc8978dad0f0d668b4435 showed Media connected and a rendered official-girl SoulX frame. Utterance utt_e7e5514b11ad86c55ccceab5fdf63008 progressed through synthesis/render/play to COMPLETED. The user explicitly confirmed sound and mouth movement normal. Browser Stop -> ENDED/UNAVAILABLE SESSION_ENDED. This is short subjective playback acceptance; no new hour-long or quantitative browser lip-sync claim.

[worker-unavailable.json](evidence/worker-unavailable.json): after stopping the existing product Worker, new formal Session startup503 with frozen RUNTIME_UNAVAILABLE plus details.integrationCode=WORKER_UNAVAILABLE. Safe summary is UNAVAILABLE/WORKER_UNAVAILABLE, never initial Lightweight REAL. Failed binding cleanup confirmed in SQL. The same cached Worker was subsequently restored so the user can continue viewing the new interface; no cloud instance was created or terminated.

[responsive-browser.json](evidence/responsive-browser.json): after cached Worker restart with a new epoch, another formal Session rendered real SoulX. Native Chrome showed the filled object-cover frame, then the full-image switch restored the uncropped source; the switch was returned to cover.390x844 device emulation visibly wrapped navigation/content and retained proportional preview. Normal Stop202 -> ENDED. The product Worker remains READY for the user; no business Session is left running by this Agent.

## Fixture and deployment scope

Dedicated ephemeral PostgreSQL16/Redis containers on school-linux, loopback forwarding and an isolated HTTPS entrance were used. Existing business DB/Redis data were never cleared. Config/keyring/private role tokens/operator/TLS files are outside Git; GPU tokens never reach the browser. The real Worker uses the existing installed model, weights and generation/epoch protocol.

Mac/school DeepSeek DNS returned reserved proxy addresses and failed the existing SSRF guard. The isolated Go CPU fixture was moved to the already authorized GPU host; public DNS then passed without weakening guards. An incorrect initial custom fixture Redis stream was corrected to the frozen dh.runtime.events.v1 on dedicated Redis. Global deployment Provider defaults were not changed.

## Remaining limits

- Single operator only; no registration, account recovery, tenant/team administration, billing or SaaS SLA. A/B ownership tests do not establish a multi-user product login system.
- Real later Worker disconnect/recovery,24h lease expiry, crash recovery and RTMP/platform publishing through this new path remain unaccepted; Mock coverage is recorded above. No renewal/hot-switch protocol exists. Shutdown margin60s.
- Only captured DeepSeek, installed XiaoYa preset at speed1 and matched SoulX Worker are integrated. Generic OpenAI-compatible endpoints, alternative TTS speeds/providers and personal uploads/cloning fail explicitly or remain outside this gate.
- Worker allocation is per Runtime, not distributed. Legacy owner-insert failure can leave an inaccessible orphan; a lost Runtime can leave a stale Go lifecycle until failure/expiry reconciliation.
- Browser playback can be blocked by user extensions/network/autoplay/output settings. Fill mode preserves aspect ratio by cropping; full-image mode retains all original edges. Cosmetic responsiveness is separate from media inference acceptance.
- Production trusted TLS ingress, secret deployment/rotation, distributed isolation and full service supervision require deployment review. The local self-signed HTTPS fixture is not a production public entrance. The chat-exposed DeepSeek Key must be revoked/replaced by the user after testing; no Key is committed.
