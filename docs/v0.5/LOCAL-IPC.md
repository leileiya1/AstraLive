# Local Runtime IPC — Agent D

Status: **CONDITIONAL, independent D implementation tested; shared wiring NOT APPLIED / NOT MERGED**. ACK `v0.5-frozen-1` §§7.1/8/9. Defaults remain TCP and disabled fallback. No schema, Session, database, Redis, Worker, WebRTC/RTMP timeline, installer or GPU changes.

Baseline: `cf6540bdcc788c037929836480812dfaa78362a2`. Starting HEAD: `5a24478126211cbcde5a9565d0c6063748426527` (two F documentation commits over baseline). Existing `runtime.Client`, `client.go`, `app.main`, TokenTransport and v1.1 schemas remain untouched. No claim of Host/product-wide v0.5 acceptance.

## Configuration and implementation

| Setting | Default | Meaning |
| --- | --- | --- |
| `ASTRALIVE_LOCAL_TRANSPORT` | `tcp` | Frozen `tcp\|uds`; no `auto` alias |
| `ASTRALIVE_LOCAL_FALLBACK` | `disabled` | `disabled\|tcp`; explicit unsupported-platform startup fallback only |
| `ASTRALIVE_RUNTIME_UDS_PATH` | unset | Canonical absolute path, <=103 UTF-8 bytes; private owned0700 parent |
| `AI_RUNTIME_URL` | existing Backend default | TCP origin; listener default `http://127.0.0.1:8000`; production wrapper keeps old18000 |
| `RUNTIME_CONTROL_TOKEN_FILE` | required by local listener | Same distinct control token role on both transports |

These are F's frozen names, rather than the suggested unapproved `ASTRALIVE_RUNTIME_TRANSPORT=auto` / deployment-mode configuration. Unified Host selection/installation is outside D. F can define an OS-aware Host default in a future CCR; this branch keeps explicit opt-in. Backend's old remote/container TCP URLs remain valid when the feature is off. The **new local listener** accepts only loopback HTTP origins (IPv4/IPv6 literal or localhost), never defaults to0.0.0.0.

`config.LocalTransportFromEnv()` validates/captures startup configuration. `runtime.NewLocal(base, options)` returns the existing HTTP Client: TCP returns `New(base)` unchanged, UDS retains JSON/routes/status/timeout/error mapping and dials the private socket via `http.Transport.DialContext`. Compose existing `userconfig.TokenTransport` **outside** its transport. The same8s timeout, context cancellation, body/traceId,202 accepted validation and30s WebRTC exception remain. No gRPC, new Redis or local proxy. UDS uses no HTTP proxy, disables redirects and has no application POST retry/fallback. Standard Go idempotent GET connection recovery remains available; commands without idempotency headers are not replayed by this adapter.

