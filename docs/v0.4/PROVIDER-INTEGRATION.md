# v0.4 Provider Integration and Operation

## Application behavior

An authenticated caller creates a business Session through the existing Go POST /api/v1/live-sessions. The Backend atomically captures the current enabled defaults using existing userconfig.Capture, stores an immutable0.3 binding and a private owner/room-context mapping. Configuration changes after creation affect future Sessions only, even if Start is delayed. A Session is a24h lease from capture; there is no renewal.

Start uses the Go SessionIntegration.Prepare hook to check expiry and load capture-time room context without adding fields to the frozen1.1 DTO. Runtime resolves /internal/v0.4/sessions/{id}/binding, whose identity comes from the stored Go mapping. It never trusts browser-supplied identity or reads experiment credentials. The response is backed by existing userconfig.Resolve and is not relayed publicly.

Supported integrated bundle for this gate: VERIFIED DeepSeek with the captured Key/model/maxTokens/optional temperature; local XiaoYa preset xiao_ya / xiaoya-default at speed1; SoulX plus its matching selected GPU_WORKER. Other generic profiles can still be saved, but this integration rejects unsupported providers/parameters explicitly. In particular it does not claim secure openai-compatible Runtime endpoint consumption or XiaoYa speed adaptation. No personal uploads or voice cloning are enabled.

Runtime instantiates one bundle per Session, using existing Streaming LLM, Sherpa synthesis, GPU runtime_adapter and consumption-aware output wrappers. Plaintext credentials go to the LLM client only. Worker receives its existing private inference authentication and media, never LLM Keys. Formal SoulX preparation requires a real-gpu Backend READY probe, matching avatar cache, both physical ACLs, a successful private Worker handshake and matching pinned asset identity. Simulation is rejected even if a development registry permits it. A selected Worker already assigned in this Runtime returns overload; there is no multi-Runtime distributed allocator claim.

No initial Lightweight fallback is allowed. After successful startup, existing generation fence, Worker Epoch, FORCE, Lightweight degradation and bounded recovery are retained. The summary and static warning/degraded/recovered events reflect the actual adapter state. A degraded Session can continue Speak. Worker health is separately visible in settings. Profile default/verification does not prove current Session health.

The lease watchdog stops60s BEFORE expiry and rejects new commands inside that shutdown margin; no hot renewal or hot replacement. Stop, failed preparation/start, terminal events, Runtime shutdown and periodic Backend reconciliation release the encrypted snapshot. Runtime clears its held LLM credential and Session/cache/task references on cleanup. Unstarted bindings expire normally. Failed service release is retried while Runtime monitoring continues and reconciled after terminal events/expiry. A Runtime process crash loses memory; an active Go Session can remain stale until failure handling/expiry, and its UI summary reports Runtime unavailable.

## Operator bootstrap

Do this once as the deployment administrator; ordinary users only use the HTTPS UI.

1. Apply additive migrations including000004_session_integration.sql using the existing migration runner. Back up the business DB first. Never reuse a business DB for tests.
2. Use the existing config-bootstrap for the AES keyring and distinct configuration identity/worker tokens. Create an additional private random Runtime control token; it must differ from identity, binding and Tool tokens.
3. Create the single-operator adapter via backend/cmd/operator-bootstrap. Provide the password through stdin (12..72 UTF8 bytes), never argv. The tool bcrypt-hashes it, creates a0600 file and refuses overwrite. Flags: --out /private/operator.json --username operator --tenant existing-tenant --user existing-user. Distribute the login password through the administrator's normal private channel.
4. Register the existing physical Worker in both existing registry formats; do not modify the Worker model, weights or protocol. Registry scopes must match the operator's tenant/user. Backend uses managementPort/tokenFile; Runtime uses registryVersion1.0, port/tokenFile, avatarRef and assetSHA256. Use loopback private tunnels for cross-host service connections.

Backend operator environment:

