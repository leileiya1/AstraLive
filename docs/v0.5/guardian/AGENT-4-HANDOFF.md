# Agent 5 → Agent 4: independent Output Guardian v1

Status: **OUTPUT GUARDIAN BLOCKED**. Implementation and local process/media evidence are reviewable; production isolation, continuous short segments and WebRTC completion are release blockers. Keep the existing `OUTPUT_FENCE_UNPROVEN` guards in both production entrypoints.

## Ownership and scope

New `output_guardian/` is an independently launched service. New `runtime/app/guardian_media.py` is its decoded-media IPC adapter. No answer CCR, Outbox migration, planner, main/Session/Provider Binding, SoulX, GPU binary wire, Worker epoch, PCM format, PTS field or Credit algorithm is changed. Agent 4 retains the formal Session lifecycle and entrypoints.

One service owns exactly one registered tenant/owner/Room. A trusted registrar installs the stable Guardian ID, exact producer incarnations, different IPC credentials for CONTROL and each producer, and a read-only PostgreSQL credential. IPC tokens are separate from backend CONTROL/RUNTIME_JOURNAL/OUTPUT_GUARDIAN, Provider Binding and Worker tokens. JSON identity fields are comparisons, never self-registration. Use AF_UNIX with separate OS UIDs/network namespaces and no Runtime publishing egress. No browser receives these credentials.

Guardian owns the ephemeral publish secret, FFmpeg/libav publisher child, RTMP Socket, private MediaMTX API, WebRTC Peer/DTLS/SRTP resources and final Permit check. The child uses PyAV's FFmpeg libraries rather than the legacy FFmpeg CLI: URLs pass through an inherited private FD, never argv/state/logs. The trusted RTMP decoder has a separate read credential and begins its reported video suffix at an IDR; the server recording must cover any skipped, undecodable join prefix. Legacy FFmpeg processes are fenced by the ingest server, not their own close assertions. The ingest API has a separate ephemeral Basic credential; loopback access alone does not authorize it. Supervisor kills its complete process groups; Linux parent-death signals and an independent child watchdog also seal publishers after parent death.

## Integration sequence

1. Provision dedicated MediaMTX v1.21.1 with only RTMP and API on loopback in Guardian's namespace. Disable overridePublisher and other ingress, including MoQ. Never use a shared server for this harness. Mount server-owned recordings read-only in Guardian (two-container configuration).
2. Start closed. Guardian obtains an OS lock and a session PG advisory lock for the Room, reconciles owned children using PID + creation time + private child marker, kicks old Room publishers through MediaMTX and verifies absence. Unknown PID identity, corrupt tombstones, SQL loss or unprovable server state fails closed. No Permit/secret is restored from disk. Startup retry waits only for the dedicated server; it never grants media.
3. Backend allocates PENDING_INSTALL, authenticates the physical Session and records its producer incarnation. CONTROL calls install with the pending binding and next Room outputBindingVersion. Guardian validates SQL, closes outputs, independently observes absence of old publishers twice, fsyncs fence.json and returns proofRef.
4. Agent 4's trusted bridge uses the receipt as evidenceRef for existing ConfirmOutputFence under the registered OUTPUT_GUARDIAN backend principal. This service does not hold a backend management token or write business SQL. Then prepare/install the existing Runtime fence and call ConfirmRunFence using the backend's actual fence receipt ID. Reconcile lost ACKs against persisted versions/receipts; do not blindly repeat ConfirmOutputFence. Guardian install is non-replayable after a version is used. Restart requires a fresh physical barrier/version, even for the same pending epoch.
5. After one-use journal START and SQL slot/Attempt binding, producer obtains the existing ≤1000ms SQL Permit. CONTROL calls bind with exact Attempt, command, utterance and actual Session generation. Guardian independently queries SQL; it never trusts a Runtime-supplied TTL/START assertion. STARTED inbox, active slot and executor must match. CONTROL owns generation binding; Runtime cannot advance it.
6. Runtime uses GuardianMediaOutput for PCM/RGB. Operator config fixes media format. IPC uses its own contiguous audio ordinal because TTS sentence chunk sequences may reset; PCM bytes remain unchanged. Video pts_us reaches the encoder unchanged. No Worker generation/Credit is invented here. accepted=true means handoff only, never decoded completion or GPU credit.
7. Producer renews with newly issued Permit IDs at roughly 100–200ms cadence. Guardian independently polls SQL at ≤100ms intervals with 200ms query timeout. Local 5ms expiry and child expiry are independent. Deadlines start before the SQL request and subtract 100ms. Lease renewal cannot extend an old Permit. Late renewal after Stop/expiry/install/process replacement cannot revive delivery. Pending writes capture actual child/pipe identity; the child checks the immutable full identity too.
8. CONTROL Stop fsyncs the local tombstone before awaited cleanup. Backend Stop remains durable truth and revokes issuance; Guardian polling independently sees it. Send Guardian Stop promptly. No live lease/Permit is required. Await process/socket/peer shutdown plus trusted server observation before physical cleanup ACK. Historical-run Stop cannot revoke a different current Run.