The Python entry point `PYTHONPATH=runtime python -m app.local_listener` runs the **existing** ASGI application in a separate Runtime process. Uvicorn accepts a pre-bound socket (`Server.run(sockets=[sock])`); this gives the wrapper control over socket permissions/cleanup rather than permitting Uvicorn to unlink an unchecked path. The current tested Uvicorn version is0.54.0. Its signal re-raise is suppressed after orderly ASGI shutdown so the wrapper can unlink its own socket before exit. See [Uvicorn settings](https://www.uvicorn.org/settings/) for the upstream UDS/fd APIs. Windows TCP does not import `fcntl` or construct an AF_UNIX socket; the event loop is explicitly asyncio.

## Shared wiring gate

F's §8 requires A→C→D shared-file sequencing. Therefore shared entry points have **not** been edited concurrently. `runtime/tests/local_ipc/shared-wiring.patch` is a concrete, gofmt-clean integration proposal, compiled/tested in a disposable source copy. It covers:

- `backend/cmd/server/main.go`: validated local client, token/dialer composition, effective transport logging.
- `runtime/app/production_launcher.py`: retain original exec/18000 command with default flags; use private listener in opt-in mode while retaining the publisher lock/preflight.
- `backend/internal/userconfig/{service,environment,session_binding,provider_probe}.go` and a new helper: capture the protected UDS transport for provider-status/TTS probe calls as well as Session commands. Otherwise those secondary calls would still attempt TCP. Default TCP preserves their original transport construction.

**CCR-D-01 (shared wiring) pending A/C/F/auth-owner review and F merge.** These extra protected probe/auth files are outside D's exclusive primary directory; they are only in the patch. No peer ACK is inferred. `docs/v0.5/ARCHITECTURE-CONTRACTS.md` and `INTEGRATION-PLAN.md` are unchanged. F must record the dependency SHA, peer ACK and merge SHA before applying/rebasing the proposal. The ordinary `cmd/server` in this branch alone still uses its original TCP client; the tested standalone factory/listener are ready for that integration. Do not advertise the Backend feature flag as wired until the patch is incorporated.

For inspection in a disposable checkout after the shared-file sequence:

```sh
git apply --check runtime/tests/local_ipc/shared-wiring.patch
git apply runtime/tests/local_ipc/shared-wiring.patch
go -C backend test ./...
```

A new Host environment example is at `runtime/tests/local_ipc/single-host.env.example`. Runtime invocation (with the existing private tokens/provider configuration already supplied):

```sh
export ASTRALIVE_LOCAL_TRANSPORT=uds ASTRALIVE_LOCAL_FALLBACK=disabled
export ASTRALIVE_RUNTIME_UDS_PATH=/run/astralive/runtime.sock
export AI_RUNTIME_URL=http://127.0.0.1:18000
export RUNTIME_CONTROL_TOKEN_FILE=/etc/astralive/runtime-control-token
PYTHONPATH=runtime runtime/.venv/bin/python -m app.local_listener
```

Backend and Runtime must run as the **same service user** in this implementation. The service's existing `RuntimeDirectoryMode=0700`/UMask0077 works; outside systemd create the configured parent as that user before Backend startup. Listener creates only the final private parent, never an unchecked directory tree. macOS needs a short canonical path such as `/Users/your-user/.astralive-ipc/runtime.sock`; `/tmp` and `/var` aliases are rejected, use their canonical paths. Container Compose networking/commands remain untouched; UDS across containers would require a deliberately configured private shared volume/user identity and is not tested here.

## Security and lifecycle

- Parent is owned0700; all ancestors reject symlinks/non-directories and other-user write permission. A root-owned sticky temp ancestor is permitted for tests with a private final directory. Socket is owned0600, chmod occurs **before listen**, and path length is bounded conservatively for Linux/macOS. Group0660 mode is intentionally unsupported.
- Backend pins the parent inode; every new dial validates parent and socket ownership/type/mode, then compares the socket inode before/after connect. Replacement closes/rejects the connection. An existing keepalive connection remains attached to its original endpoint. Same-UID administrators/processes that can rewrite private files are inside the service-user trust boundary; filesystem checks do not replace tokens or sandbox such peers.
- Listener retains an exclusive `flock` on an owned private regular `.lock` file opened with O_NOFOLLOW; it never unlinks the lock (avoids split-lock races). Its persisted device/inode record identifies the socket from its previous lifecycle.
- Stale cleanup requires exclusive lock, matching device/inode, owned0600 socket, and connect probe returning **ECONNREFUSED**. Live, unknown, unowned, symlink, regular-file or uncertain-liveness paths fail closed; no PID guessing. Normal cleanup removes only the unchanged recorded socket. SIGKILL leaves a record for controlled restart. A crash between bind and recording fails closed and may need operator inspection, rather than deleting an unknown file.
- Runtime validates the existing control token on **all** local listener routes, including health, even in binding-disabled experimental mode. Binding-enabled mode uses the original trusted-control middleware and distinct-token checks. Token files are reread per request, retaining rotation/revocation behavior. No local peer is promoted to user/tenant authorization.
- Missing socket/refused connection, unsafe permission/path, replacement and HTTP rejection have diagnostic logs without tokens/request bodies. No invalid token, permission error or runtime response initiates TCP fallback. An unsupported OS can choose explicit loopback TCP at startup before any command is sent. Supported Unix bind/startup failures remain stopped with a diagnosis. Recovery of ambiguous sent commands belongs to A, not a hidden transport retry.

## Reproduce tests and benchmark

Benchmark-only dependency: `runtime/tests/local_ipc/requirements-benchmark.txt` (`psutil`); it is **not** in Runtime production requirements. Tests use a private temporary directory, synthetic private control/worker tokens and owned disposable Runtime subprocesses. No remote production service or paid GPU is started. Linux ran on an isolated directory/venv on `school-linux`; it did not alter existing deployments.

```sh
runtime/.venv/bin/pip install -r runtime/requirements.txt -r runtime/tests/local_ipc/requirements-benchmark.txt
ASTRALIVE_IPC_TEST_PYTHON="$PWD/runtime/.venv/bin/python" go -C backend test -race -v ./internal/config ./internal/runtime
PYTHONPATH=runtime runtime/.venv/bin/python -m unittest runtime.tests.test_local_listener -v
runtime/tests/local_ipc/run-benchmark.sh
# cross compile only; -exec=true deliberately does not execute Windows binaries
GOOS=windows GOARCH=amd64 go -C backend test -exec=true ./internal/config ./internal/runtime ./cmd/local-ipc-bench
```

The benchmark calls the actual authenticated Runtime v1 Utterance route with **exactly1024/10240/102400 serialized JSON bytes**, concurrency1/10/50,200 samples per cell. With no binding it returns409 PROVIDER_BINDING_EXPIRED after auth/JSON/Pydantic/lease checking; **no LLM/TTS/GPU/Speak execution** takes place. The rejected-control path is a transport/control microbenchmark, not a throughput result for successful full Speak. Separate fixture tests cover202/payload/trace/status/redirect parity over UDS. Go→actual Python tests cover health,401, missing-Session404, prestart, kill/restart and graceful Stop cleanup.

Cold1KB closes the underlying connection pool between200 requests. Warm cells include initial connection(s), preserve all200 samples and record GotConn reuse; concurrency1 reuses199/200. No latency outlier/censored request is dropped; unexpected status/transport error aborts the run. The benchmark fails if payload API validation returns422.

Client `totalMs` starts before JSON marshal and ends after response/error processing. `ConnectStart/ConnectDone` measures **kernel dial time only**, not filesystem checks; cold total includes UDS checks. Benchmark-only outer ASGI middleware emits `Server-Timing: app;dur=` using Runtime's monotonic clock, including auth/routing/body read/parse/validation/lookup. `appMs` is distinct from the client total. `residualMs=max(0,total-app)` includes client serialization, scheduling/HTTP/body transfer/response read and wrapper overhead; **it is not pure network transit**. Neither clock is compared across hosts. No production header/API/schema is changed.

Pools use protected baseline `http.Transport{Proxy:nil}` defaults on both transports (per-host idle limit2, no tuning). Client diagnostic logging is equally suppressed in the benchmark; server access logging is disabled. Python TCP uses the same Uvicorn ASGI/asyncio stack. Default/development TCP launcher vs new protected TCP/UDS are preserved as separate evidence.

CPU is process CPU seconds, not normalized percentage: Runtime before/after per cell; Go Getrusage at completion including startup/sampler. RSS/FD peaks are sampled about every5ms and can miss short peaks; Go also records OS MaxRSS. Linux restricts parent access to Go `/proc/<pid>/fd`; Go samples `/proc/self/fd`, and the report records external access denial. Mac FD sampling uses psutil. Small cells, background host work, no randomized repeated trials/confidence intervals, error-route-only processing and instrumentation limit any inference about production latency.

## Evidence and observed results

Evidence is under `docs/v0.5/evidence/local-ipc/`: initial pre-adapter macOS baseline `macos-http-baseline.json`; final comparable `darwin-{baseline,tcp,uds}.json`, `linux-{http-baseline,tcp,uds}.json`; raw samples, per-cell CPU/RSS/FD/connection reuse and source SHA256/flags/software metadata are included. The generated tables below use **final TCP vs UDS** files; baseline remains separately inspectable. Each final file contains2000 samples (cold plus nine warm cells).

### macOS: milliseconds, TCP vs UDS

| Payload / concurrency | TCP P50 / P95 / P99 | UDS P50 / P95 / P99 |
| --- | --- | --- |
| 1KB cold /1 | 0.712 / 1.040 / 1.572 | 0.604 / 0.731 / 0.873 |
| 1KB /1 | 0.578 / 0.721 / 1.011 | 0.539 / 0.614 / 0.663 |
| 1KB /10 | 3.069 / 3.359 / 3.984 | 3.176 / 3.530 / 3.881 |
| 1KB /50 | 14.421 / 19.987 / 20.960 | 14.693 / 20.660 / 21.197 |
| 10KB /1 | 0.588 / 0.675 / 0.781 | 0.556 / 0.655 / 0.768 |
| 10KB /10 | 3.320 / 4.383 / 11.641 | 3.258 / 4.390 / 11.377 |
| 10KB /50 | 14.790 / 17.509 / 18.384 | 14.546 / 17.716 / 17.999 |
| 100KB /1 | 0.806 / 0.980 / 1.224 | 0.907 / 1.109 / 1.319 |
| 100KB /10 | 4.103 / 4.885 / 5.384 | 5.763 / 6.551 / 6.836 |
| 100KB /50 | 19.579 / 29.947 / 30.315 | 27.519 / 33.556 / 34.695 |

Cold kernel connect P50: TCP **75.1µs**, UDS **5.7µs**; this excludes UDS path checks. Warm1KB/1 total P50: **0.578 vs 0.539ms**.

| Transport | Max sampled Go RSS / FD | Max sampled Runtime RSS / FD | Summed Go / Runtime CPU seconds (2000 requests) |
| --- | --- | --- | --- |
| TCP | 37.2MiB /55 | 73.4MiB /69 | 0.509 /0.829 |
| UDS | 39.2MiB /55 | 80.1MiB /63 | 0.490 /0.904 |

### Linux: milliseconds, TCP vs UDS

| Payload / concurrency | TCP P50 / P95 / P99 | UDS P50 / P95 / P99 |
| --- | --- | --- |
| 1KB cold /1 | 1.126 / 1.374 / 1.685 | 0.689 / 0.903 / 1.282 |
| 1KB /1 | 0.643 / 1.160 / 1.252 | 0.608 / 1.147 / 1.308 |
| 1KB /10 | 5.724 / 8.062 / 10.591 | 5.408 / 6.410 / 7.156 |
| 1KB /50 | 29.484 / 39.040 / 39.660 | 26.933 / 34.035 / 34.132 |
| 10KB /1 | 0.718 / 1.292 / 1.501 | 0.626 / 1.061 / 1.238 |
| 10KB /10 | 6.272 / 7.843 / 17.998 | 5.885 / 8.392 / 17.530 |
| 10KB /50 | 28.484 / 33.592 / 34.372 | 28.646 / 33.550 / 35.003 |
| 100KB /1 | 1.010 / 1.681 / 1.982 | 0.952 / 1.687 / 1.929 |
| 100KB /10 | 7.838 / 11.855 / 13.173 | 7.493 / 8.706 / 9.007 |
| 100KB /50 | 36.923 / 51.439 / 54.119 | 37.458 / 50.137 / 50.204 |

Cold kernel connect P50: TCP **52.0µs**, UDS **4.9µs**; this excludes UDS path checks. Warm1KB/1 total P50: **0.643 vs 0.608ms**.

| Transport | Max sampled Go RSS / FD | Max sampled Runtime RSS / FD | Summed Go / Runtime CPU seconds (2000 requests) |
| --- | --- | --- | --- |
| TCP | 33.5MiB /57 | 65.8MiB /65 | 0.644 /1.600 |
| UDS | 33.3MiB /57 | 65.6MiB /76 | 0.552 /1.450 |

Cold kernel connect is shorter on UDS in these runs, but warm-control results are mixed. Several UDS cells are slower, and tail latency does not consistently improve. The retained app/residual breakdown shows that ASGI processing, serialization, scheduling and host load dominate many cells. This is one200-sample run per cell, not a confidence-bounded transport speedup. No evidence supports a tens-fold improvement in full Speak or user-visible LLM/TTS/GPU latency; TCP remains the default.

## Acceptance matrix and limits

| Gate | macOS arm64 | Linux amd64 | Evidence |
| --- | --- | --- | --- |
| Actual Go→Python UDS / loopback HTTP | PASS | PASS | `*-go-tests.log`, benchmark JSON |
| Backend client before Runtime / same client after SIGKILL restart | PASS | PASS | `TestActualRuntimeLocalLifecycle`; error then recovery, no command replay |
| Normal SIGTERM cleanup / stale inode restart | PASS | PASS | actual subprocess test and Python lifecycle tests |
| Parent/socket permissions, file/symlink, live/unknown inode preservation, lock exclusion/replacement | PASS | PASS | Go/Python security tests |
| Invalid token401 / rotation on keepalive | PASS | PASS | actual Runtime test; no auth downgrade |
| Sizes1/10/100KB, concurrency1/10/50, reuse | PASS | PASS |200 samples per cell, no unexpected responses |
| Trace/JSON202/status/redirect/cancellation/WebRTC timeout semantics | PASS (fixture) | PASS (fixture) | `TestUDSSafetyAndHTTPParity`, existing Client regression |
| Real foreign-owner inode cleanup refusal | NOT TESTED | NOT TESTED | non-root test skipped; source checks UID, no sudo available |
| Full Backend+DB+Redis+real providers with staged entry wiring | NOT TESTED | NOT TESTED | staged wiring compiles/regresses; independent IPC test is not Host acceptance |
| Windows TCP runtime/auth/restart | NOT TESTED | NOT TESTED | config simulation + Windows Go cross compile only |

Windows uses the TCP branch without UDS/fcntl. **No Windows machine was available**, so no Windows PASS is claimed. Existing Go/Python token readers rely on POSIX mode bits; their behavior against Windows NTFS ACLs is an explicit auth-owner/F validation gap, not waived or weakened by this transport. Production RTMP launcher is already Linux-specific (`fcntl`/systemd); Windows uses the new standalone listener, subject to that auth gate.

Local Go full suite (`go -C backend test ./...`) passed; Python Runtime/binding regression41 tests passed; v1.1 contract validation passed. Go race tests with actual subprocesses passed on both platforms. Python security suite10 tests:9 passed, foreign-UID test skipped on each. Staged shared patch in a disposable copy passed full Backend Go suite; shared source files in this branch remain unchanged. Windows compilation passed without executing the binaries. Exact logs accompany these claims; real provider/media/continuity and official-platform acceptance are not inferred.

## Rollback and handoff

1. Stop/fence new admission and owned Sessions; resolve/record ambiguous commands and allow Runtime/media cleanup/binding release. Never replay sent/unknown commands during a transport change.
2. Stop Runtime/Backend. Set `ASTRALIVE_LOCAL_TRANSPORT=tcp`, `ASTRALIVE_LOCAL_FALLBACK=disabled`, restore the old `AI_RUNTIME_URL`, retain the same private control token/binding configuration.
3. Start the original TCP Runtime entry (or default production launcher) and Backend. Confirm authenticated health, ordinary command semantics and no remaining owned output. Defaults return `runtime.New(base)` and the production patch selects the **original exec command**. No migrations or provider/media changes need undoing.
4. Preserve evidence/lock records; only remove a stopped socket after ownership/type/inode verification. Do not indiscriminately remove a socket/lock or switch an in-flight client to another endpoint.

D ACKs the frozen TCP/UDS/auth/fallback contract and leaves defaults off. F handoff: review CCR-D-01 and staged patch after A/C, record peer ACKs/merge SHA, run integrated Host gates and Windows auth/loopback tests. Implementation commit is reported in Agent D's delivery message and Git history; this document deliberately contains no self-referential commit SHA. No PR merge/push or shared service reconfiguration was performed.
