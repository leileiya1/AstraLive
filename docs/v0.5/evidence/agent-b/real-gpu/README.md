# Real GPU evidence index

The primary scope and all favorable/adverse comparisons are in [AUDIO-MASTER-TIMELINE.md](../../../AUDIO-MASTER-TIMELINE.md).

- baseline-1: default-OFF short real GPU control, clean source738f152.
- v2-short-1: intentionally stopped INVALID trial; Python frame address reuse caused false credits. Do not count duration or frames as acceptance.
- v2-short-2: corrected short A/B, clean sourceb19e537; regression in first-frame P95 retained.
- v2-soak-1: 1807.83s uninterrupted clock soak, source3dff41e;65 FORCE,257/260 verified PCM matches. The three coverage gaps remain unverified.
- ledger-short-1: 121.63s final ledger seam preflight,15 natural boundaries, sourcee2a8fa2.
- ledger-soak-1: 1806.81s uninterrupted final media implementation, sourcee2a8fa2;222 natural boundaries,222/222 waveform matches,222 stale epoch injections absent from both sinks. The journal is a TEST_DOUBLE, not SQL/A/C durability.

Each run stores sourceSHA, dirty state and runtime source-file hashes, Chrome raw statistics, raw sample/cycle/avatar/driver logs, recording size/hash/path, and applicable packet/content/resource audits. Rotated avatar logs are all included. Long raw logs are gzip-compressed; use gzip -dc for inspection. previews are selected8s excerpts only. Full recordings persist at the absolute paths in recording.json outside Git. Frame markers are test instrumentation applied after genuine GPU inference, not production overlay or synthetic avatars.

resource-audit.py documents the audit used before moving original /tmp directories to cache. Its remote time window uses original samples.jsonl macOS birthtime and500ms tolerance; resources.json retains the computed window. Re-running after moving/copying files requires that stored original window, not the new file creation time. Process RSS/CPU is sampled during playback, excludes Chrome/FFmpeg, and is not a deployment-wide accounting. Worker status and resources are observations, not viewer playback proof.

ready-after.json proves the user-owned isolated Worker was left READY/UP and idle after normal Stop. All recordings ran against the same final Worker incarnation. Provisioning source/weight download manifests are fixed official upstreams; no private token or signed CDN URLs are archived.