## Completion and remaining blockers

Guardian owns a transparent RTMP chunk relay and the real server Socket. It forwards original media/PTS, checks local authorization at each socket handoff, and withholds only terminal FCUnpublish/deleteStream/closeStream while waiting for independent decode. Codec close can flush interleaved tail packets without prematurely destroying the server path. Stop/expiry closes the relay immediately; no media, silence or fixed A/V delay is added.

finish flushes the finite Attempt encoder, then requires complete ordered coded-packet coverage and actual independent audio/video decoding. MediaMTX recording provides a prefix; a trusted RTMP reader provides a suffix. Both must match the encoder's exact sequence, their union must have no hole, and independent decoders must cover the full audio/video range after subtracting overlap (AAC overlap uses its 1024-sample codec frame). Duplicate/missing packets, head/tail loss or decoder errors yield DRAIN_UNKNOWN. Receipt includes full video PTS list, PCM sample range, observer identity and hashes, scoped to the exact Attempt.

This proves dedicated local RTMP ingest, not official-platform/audience playback. Agent 4 must map receipts to the existing trusted checkpoint/range verifier without inventing frozen wire DTOs or bypassing completion checks. decodedAudioSamples/decodedVideoFrames express covered source range after overlap removal; prefix/suffix raw decode counts are also returned.

Media blockers remain:

- MediaMTX's pinned RTMP reader analyzes a two-second timestamp window (gortmplib v1.0.3 reader.go). A new publisher per Attempt cannot reliably complete shorter segments; a 400ms test intentionally stays UNKNOWN. Do not hide it with fixed silence/A/V delay, timeout growth or GPU PTS changes. A long-lived, permit-fenced Publisher/encoder with correlated per-Attempt ranges requires further additive design/testing.
- The finite CPU path currently requires first video PTS=0 and starts its audio sample clock at zero. Nonzero initial video PTS is rejected without rewriting it. Existing Session-wide PTS and continuous PCM origin alignment must be handled in the same long-lived Publisher design; the zero-origin synthetic result does not establish full Session timeline compatibility.
- WebRTC receives real audio/video and physically closes on expiry. Existing track counters are not decoded-peer range receipts. If WebRTC is required, finish returns UNKNOWN even if RTMP passed. External ICE/TURN and a trusted remote receiver completion adapter remain unimplemented; local-only ICE is explicit in output_guardian/webrtc.py.

## Private IPC v1 (not durable-live-1)

POST /guardian/v1/{op} on AF_UNIX, exact Authorization: Bearer token, JSON ≤9MiB. Duplicate keys/extra fields rejected. No public TCP IPC, query token or cookie auth. Unknown producers cannot self-bind. Errors contain static codes. finish has a 2s server observation/cleanup budget and a 3s IPC read budget; these do not extend the ≤1s Permit or change Worker/media timeouts.

