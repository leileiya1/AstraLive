# CCR-BC-003: opt-in real GPU inference budget profile

Status: explicitly approved by user on2026-10-12; exact additive schema/owner review and new freeze manifest pending. Original v0.5-frozen-1 bytes and existing staging profiles remain unchanged.

## Actual evidence

Existing Linux RTX3080 10GiB, exact Worker source1d389169/release9b920ecff31222063ac7d20b12d79cbb8b437de22a812a4056ddcd21ce291e15. Actual prerecorded XiaoYa 29440 source samples (1.84s), TCP1.2 short profile. First inference reports baseline4316367872 bytes, incremental allocated peak871138816 bytes (830.78MiB), incremental reserved peak0. Fixed cap536870912 bytes (512MiB) is exceeded. Worker host buffer peak113758208 bytes is below268435456 cap; RGB786432 is below50331648. Failure is RESOURCE_CAP_CHECK/GPU_ALLOCATED_CAP, not an encoder or header error. No commit, sink publication or consumed pose proof. Negative gate retained; Worker stopped safely.

## Requested amendment

Add explicitly selected short and 8-second GPU profiles with increment allocated cap1073741824 bytes (1GiB), retaining the existing512MiB profiles and all their values. Keep original native/audio/network/CPU/RGB/duration/lease bounds, proof DTOs, hash domains, epoch rules, original TCP1.1 and default-off switches. The new profiles must receive distinct limits revision names, actual new-short GPU evidence before new8s, independent owner ACK and a new immutable freeze manifest. A profile increase is an allowance for measured existing native inference, not an optimization or a latency claim. Reject profile mismatch before READY; no automatic fallback or perattempt growth.

The proposal leaves193.22MiB above the measured short peak; this is a bounded starting cap, not proof of long GPU stability. Real short and8s resource/lease/cancel gates and business Golden still must pass. If they exceed this allowance, stop and diagnose rather than growing it silently.

## Review and rollback

A owns exact profile/schema/helper changes; B Worker config and negotiation; C captured config/Runtime; F frozen addendum and real evidence. Before approval only read-only review and current-profile software work continue. Preserve original profile values, their regression vectors and the old freeze manifest. Revert operator profile/flags only after sealing/fencing the Session, native safe release or physical retirement and explicit UNKNOWN disposition. No ambiguous speech replay.