```text
APP_ENV=production
SESSION_BINDINGS_ENABLED=true
CONFIG_PUBLIC_ORIGIN=https://your-existing-public-host
CONFIG_KEYRING_FILE=/private/keyring.json
CONFIG_IDENTITY_TOKEN_FILE=/private/identity-token
CONFIG_WORKER_TOKEN_FILE=/private/config-worker-token
AUTH_OPERATOR_FILE=/private/operator.json
RUNTIME_CONTROL_TOKEN_FILE=/private/runtime-control-token
GPU_WORKER_REGISTRY_FILE=/private/backend-registry.json
AI_RUNTIME_URL=http://protected-runtime:8000
# Existing DATABASE_URL, REDIS_URL and INTERNAL_API_TOKEN remain required.
```

Runtime operator environment:

```text
APP_ENV=production
SESSION_BINDINGS_ENABLED=true
CONFIG_BACKEND_URL=http://protected-backend:8080
CONFIG_WORKER_TOKEN_FILE=/private/config-worker-token
RUNTIME_CONTROL_TOKEN_FILE=/private/runtime-control-token
GPU_WORKER_INFERENCE_REGISTRY_FILE=/private/inference-registry.json
SESSION_PROVIDER_STATE_DIR=/private/runtime-provider-state
TTS_MODEL_DIR=/already-installed/xiaoya/model-directory
MOCK_MEDIA=false
WEBRTC_ENABLED=true
# Existing Redis events and TOOL_BASE_URL/TOOL_TOKEN remain configured.
# LLM_API_KEY / experimental .private files are NOT required or consumed.
```

Retain the original accepted media output configuration. This gate does not automatically change RTMP publishing targets or activate live-platform credentials. New-path headless and dual-output RTMP decoding and short recovery have now been exercised independently; see AGENT-A-ACCEPTANCE.md. Prior lab/one-hour evidence is not substituted, and quantitative speaker-loopback lip-sync/platform ingestion are not claimed.

Production same-origin TLS ingress fragment:

```nginx
location ^~ /internal/ { return 404; }
location /api/ {
    proxy_pass http://protected_backend;
    proxy_buffering off;
    proxy_read_timeout 3600s;
}
```

Terminate HTTPS with a trusted certificate; do not expose the protected Backend/Runtime/Worker listeners separately. Do not log request/response bodies, cookies or Authorization on these paths. The loopback self-signed acceptance fixture is test-only.

## User flow

Open settings, log in, add DeepSeek with a NEW Key, run the real server-side test, then select that verified version as default. Save/select XiaoYa (speed1), the authorized logical Worker, and SoulX referencing that Worker profile. Create a Room using owned Avatar/Voice resource labels and then create/start a Session. Provider selection comes from the pinned user defaults; the console explicitly shows its actual bundle/version/capture/expiry. Later credential updates require a fresh successful connection test and default selection and affect only new Sessions. Stop via the normal Go API and await ENDED. Users do not edit Runtime .env or SSH into GPU.

## Feature/review handoff

First hooks commit:8bc89bf on codex/v0.4-session-integration, isolated from main. Agent B should consume the existing authenticated Go ownership path and Runtime speak API; integration-specific logic lives in runtime/app/session_binding.py. runtime/app/session.py changes are limited to the agreed per-Session factory/maxQueue hook and static preparation-failure code. No Agent B code is merged. Frozen contracts and generated1.1 DTOs are unchanged. New0.4 machine contract is session-integration.openapi.json; its generated frontend types are in features/settings/integration-generated.ts. The private extension is described separately in session-integration.internal.openapi.json; it must never be imported into browser clients.

## Real configuration probes

The existing configuration test operation now dispatches the supported local providers to real checks. TTS sends only the fixed XiaoYa preset through the private, Runtime-control-authenticated POST /internal/v0.4/provider-probes/tts. The Runtime synthesizes a short Chinese phrase using installed Sherpa assets, checks nonzero PCM and returns sample count/rate. It bounds synthesis to15s and serializes probes; it never calls a GPU or sends credentials in this request. GPU_WORKER reads existing management /v1/status through the trusted physical registry and checks gpu/UP/READY/avatar cache. AVATAR verifies its owned Worker-profile reference and matching physical avatar cache. These two checks prove readiness; Session rendering acceptance is separate. The existing per-owner test limiter/version CAS and verification/default reset on failure remain authoritative.