Binding = {tenantId, ownerId, roomId, runId, runEpoch, sessionId, outputBindingVersion, producerIncarnation}.

Attempt = {binding, attemptId, utteranceId, generation, commandId}. Every frame repeats and matches it exactly. Epoch/binding/generation are positive JSON integers; bool/float rejected.

| Operation | Principal | Exact JSON fields | Success |
| --- | --- | --- | --- |
| install | CONTROL | binding | CLOSED_FENCED, proofRef, binding, barrier |
| bind | CONTROL | attempt, permitId | AUTHORIZED |
| renew | bound producer/CONTROL | attempt, permitId | AUTHORIZED |
| media audio | bound producer/CONTROL | attempt, kind=audio, sequence, payload=base64 PCM16LE mono | accepted (not checkpoint) |
| media video | bound producer/CONTROL | attempt, kind=video, pts_us, payload=base64 RGB24 | accepted (not checkpoint) |
| offer | bound producer/CONTROL | attempt, sdp | answer SDP |
| finish | bound producer/CONTROL | attempt | LOCAL_MEDIA_DRAINED plus all required evidence, otherwise UNKNOWN |
| stop | CONTROL | runId | CLOSED_FENCED after trusted cleanup |

GuardianMediaOutput.interrupt(newGeneration) closes local admission and requires CONTROL rebind; it cannot authorize a generation. Its stop() closes IPC only: Agent 4's Stop path must call Guardian CONTROL Stop. Do not reinterpret BoundConsumptionMediaOutput's WebRTC-OR-RTMP consumption as durable completion or modify the validated Credit algorithm.

## Deployment / OS gate

See infra/guardian/{compose.yaml,guardian.service,runtime-isolation.conf,readonly-role.sql,config.example.json}. Protect config/secrets; state is Guardian-owned mode 0700. Registrar provisions separately permissioned copies of producer token for verifier and Runtime UID. IPC directory allows Runtime group traversal/connect, but not socket replacement or state changes. Runtime must not mount Guardian config/state/recordings, Docker socket, host PID namespace/networking or production publishing keys.

Linux drop-in removes AF_INET/AF_INET6 for Runtime and descendants; AF_UNIX proxies are needed for Backend/Worker/LLM. Container acceptance Runtime probe uses network_mode:none and is not a finished Runtime deployment. Guardian/MediaMTX share a separate namespace; ingest/API/auth ports have no host mappings and bind loopback. Run UID/capability and negative credential/port reachability tests from an adversarial Runtime before approval. Configuration inspection alone proves no isolation.

The tested macOS host has no Docker/Podman executable or daemon in the inspected paths. Linux/container isolation and arbitrary external-platform key revocation are NOT TESTED. No existing real Runtime/Worker/external livestream was stopped/reconfigured. A legacy publisher holding an external platform key outside this controlled namespace remains a blocker: revoke/move that key and prove the external connection severed before LIVE.

## Reproduction

From repository root create a dedicated Python 3.12 venv, install output_guardian/requirements.txt and requirements-test.txt. Download pinned MediaMTX outside the repo. Set GUARDIAN_TEST_MEDIAMTX to its binary and GUARDIAN_TEST_PG_BIN to a PostgreSQL ≥16 bin directory, then run:

```
.venv-guardian/bin/python -m pytest output_guardian/tests -q -s
```

Fixture starts a fresh loopback PG cluster, applies unchanged 000001–000006 migrations, creates a unique guardian_test_* database per case, starts dedicated MediaMTX on dynamic loopback ports and uses CPU synthetic media only. It cleans up its own resources. Fixture SQL simulates existing backend activation/Permit writes; formal Agent 4 bridge and Provider/Session reconstruction are not validated. See acceptance report and raw evidence alongside this handoff.
