# SoulX immutable segment staging: B design review

Date: 2026-10-12. **PROPOSAL ONLY / NOT APPROVED / NOT IMPLEMENTED.**
Reviewed integrated source `48eb0387f4e0f7db08ca8b64d3ae02c2207a9f57` and frozen `v0.5-frozen-1`. B branch was clean at `dda7936` before this owned evidence/proposal addition. Frozen contracts and production source remain unchanged. No SSH, model installation, GPU operation, or real-media run was performed for this review.

## Finding

Unchanged internal TCP1.1 does not provide an ordinary complete-segment precommit staging operation. This is an interface gap, not evidence that the Timeline/Continuity software has no value.

- `gpu_worker/service.py:108-112,179-195`: four in-flight frames; each Credit replenishes a slot **and** inserts original RGB into `adapter.committed`. GenerationComplete is emitted only after every frame is credited as consumed.
- `gpu_worker/validated/adapter.py:8-16,170-183`: each new generation restores the last nine **consumed** frames, or the portrait when fewer than nine exist. Restoration occurs at generation start, not at every inference block. The native model owns speculative latent evolution within the generation.
- `gpu_worker/validated/adapter.py:99-109`: cancellation clears queued audio/video but preserves committed pose history. False preplayout Credits therefore survive cancellation and can influence the next generation.
- `gpu_worker/validated/async_link.py:85-97` and `gpu_worker/validated/prefetch.py:85-88`: existing completion waits for the consumed acknowledgement; it cannot serve as a generated-artifact final marker.
- C `runtime/app/narration_segments.py:85-95` explicitly rejects this renderer before staging; this rejection is correct. B's earlier real GPU ledger test uses incremental rendering after commit and a test journal; it cannot establish C's full READY or SQL integration.

The frozen READY requires complete immutable PCM **and video** with final marker, validated counts/ranges/hashes/provider provenance before any sink handoff. Neither receiving four frames nor generating the PCM alone satisfies it. Splitting speech into <=160ms pieces does not fix the completion API and is not a semantic boundary solution.

## Reproducible local diagnostic

[Probe](evidence/agent-b/safe-staging/probe.py) invokes unchanged production `Worker.handle`, native TCP framing and actual CPU libx264 encoder. The adapter/model frames are explicitly synthetic; no Torch/model inference, Runtime, SQL, Chrome, RTMP or audience playback is involved. [Result](evidence/agent-b/safe-staging/result.json) records exact production/probe hashes.

Environment: macOS27.0.1 arm64, Python3.12.13, PyAV17.1.0, NumPy2.5.3. [Raw final output](evidence/agent-b/safe-staging/run.log) is retained. No dependencies were installed or shared environment changed.

```sh
PYTHONPATH=/absolute/AstraLive-agent-f /path/to/runtime-python \
  docs/v0.5/evidence/agent-b/safe-staging/probe.py \
  --repo /absolute/AstraLive-agent-f \
  --output /new/result.json
```

Exit0, six assertions PASS:

1. A synthetic960ms/24-frame segment sends exactly frames0..3, then remains blocked during the200ms observation without Credit; Health remains responsive.
2. No Credit leaves consumed pose empty.
3. Deliberately exercising the rejected early-Credit workaround for nine unplayed frames records nine consumed poses in the actual service branch.
4. CancelGeneration retains those nine falsely acknowledged poses.
5. Even a160ms/four-frame generation has no GenerationComplete before consumption credits.
6. Normal consumption credits complete that short generation.

This proves the local control coupling and rejects the workaround. The200ms observation is not a GPU timeout/performance measurement. Native restore consequences are source-reviewed; no synthetic model is claimed to validate visual continuity. Two initial probe attempts failed because the diagnostic's minimal Health status omitted `lastError`; the fixture was corrected without production edits before this final run.

## Concrete options

| Option | Effect | Decision |
| --- | --- | --- |
| Keep original TCP path with Continuity off | Existing verified streaming behavior remains available; no new strict READY claim | Valid compatibility fallback |
| Explicit Lightweight2D Continuity experiment | Exercises durable plan/cursor/Timeline with complete synthetic/CPU artifacts | Already tested; not SoulX |
| Early Credit, larger send queue, READY after PCM/first frames, or automatic renderer downgrade | Violates consumed-pose or complete-artifact semantics; could mislabel the selected provider | Reject |
| Versioned capability for immutable SoulX staging | Separates transport receive credit from consumed-pose evidence while preserving strict READY | Recommended next design/implementation gate |
| Independent offline native inference staging engine | Avoids streaming service credit coupling, but introduces a new owned inference path and explicit pose commit/cancel API | Larger change; cannot be asserted compatible without review |

