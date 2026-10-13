# Real Platform RTMP Readiness / Production Hardening

Date: 2026-10-08. Primary host: school-linux.

## Current accepted RTMP state

**ASTRALIVE V0.1 CORE MVP ACCEPTED** and **READY FOR REAL PLATFORM RTMP**
remain the current accepted local state. The authoritative
[final summary](../integration/evidence/rtmp-final/final-summary.json) reports
911.9 seconds of one dual-output Session, all checks true, no failure events,
and normal Stop/Cleanup. Existing reconnect, 300.2-second idle, 20 FORCE,
headless output and A/V synchronization evidence is retained. No full local
15-minute acceptance was repeated in this phase.

## Credential security and argv risk

[Security report](RTMP-SECRET-SECURITY.md) records the live fake-key experiment:
FFmpeg argv and ps expose the output key, cmdline is 0444, and school-linux has
no hidepid option. Same UID and root can read it; current default procfs also
allows ordinary cross-UID command-line access. No real credential was used.
Redacted logs are not proof of argv secrecy.

Production requires a dedicated locked `astralive` user, root-owned release
files, root:root 0600 EnvironmentFile, 0700 secret/state directories, no shared
UID, no real keys in Git/logs/evidence, and verified host-level hidepid=2 or
equivalent isolation on shared servers. Root and service UID remain trusted.
`ProtectProc=invisible` is additional service sandboxing, not protection from
host observers. Current school-linux configuration must not receive a real
credential unchanged. Templates are ready; operator deployment/verification
of this boundary is still required before credential installation.

Temporary secret files must be 0600 in protected volatile storage and removed
on exit/failure. Production launch creates no temporary secret files. An
optional protected, separate-UID localhost RTMP relay is documented for users
who require platform keys outside Runtime; it is not implemented here.

## Target configuration and platform profiles

Two mutually exclusive forms are supported:

```text
RTMP_URL=rtmp://host/app
RTMP_STREAM_KEY=<configured in protected file>
```

or a platform-provided complete `RTMP_PUBLISH_URL`, including path/query auth.
The complete URL is preserved; conflicting forms fail closed. HTTP URLs,
missing hosts, invalid ports, URL userinfo, fragments and whitespace fail
validation without echoing the target. Logs redact the full path/query; repr
excludes credential-bearing fields. Stderr redaction covers URL, key/path,
query values and encoded/decoded variants; diagnostics reapply it.

`RTMP_PLATFORM=generic` is the only profile implemented. It keeps 720x1280,
25 FPS, CPU H.264/libx264, yuv420p, AAC, 48 kHz stereo, 3000k video, 128k audio,
veryfast preset and 50-frame GOP (two seconds). Existing per-field environment
overrides remain; `RTMP_GOP` can override GOP and otherwise follows FPS × 2.
Unknown profiles are rejected. No assumed douyin/taobao requirements, APIs or
bullet-chat adapters were added.

`rtmp` and `rtmps` are valid target schemes. school-linux FFmpeg
8.0.1-3ubuntu2 lists RTMPS under **Output**. Preflight checks the actual chosen
binary, so an input-only or unsupported RTMPS build fails. Protocol listing
is build capability evidence, not an authenticated TLS/platform publish test.
Official platform TLS/certificate requirements remain to be verified later.

## RTMP Preflight

`PYTHONPATH=runtime <Linux Runtime venv>/bin/python -m app.rtmp_preflight`
performs checks before publishing:

- FFmpeg present; libx264/AAC/yuv420p/FLV available; selected output protocol.
- URL and credential form present; valid target/scheme/port; codec settings,
  even positive dimensions, FPS/GOP/rates/preset and reconnect bounds valid.
- Host DNS resolution and defensive secret redaction.
- No visible FFmpeg RTMP publisher; unreadable proc inspection fails closed.

Results contain only check booleans, `ok`, `publishes=false` and
`connectionVerified=false`. No target is sent to a subprocess or emitted.
DNS exceptions and FFmpeg capability output are not printed. Preflight does
not open a publish connection or establish account permission. Full-URL
configuration is treated as a supplied credential-bearing publish path; its
authentication cannot be verified without a later authorized platform test.

The production launcher holds a service-user flock before preflight and across
Runtime exec, and enforces one Session. Visible proc scanning cannot prove the
absence of remote publishers, other executables or hidden namespaces. The lock
and unique service ownership provide the local deployment boundary; a privileged
operator can bypass it.

## Output health and warning policy

