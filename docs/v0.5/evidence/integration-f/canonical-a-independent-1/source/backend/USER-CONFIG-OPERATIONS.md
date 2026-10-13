# User Configuration v0.3 Operations and Shared Handoff

Implementation is opt-in. It does not import experimental credentials, override the accepted Runtime or activate GPUs. Existing v1.1 API stays intact.

## Deployment bootstrap (operator only)

1. Back up PostgreSQL. The existing migration runner applies `000003_user_configuration.sql` transactionally; tested against a disposable PostgreSQL instance and rerun for idempotency.
2. Prepare a private directory outside the Git tree and outside PostgreSQL storage. Run from backend:

```sh
go run ./cmd/config-bootstrap --dir /absolute/private/path/astralive-config
```

The command creates a random AES keyring and distinct identity/worker token files with 0600 permissions; prints no secrets and refuses overwrites. Do not copy these files into Git or a DB backup. Use a deployment secret manager or protected filesystem, not ordinary users' .env edits.

3. Operator environment/secret mount:

```text
CONFIG_PUBLIC_ORIGIN=https://your-astralive-host.example
CONFIG_KEYRING_FILE=/absolute/private/path/astralive-config/keyring.json
CONFIG_IDENTITY_TOKEN_FILE=/absolute/private/path/astralive-config/identity-token
CONFIG_WORKER_TOKEN_FILE=/absolute/private/path/astralive-config/worker-token
CONFIG_LLM_HOSTS=approved-public-provider.example
```

Empty origin keeps the legacy stack unchanged and leaves configuration routes unmounted. Invalid origin or keyring prevents startup. Files are reread during use; keyring/token rotations need no process restart. Preserve old key IDs until old credentials AND encrypted bindings are gone. Credential replacement uses the UI's dedicated update action and invalidates current verification/default. No bulk master-key rewrap is implemented.

4. Serve the React app and Backend on the same HTTPS origin; reverse proxy only `/api/` to Go, explicitly deny public `/internal/v0.3/`. Keep trusted identity adapter and Worker traffic on protected TLS/service networks. Disable request/response body logging for config/internal paths at proxies/APM. Existing unauthenticated legacy v1.1 resources are not yet a multi-tenant SaaS authorization surface.
5. Connect the existing login service to `POST /internal/v0.3/config-sessions` using the identity token. Scope must derive from validated login claims. Set returned opaque token using server-side `Set-Cookie: astralive_config_session=<opaque>; Secure; HttpOnly; SameSite=Strict; Path=/api/v0.3/config; Max-Age=43200`. Do not deliver token JSON to browser JS. Logout revokes via DELETE internal session adapter and expires the cookie. Repository inspection found no existing webpage login implementation, so production login integration remains a release blocker; this module intentionally does not add password/OIDC login.
6. Periodically delete expired rows in `config_auth_sessions` and `provider_bindings` using an operator DB job; expiry is enforced even without cleanup. Backup restores must restore the matching externally stored keyring separately.

## Other Agents' integration ownership

- SoulX Worker Agent: consume immutable binding using dedicated worker token, match tenant/user, retain one bundle per Session; report GPU_WORKER version-bound health; never read the browser cookie or arbitrary user URLs. Lifecycle allocation/rendering is outside this module.
- Avatar/Voice Agent: implement real XiaoYa synthesis / Avatar prepare probes under a future explicit capability-contract amendment. The UI currently reports `PROVIDER_TEST_UNAVAILABLE`; saving metadata does not prove inference.
- Control/Runtime Session integration owner: establish authenticated Session ownership mapping and attach binding privately without changing frozen v1.1 wire/FSM. Capture at new Session creation, construct Providers once, release on Stop/failure. Empty or incomplete bindings must fail explicitly. Do not hot-swap existing Providers or fall back to global/experimental keys. This module does not alter existing Session logic, and settings do not drive the production Runtime until this integration passes.

Shared frozen specs: `contracts/USER-CONFIG-CONTRACT.md`, `PROVIDER-CONTRACT.md`, `DATABASE-MIGRATION-PLAN.md`, `SECURITY-BOUNDARY.md`, machine-readable additive OpenAPI `contracts/user-config/schema.json`. Frontend DTOs are generated from that spec; `generate_schema.py` is its checked-in generator. Frozen v1.1 files are unchanged.

## Verification commands

```sh
# Explicit DISPOSABLE PostgreSQL database; never point this at production.
CONFIG_TEST_DATABASE_URL='<disposable PostgreSQL URL>' go test -race ./...
# Frontend (run in frontend)
bun run build
bun run test
# Runtime (repository root; real-provider tests stay opt-in)
PYTHONPATH=runtime runtime/.venv/bin/python -m unittest discover -s runtime/tests -p 'test_*.py'
# Existing contract and acceptance guards with explicit test dependencies
uv run --with-requirements tests/requirements.txt --with-requirements runtime/requirements.txt python -m unittest tests.test_contracts tests.test_acceptance_guards
```

Rendered Chrome fixture uses real HTTPS Go + isolated Postgres, but SYNTHETIC upstream responses only. Start `TestConfigurationBrowserHarness` with `CONFIG_BROWSER_TEST=1`, explicit disposable DB and `CONFIG_BROWSER_READY_FILE` pointing to a temporary file; then run `CONFIG_BROWSER_READY_FILE=<same path> uv run --with playwright python tests/config_center_browser.py`. Self-signed loopback TLS is ignored only in the test browser. Test-only login/probe routes never compile into the production server.

## Real DeepSeek acceptance gate

After HTTPS and login are connected, the actual user enters a NEW Key in the configuration center. Save, test and obtain a real nonempty reply, refresh to safe metadata, update to another/new rotated Key and test again, verify an intentionally invalid Key produces visible failure and blocks default selection. Do not use keys from `.private` experiments, chat, Git, browser storageState or reports. Currently REAL_PROVIDER_NOT_VERIFIED; synthetic upstream tests cannot satisfy this gate. No full v0.3 production release claim is made.
