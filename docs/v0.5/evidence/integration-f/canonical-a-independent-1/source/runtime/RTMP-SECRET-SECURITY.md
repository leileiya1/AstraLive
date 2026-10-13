# RTMP Stream Key Security

Date: 2026-10-08. Scope: production preparation, no real platform credentials.

## Result

**Stream Key is present in FFmpeg argv. Log redaction does not hide argv.**
`FFmpegRTMPMediaOutput._command()` passes `RTMPSettings.target` as the final
output argument. This applies both to URL + key and to `RTMP_PUBLISH_URL`.
No obfuscation or custom encryption is used.

## school-linux investigation

Live checks used a clearly fake marker and a blocked rawvideo input. No frames
were sent and no real platform was contacted. The test process was terminated
and reaped in `finally`.

| Check | Observed result |
| --- | --- |
| SSH operator | sapiece, UID 1000 |
| `/proc` mount | `proc rw,nosuid,nodev,noexec,relatime`; no hidepid/gid option |
| `/proc/<ffmpeg pid>/cmdline` | Fake stream-key marker visible after exec |
| `ps -ww -p <pid> -o args=` | Fake stream-key marker visible |
| cmdline permissions | 0444 |
| Cross-UID accessibility | UID 1000 successfully read an unrelated root-owned nonempty cmdline; contents were not emitted |
| root impersonation | Not performed; noninteractive sudo unavailable |

An initial immediate read raced subprocess exec; the repeat waited 300 ms and
confirmed both argv and ps visibility. Under this host's default procfs policy,
ordinary users able to access host `/proc` can inspect these command lines.
Same-UID processes can read them. Host root can read them, including after
hidepid isolation; that root conclusion follows Linux's privilege model, not a
sudo test performed here. PID/mount namespaces and separate security policies
may further limit visibility, but none was demonstrated for the current host.

The [Linux procfs documentation](https://www.kernel.org/doc/html/v6.15/filesystems/proc.html)
describes hidepid protections; [proc(5)](https://www.man7.org/linux/man-pages/man5/proc.5.html)
defines hidepid=0/1/2 and the exemption group. Neither hides secrets from the
publisher UID or privileged host administrators.

## Required production boundary

Before installing a real credential on a shared Linux host:

1. Use a dedicated `astralive:astralive` system account, locked password,
   `/usr/sbin/nologin`, no login keys and no shared UID. Do not add ordinary
   operators to its group or grant unrestricted sudo/run-as access.
2. Use root-owned release code/venv/models under `/opt/astralive`, readable and
   traversable only by root and the service group (directories 0750; ordinary
   source/model files 0640; executables retain needed execute permission).
   Keep writable state under `/var/lib/astralive` and `/run/astralive` (0700).
3. `/etc/astralive` is root-owned 0700; `runtime.env` is root:root 0600.
   systemd reads EnvironmentFile before dropping privileges. Do not source it
   through a shell, use `set -x`, dump the environment, or put keys in unit files.
4. On shared hosts, configure **host-level** `/proc` hidepid=2 (or equivalent
   verified host isolation), with no exemption group accessible to ordinary
   users. Evaluate monitoring compatibility first. Verify from a separate
   ordinary UID using a fake publisher before loading real credentials.
   This task did not remount `/proc` or edit fstab.
5. Service `ProtectProc=invisible` restricts the service's own view of procfs.
   It **does not hide this service from users reading the host mount**.
   [systemd.exec](https://github.com/systemd/systemd/blob/main/man/systemd.exec.xml)
   documents its mount namespace scope. Do not treat it as step 4.
6. Root and same-UID access remain trusted boundaries. Disable core dumps;
   restrict journal/evidence readers and privileged monitoring agents. Do not
   capture raw ps/argv/environment into diagnostics or incident bundles.

EnvironmentFile chmod 600 protects the on-disk file, not argv or process memory.
Environment secrets also remain accessible to the service UID and root, and can
be inherited by child processes. The env-based interface is retained as
requested; systemd itself cautions that environment variables are not an ideal
secret transport. This is an explicit trust boundary, not a claim of secret
invisibility.

## Application safeguards

- Credential fields are excluded from settings repr.
- Target validation errors do not echo supplied URLs or credentials.
- Redaction covers complete RTMP/RTMPS URLs, path segments, stream keys,
  query values and URL-encoded/decoded forms in captured FFmpeg stderr.
- Diagnostics reapply redaction to stderr/lastError before serialization.
- Preflight emits check names and booleans only, never argv, DNS exception text,
  FFmpeg stderr or a credential-bearing target.
- runtime `.gitignore` excludes `.env`, `.env.*` (except `.env.example`) and
  `*.secret`; the example contains only a fake target and `replace-me`.
- No temporary secret file is created by the production launcher. If an
  operator uses an ephemeral secret file, place it in a protected `/run`
  directory, use 0600 and arrange deletion on exit/failure. Remove obsolete
  files after stopping service; do not delete a persistent EnvironmentFile
  needed for Restart. Revoke/rotate any credential exposed by earlier tooling.

Redaction is defense in depth. Do not log the dataclass via `asdict()`, raw env,
raw subprocess arguments, or platform-provided credentials in evidence.

## Optional relay boundary

If platform credentials may not exist in the Runtime/FFmpeg security domain:

```text
AstraLive Runtime -> localhost RTMP -> dedicated RTMP relay -> platform
```

Use a separate non-shared relay UID, root-owned 0600 credential configuration,
loopback-only authenticated ingress and the same host-level proc isolation.
Choose a relay that consumes platform credentials from protected configuration;
a relay that launches FFmpeg with the platform URL merely moves the argv risk.
This is a deployment alternative, not an implemented relay or media redesign.
Host root still remains trusted. RTMP itself is unencrypted on the network;
use official RTMPS where available, subject to the selected FFmpeg build and
platform's TLS requirements.

## Security disposition

Current school-linux shared-UID/default-proc setup must **not** receive real
platform credentials as-is. Production deployment instructions and isolation
requirements are ready; operator application and verification of the boundary
remain prerequisites to live publishing.