RTMP diagnostics retain existing counters and add/standardize `enabled`,
`running`, `ffmpegPid` (legacy `pid` retained), `processStarts`, `reconnectCount`,
`writeFailures`, `targetFps`, `resolution`, `audioQueueMs`, `videoQueueMs`,
`audioDropped`, `videoDropped`, redacted `lastError` and `stderrTail`.
`connected=null` explicitly means unknown: FFmpeg process liveness does not
prove platform ingestion. `lastError` is the latest captured stderr diagnostic,
not a separately verified platform rejection.

`RUNTIME_MEDIA_METRICS_INTERVAL_SECONDS` enables server-side periodic INFO
JSON diagnostics (60 seconds in the template). The existing acceptance interval
variable remains a fallback. No frozen public API/Contract was changed.

Fanout drop totals remain metrics. Ordinary shedding logs only at DEBUG.
Per-sink/per-media `drop_rate = window drops / window offered items` uses
10-second windows. A warning requires **more than 10%**, at least 50 offered
items per window, for three consecutive active windows; warnings have a
60-second cooldown. Idle gaps of 20 seconds or more and low/healthy windows
reset sustained-overload state. The existing warning code reaches
`RUNTIME_WARNING` through the existing Session handler and includes rate,
window offers and drops. Latest-frame shedding, queues, workers, pacing,
generation invalidation, media clocks and reconnect logic were not rewritten.

## systemd and Mac independence

[Deployment template](deploy/astralive-runtime.service) and
[operator instructions](deploy/README.md) use a **system service**, independent
of SSH session lifetime, with explicit User/Group, WorkingDirectory,
EnvironmentFile, Restart=on-failure, startup rate limit, graceful SIGTERM,
45-second shutdown allowance, cgroup final cleanup, journal logging, restricted
filesystem/capabilities, disabled core dumps and initial single-Session resource
limits. systemd manages protected state/runtime directories. No actual user,
unit, host procfs policy or production environment was changed.

`systemd-analyze verify` passed on school-linux with the unprovisioned
`/opt/astralive/runtime/.venv/bin/python` temporarily substituted by
`/usr/bin/python3` for syntax verification. The original template correctly
reports the missing production executable; service deployment/permission and
sandbox acceptance remain operator gates, not claimed as completed here.

The production path is:

```text
school-linux -> AstraLive Runtime -> FFmpeg -> RTMP platform
```

Backend/Redis/Tool/model services must also be server-local or independently
hosted. Mac is an optional management preview only. RTMP does not depend on
WebRTC/browser, Mac launchd or SSH tunnels. A Mac-off real-platform observation
is a required later platform acceptance check, not executed in this phase.
Restart recreates Runtime, not an automatic prior Live Session.

## Regression validation

Command:

```bash
PYTHONPATH=runtime runtime/.venv/bin/python \
  -m unittest discover -s runtime/tests -p 'test_*.py' -v
```

Result: **79 tests, 68 passed, 11 opt-in skips, 0 failures, 0 errors**.
Includes target validation/full URLs, codec/profile overrides, secret repr and
diagnostics redaction, preflight failure gates/output protocol distinction,
sustained drop threshold/cooldown/recovery, delivery/metric retention, production
diagnostic scheduling and launcher preflight/lock rejection.

school-linux isolated targeted regression: **24/24 passed**. A short localhost
FFmpeg smoke with fake full publish URL passed preflight, H.264/yuv420p
720x1280/25 FPS, AAC/48 kHz/stereo, interrupt PID stability and normal Stop:
processStarts=1, reconnectCount=0, writeFailures=0. Source was staged in a
separate temporary directory and removed afterwards; actual Runtime deployment
was untouched. The smoke did not use Real LLM/TTS or a browser, and does not
replace their existing accepted evidence.

[Validation summary](evidence/rtmp-production/validation-summary.json),
[Runtime test output](evidence/rtmp-production/runtime-tests.log),
[remote targeted tests](evidence/rtmp-production/school-linux-targeted-tests.log),
[smoke result](evidence/rtmp-production/smoke-summary.json), and
[security observations](evidence/rtmp-production/security-summary.json).

## Remaining requirements for real platform

User/operator must select the platform, provide official publish URL/key,
confirm account publishing permission and official media/TLS requirements,
apply and verify deployment isolation before loading credentials, provision
server-only dependent services, and authorize the real-platform connection.
Then validate ingestion, playback, reconnect, Stop/Cleanup and Mac-off continuity.
No douyin/taobao connection, RAG, MuseTalk, real-platform live acceptance or
production service installation was performed in this task.

## Verdict

**READY FOR PLATFORM CREDENTIALS**

This verdict covers completed production hardening and reviewable deployment
preparation. It does not authorize loading a real credential into the current
unisolated school-linux environment or claim real-platform live acceptance.
