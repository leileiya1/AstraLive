# v0.4 Authorization Boundary

## Audited deployment and scope

The baseline has no trusted public authentication gateway. The frontend proxy exposes /api; legacy /api/v1 routes lack product authorization. CONFIG_IDENTITY_TOKEN is an internal adapter credential, not a user identity. The user selected a single-operator MVP on 2026-10-10. There is no registration, team administration, SaaS tenant provisioning, OIDC or account recovery claim.

The deployment administrator provides a private operator file with username, bcrypt passwordHash (cost12..14) and existing tenant/user scope. No second account table is introduced. Successful login calls existing IssueSession and stores only a SHA256 opaque-token hash in config_auth_sessions. It returns identity metadata, never the opaque token in JSON. Both cookies refer to the same row:

| Cookie | Path | Flags |
| --- | --- | --- |
| astralive_user_session | /api | Secure, HttpOnly, SameSite=Strict, 12h |
| astralive_config_session | /api/v0.3/config | same flags and token |

POST /api/v0.4/auth/login requires exact configured Origin, bounded JSON/password and a database-backed five-attempt/minute global login limit. This small MVP limit can be exhausted by hostile traffic; deployment should also provide ordinary ingress rate limiting. A login rotates the presented existing product session. POST /auth/logout deletes the hash and expires both cookies. Expiry/revocation apply to both product and configuration requests. SSE rechecks server-side identity at least every15s and closes after revocation or expiry.

## Product ownership

All /api/v1 routes with configuration enabled require product identity BEFORE frozen request validation or idempotency replay. resource_owners scopes avatars, voices, products, knowledge bases, jobs, rooms and sessions by tenant AND user. URL IDs and body references are checked; list responses filter by caller scope. Unknown/foreign IDs are indistinguishable404. Idempotency storage keys include scope and cannot replay another user's response. Browser tenant/user headers or JSON cannot set owner.

Historical rows are intentionally unclaimed. No migration transfers another user's resources. Creation of most legacy resources writes a separate owner record before responding; if that insert fails, an inaccessible orphan may remain for operator reconciliation. New integrated Sessions use a transaction for Session, owner, room snapshot and binding mapping. Concurrent room updates cannot produce a mixed snapshot. Resource IDs have no ownership-transfer API in this MVP.

Config/Profile and physical Worker ACL checks remain the existing frozen mechanisms. Creating an owned GPU_WORKER profile with another operator's workerRef does not grant access. Both the Backend management registry and Runtime inference registry must authorize the same trusted scope. A product cookie is never accepted as a service Bearer.

## Service boundaries and ingress

| Role | Credential | Purpose |
| --- | --- | --- |
| Login adapter | operator file; CONFIG_IDENTITY_TOKEN_FILE for existing trusted adapter | issue/revoke config_auth_sessions |
| Binding consumer | CONFIG_WORKER_TOKEN_FILE | existing0.3 capture/resolve;0.4 server-owned Session mapping |
| Go -> Runtime | RUNTIME_CONTROL_TOKEN_FILE | all bound Runtime HTTP commands/status |
| Runtime -> Go Tool | INTERNAL_API_TOKEN / TOOL_TOKEN | existing dynamic product facts |
| Runtime -> GPU | existing inference token | unchanged Worker1.1 session/epoch/generation protocol |
| Backend -> GPU health | existing management token | loopback read-only management status |

Startup checks binding/control/identity/Tool credentials are distinct; files must be private regular files. Runtime rereads control tokens per request. Browser sees none of these tokens, their paths, Worker endpoints or SSH information. Binding plaintext is transient trusted Runtime memory. Logs exclude raw exception strings and upstream resolution payloads.

Production Backend and Runtime refuse startup without the explicit Session-binding gate. Legacy development stacks without config retain baseline behavior and are controlled-development-only. Do not publish them as a product. Public ingress must explicitly deny ALL /internal/, including v0.3/v0.4 and Runtime/Tool paths. Bind service listeners to loopback or protected private networks; use TLS across untrusted service networks. The isolated HTTPS acceptance proxy denies internal paths. An example production ingress fragment is in PROVIDER-INTEGRATION.md.

## Frozen error compatibility

Frozen1.1 ErrorCode enums remain untouched. Authentication uses401 INVALID_ARGUMENT, CSRF403 INVALID_ARGUMENT, foreign owner404 RESOURCE_NOT_FOUND. Provider-selection failures use CONFLICT or RUNTIME_UNAVAILABLE with a static details.integrationCode. New /api/v0.4 and configuration routes use their explicit integration error codes. Runtime v1 errors follow the same envelope compatibility; provider summaries and runtime-event payloads disclose static integration reasons.

## Acceptance boundary

The single login adapter is a real server-side authentication path. Same-tenant A/B tests use separately provisioned trusted identities to exercise SQL/HTTP ownership, without claiming two interactive SaaS accounts. PostgreSQL tests use a dedicated disposable container; production data is never cleaned. TLS browser interaction, actual DeepSeek requests and GPU inference are reported separately in AGENT-A-ACCEPTANCE.md.