## Minimal proposed CCR scope (F numbering/approval required)

Suggested identifier **CCR-BC-002**, distinct from the unapproved early-Credit CCR-BC-001. Do not activate it through configuration or silently add messages to TCP1.1.

1. **Additive capability/version negotiation**, default absent/off. An explicitly selected staging-capable client/Worker pair may use the new mode; original1.1 framing, authentication, Credit meaning, four-frame streaming window, cancellation, and public business contracts stay unchanged. A missing/mismatched capability fails closed for SoulX Continuity. TCP remains sufficient; QUIC is unrelated.
2. **Separate generated receipt from sink consumption.** A named received/staged acknowledgement releases the bounded four-frame network window only after immutable sequence/PTS-validated artifact storage. It never appends consumed pose, emits sink_consumed/completed, or advances a semantic cursor. A distinct generation-produced final descriptor proves audio EOF, final video sequence/count/range and artifact integrity. Existing GenerationComplete retains consumed semantics in compatibility mode.
3. **Preserve original native RGB for later pose commitment.** Worker retains a bounded per-attempt original-frame artifact until play/cancel/reconcile; decoded H264 RGB must not silently substitute for the original VAE pose. Runtime's complete PCM/video artifact and Worker retention have explicit duration/byte/lease budgets, including pipeline/inference memory. Overflow rejects before READY. Current C bounds8s/160MiB are not sufficient proof of total GPU/host memory capacity; choose and test an explicit short-segment limit first.
4. **Consume pose only after committed sink evidence.** Runtime maps the complete business identity plus Worker epoch/generation to the staged attempt. After B ledger installation and actual named sink consumption, a separately fenced monotonic pose-consumption acknowledgement advances only proven frames. Required-sink disagreement/partial tails remain explicit UNKNOWN; select a reviewed watermark policy, do not invent audible proof. No pose effect from merely generating, receiving, READY or ledger commit.
5. **Cancellation and next-generation fence.** One active staged attempt/lease initially; no independent speculative next generation based on unplayed media. FORCE/Stop cancels staged eligibility, discards unconsumed artifacts/latents at the safe model boundary, preserves only acknowledged consumed pose and refuses late received/consumed/final messages from the retired tuple. Missing consumption evidence after crash stays UNKNOWN; no replay/reconstruction of old speech. Reconnect/Worker restart preserves existing new-incarnation rules.
6. **Ownership/dependencies.** A reviews durable proof/retry fields; B owns Timeline/sink mapping; C owns artifact orchestration/READY and lifecycle; Worker owner (E or a separately assigned owner) owns native/TCP capability changes. D's Go→Python IPC cannot fix Python→GPU staging. F owns CCR authority, integration and independent acceptance. B will not edit Worker code or C orchestration under current ownership.

**Auth, release and rollback boundaries:** all new messages stay on the existing authenticated Session/Worker-incarnation lease; an opaque staged-attempt ID never grants ownership or bypasses the current binding/epoch checks. Duplicate same-identity/hash receives are harmless; conflicting hashes, future/gapped consumption and retired IDs fail closed. Receiver storage ACK and pose ACK are separate retry domains. Original RGB may be released only after its defined consumption watermark or fenced artifact discard, never because a packet was received. An acknowledgement/crash ambiguity blocks the next attempt until A/C reconciliation; preserve consumed history when it is known, retain UNKNOWN when it is not. Capability rollback first stops/reconciles the active staged attempt and releases its storage, then starts a fresh original1.1 lease with Continuity off; do not hot switch an active staged generation into legacy streaming. Keep the original Worker release and captured-provider configuration available.

## Acceptance before enabling the capability

Keep the original Credit regression suite. Add deterministic control tests for staged receive vs actual consumed history, EOF/final counts, contiguous IDs/PTS, duplicate/conflicting acknowledgements, budgets, Stop/FORCE and late-message rejection. Then run an owned real-GPU short stage with **no sinks**, prove complete immutable artifact and unchanged consumed history; cancel it, start a future attempt and inspect pose restoration. Only then run commit/play, partial interruption, answer/resume, all required sink proof, real Chrome/local RTMP, and normal cleanup. Provider identity, true inference, hashes, source pin and clock domains must be recorded. Long busy latency/naturalness is a later gate, not inferred from this diagnostic.

The existing frozen READY and semantic cursor contracts need no relaxation. Implementation starts only after the affected owners and F approve the concrete transport/pose addition and the user authorizes any frozen-contract revision required by the integration instruction.
