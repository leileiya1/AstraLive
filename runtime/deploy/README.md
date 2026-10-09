# Production systemd deployment template

This directory contains templates only. No actual host units/users/procfs
settings have been modified. Use a system service on school-linux, independent
of SSH and macOS. See [credential security](../RTMP-SECRET-SECURITY.md) before
installing a credential.

## Operator deployment procedure

- Create locked `astralive:astralive` with nologin; do not share its UID/group.
- Install a reviewed release under `/opt/astralive`; provision a **Linux-built**
  venv there from the existing Runtime requirements, and CPU TTS model files.
  Keep code/venv/models root-owned, group-readable; do not copy the macOS venv.
- Create root:root `/etc/astralive` (0700) and `runtime.env` (0600). Copy the
  four placeholder lines from `runtime/.env.example`, then edit securely.
  Do not paste credentials into shell command lines or task evidence.
- Supply Real LLM settings, `TTS_MODEL_DIR=/opt/astralive/...`, Tool URL/token,
  Redis URL and existing Runtime provider settings in the protected file.
  Store caches/output under `/var/lib/astralive`, not the read-only release.
  Backend, Redis, database and Product Tool must also run on school-linux or
  independent server services; none may depend on a Mac tunnel/proxy.
- Confirm `MAX_SESSIONS=1`; the template intentionally has a single publisher.
  The service-user flock is held throughout Runtime's lifetime. Preflight
  scans visible FFmpeg RTMP publishers; it cannot detect remote publishers,
  hidden PID namespaces or programs using another executable name. Neither
  a proc scan nor a lock prevents a privileged administrator bypass.
- Apply/verify host-level hidepid=2 or an equivalent isolation boundary before
  real secrets. `ProtectProc=invisible` alone is insufficient.
- Install `astralive-runtime.service` in `/etc/systemd/system`, verify with
  `systemd-analyze verify`, then reload and enable it as an operator. This
  preparation task does not perform those mutations or start platform output.

EnvironmentFile uses systemd key=value syntax, without `export` or shell
expansion. Use either `RTMP_URL` + `RTMP_STREAM_KEY`, or `RTMP_PUBLISH_URL`.
Remove the other form entirely; ambiguous configuration fails closed. A full
URL may carry authentication in its path/query; it is kept byte-for-byte.
`RTMP_PLATFORM=generic` is the only implemented profile; douyin/taobao require
future official parameter confirmation before profiles are added.

For management previews choose `WEBRTC_ENABLED=true`; without a preview use
`WEBRTC_ENABLED=false`. RTMP clocks and lifecycle run server-side either way.
Use a trusted local/server-side control API path to start/stop Sessions; an SSH
management connection is optional. The template binds Runtime to localhost,
so public users must continue through the existing Go API.

## Lifecycle and limits

`production_launcher` acquires `/run/astralive/publisher.lock`, runs non-publishing
preflight and execs Uvicorn. Start does not create a Live Session automatically.
Restart=on-failure, 10-second delay, max five starts per 300 seconds prevents
unbounded restart loops. Restart restores the Runtime process, not previous
Session state; control-plane recovery remains an operator/application concern.
RTMP reconnect remains owned by the existing media output.

For scheduled end of broadcast, use the existing Session Stop API and verify
ENDED/FFmpeg exit before stopping the unit. On service shutdown KillMode=mixed
sends SIGTERM to Uvicorn first; its lifespan calls manager.close() and the
existing media cleanup. Uvicorn allows 25 seconds; systemd allows 45 seconds
before killing remaining cgroup processes. No shell cleanup depends on SSH.

Journal output is structured Runtime logging; media diagnostics use INFO every
60 seconds by default. Restrict journal readers. The unit disables core dumps,
uses 0077 umask, no capabilities and a read-only system with private temporary
files. State/runtime directories are systemd-managed with 0700 permissions.
Initial limits: MemoryHigh=4G, MemoryMax=6G, TasksMax=512, NOFILE=4096. These are
conservative single-Session starting values, above observed final-soak RSS;
monitor model loading and real-service load before adopting them unchanged.

## Preflight and acceptance after operator deployment

Run `python -m app.rtmp_preflight` from the Linux Runtime venv with protected
configuration in its environment. It returns boolean checks and exit 0/1,
never publishes. An unavailable RTMPS output protocol fails the check. DNS
resolution succeeds or fails independently of TLS, authentication and platform
account authorization; these are not established by preflight.

Before real output, verify permissions and cross-UID argv isolation with fake
credentials. Then configure the chosen official target and account permissions.
The current build lists RTMPS output, but no real TLS endpoint has been tested.
Verify the platform's TLS/certificate requirements during the authorized test.

The design is `school-linux -> Runtime -> FFmpeg -> platform`. No Mac process,
launchd unit, browser, relay, tunnel, or physical audio device is on that path.
The accepted local harness's Mac browser/tunnel was management/observation only.
A later authorized real-platform test must explicitly disconnect management
and turn off the Mac, then verify platform output keeps advancing. That physical
Mac-off platform acceptance has not been executed in this preparation phase.
