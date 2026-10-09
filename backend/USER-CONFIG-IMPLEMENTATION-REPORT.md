# AstraLive v0.3 User Configuration — Implementation Evidence

2026-10-09. Status: configuration module implemented and tested; **full v0.3 production acceptance pending**. No new paid GPU, neural network change, production Avatar switch, experiment-key import, or accepted Session rewrite.

## Delivered

Four additive frozen contracts under `contracts/`: USER-CONFIG-CONTRACT, PROVIDER-CONTRACT, DATABASE-MIGRATION-PLAN, SECURITY-BOUNDARY. Machine-readable additive OpenAPI and generator are under `contracts/user-config`; generated TypeScript types are separate from v1.1 DTOs. The existing Control/Runtime OpenAPI and CONTRACTS.md passed SHA-256 equality against the pre-change snapshot.

Migration 000003 adds authenticated identity adapter sessions, user/tenant scope, seven logical configuration entities (shared profile table with typed views), encrypted credentials, settings, immutable expiring Provider bindings and test cooldown. No old resource/Session table or earlier migration was changed.

Backend adds AES-256-GCM vault, external owner-only reloadable keyring, scope-enforced CRUD/key update/deletion, backend-only LLM connection test, independent DeepSeek/OpenAI-compatible schemas, HTTPS allowlist/DNS/IP pinning/redirect blocking, version CAS, default/disable actions, trusted worker snapshot resolution and version/TTL-bound health. Public readbacks never contain secrets. Dedicated identity and worker tokens are separated from Runtime Tool token. Key/bootstrap files have no hardcoded production defaults and are ignored by Git.

React configuration center reads real Backend endpoints. It shows unconfigured/configured/failed/default/disabled states, provides model/TTS/Avatar/Worker/platform forms, and permits explicit tests, default selection, secret replacement/removal and policy saving. Password input is uncontrolled and cleared before submission; keys do not enter query/mutation persistence or localStorage. XiaoYa is correctly treated as local TTS, not a fictitious remote TTS service.

## Evidence

| Check | Actual result |
| --- | --- |
| `CONFIG_TEST_DATABASE_URL=<isolated DB> go test -race ./...` | PASS; independent `postgres:latest` container on school-linux loopback through SSH tunnel; synthetic test values only |
| `go test -race ./internal/userconfig -count=1` after final internal-auth/health tests | PASS, 3.741s |
| `go vet ./...` | PASS |
| `bun run build` | PASS, type checking + Vite production bundle; existing dependency annotation warnings only |
| `bun run test` | 34 tests PASS, including 7 settings tests |
| `PYTHONPATH=runtime runtime/.venv/bin/python -m unittest discover -s runtime/tests -p 'test_*.py'` | 79 executed, OK, 11 existing opt-in real-service tests skipped |
| `uv run --with-requirements tests/requirements.txt --with-requirements runtime/requirements.txt python -m unittest tests.test_contracts tests.test_acceptance_guards` | 5 tests PASS |
| Rendered Chrome + HTTPS Go + actual isolated PostgreSQL | PASS; save/refresh/test/default/rotate/401 failed-state persistence/TTS speed readback/Avatar save/Worker UNKNOWN/no localStorage; SYNTHETIC upstream only |
| Frozen v1.1 hashes | all 3 unchanged |

PostgreSQL test explicitly covered: encryption at rest; same-tenant cross-user and cross-tenant denied access/calls/key updates; missing Origin denial; no secret in public responses; stale write and stale test rejection; new test uses new key; pinned binding keeps old key after rotation/deletion; expired binding and revoked identity denial; same-scope Worker reference; stale health UNKNOWN; independent service-token privileges; actual internal resolution and health reporting. Migration rerun was idempotent. AES tests covered altered ciphertext/ownership and master-key activation without restart. SSRF tests covered private/IPv6/reserved addresses, mixed DNS and pinned single lookup, absent host allowlist and blocked redirects.

Browser evidence: `integration/evidence/user-config-v03/browser-result.json` and PNG screenshots, intentionally excluded from Git as local artifacts. `tests/config_center_browser.py` and Go test-only HTTPS harness are retained for reproduction. The harness's synthetic login routes are not included in production binaries. Isolated Postgres container and anonymous volume were deleted; own SSH tunnel terminated; pre-existing containers remained running.

## Acceptance interpretation

1–4. Real user DeepSeek Key save/reply/refresh/rotation: storage and UI flow tested with synthetic credentials; **REAL_PROVIDER_NOT_VERIFIED**, needs a new user Key entered through deployed HTTPS UI.
5. Provider 401 failure: controlled upstream 401 tested through actual Go/DB/Chrome, correctly FAILED and default disabled; actual external invalid-key request not performed.
6. Different users cannot read/use one another's config: actual PostgreSQL HTTP test PASS, including same-tenant users; privileged worker is a trusted service boundary.
7. TTS/Avatar save/read: actual DB and browser PASS; synthesis/render probes still owned by the other Agents.
8. Existing Runtime regression: unit suite OK with explicit real-service skips; no new one-hour/GPU acceptance claim.

Release gates remaining: repository contains no existing webpage login implementation, so trusted login service must connect to the supplied identity adapter; authenticated Session ownership + immutable binding integration must be implemented under the documented shared boundary; XiaoYa/Avatar actual probe adapters require their owners; real DeepSeek Key verification must occur through HTTPS. Current production Session code intentionally continues using the accepted Provider setup. See [operations and shared handoff](USER-CONFIG-OPERATIONS.md).