Bound DeepSeek failures propagate instead of entering the legacy input-echo fallback. Authentication errors are PROVIDER_AUTH_FAILED, other LLM errors LLM_FAILED; STOP policy fails and cleans the Session. Cleanup tracks in-flight tasks, releases the binding with retry, clears the held key and closes media/Avatar under bounded waits.

## Browser and responsive console

The layout uses Tailwind classes, fluid Flex proportions, responsive stacking and width-safe controls. The former max-w-7xl limit is removed. Preview defaults to object-cover without distortion; 完整画面 switches to object-contain. Cover may crop the edges to fill the16:9 frame. The window is resized through responsive layout, not a transform scaling the whole page. Motion provides short navigation/page/sidebar transitions with reducedMotion=user; media frames, polling and lifecycle commands are not animated. No custom CSS file is added; the existing CSS entry keeps only the Tailwind import. Motion layout/animation features are loaded as a separate lazy chunk. See [Motion accessibility](https://motion.dev/docs/react-motion-config) and [lazy feature loading](https://motion.dev/docs/react-lazy-motion).

WebRTC requires browser support and permitted network access. In native Chrome acceptance, an enabled WebRTC leak-protection extension blocked RTCPeerConnection before any HTTP offer. The user disabled that extension, after which the existing browser path connected and rendered SoulX. Do not disable user browser privacy protections automatically. Server ready events indicate the media producer is ready, not proof that the browser is playing.

## Isolated deployment findings

The real acceptance used GPU-hosted Go CPU processing, school-linux Runtime/XiaoYa, an existing RTX3080 Worker, independent temporary PostgreSQL/Redis and a loopback HTTPS proxy. Mac/school DNS returned reserved proxy addresses for DeepSeek; the SSRF guard correctly rejected them. Moving the isolated Go CPU fixture to the authorized GPU host restored valid public DNS; no allowlist or TLS check was weakened. Redis uses the frozen dh.runtime.events.v1 name on the independent Redis instance. An initial custom fixture stream was corrected rather than changing Runtime contracts. There is no global production provider/default switch.

## Headless RTMP and recovery operation

An administrator configures the existing protected Runtime sink using RTMP_ENABLED=true and a private RTMP_PUBLISH_URL (or RTMP_URL plus RTMP_STREAM_KEY), keeping MOCK_MEDIA=false. Optional WEBRTC_ENABLED=true permits a preview alongside publishing; an actual browser subscriber is no longer required for a bound SoulX Session to publish. Ordinary users continue creating and controlling Sessions through authenticated Go APIs. Browser clients never receive the publish secret. The isolated gate used a loopback MediaMTX destination, H.264720x1280/25fps and AAC48kHz stereo. Default production destinations are not switched by this change. LIVE_PLATFORM credential/profile consumption is not added by this gate. For real platform deployment, retain [RTMP secret isolation requirements](../../runtime/RTMP-SECRET-SECURITY.md), including process-argument visibility.

The business wrapper grants Worker credit after WebRTC frame consumption or a completed RTMP encoder pipe write, and captures the original link for each credit task. Queue admission, a filler tick and process liveness alone do not grant credit or prove platform acceptance. A headless Session drains its publishing sink; a missing optional preview is not reported as failed playback. FORCE cancels pending credits and retains the existing generation fence. A configured WebRTC receiver keeps the original fanout drain behavior.

For later Worker loss, keep the original binding. The existing bounded reconnect policy allows a candidate within300s/24 attempts; current fallback speech stays Lightweight and visibly DEGRADED. A ready candidate is promoted only at a future speech boundary, using the new Worker Epoch. Exhaustion leaves explicit degradation; Stop and a new Session are required for a new admission rather than an undefined unlimited retry or hot-switch. The real restart in this gate took about98s. RTMP ingest recovery separately uses its existing FFmpeg supervisor/backoff and does not block a connected WebRTC preview. Private sink diagnostics/decoded readback establish recovery; FFmpeg liveness alone does not.

The24h real lease soak is deferred at the user's request. The v0.3 lease limit and60s pre-expiry shutdown remain enforced; no renewal version is invented.
