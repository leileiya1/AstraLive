# receiver-1 isolated implementation

Baseline `e98d8cf53d1aa5518f9c908785b7a5feae5117f8`; frozen normative digest
`3c0c317ed00f6fa4d2cf15ef3f61fc002d4bb22bf02d53ee9f1b407458bb28b1`.
Production admission remains **OUTPUT_FENCE_UNPROVEN**. This is an additive
module PR, requiring Agent4 review; neither service template is installed.

`output_guardian.v2` contains a real short gate, irreversible Run tombstone,
temp/file/directory-fsynced deny journal, receiver coordinator, authenticated
HTTP/1.1 over AF_UNIX, three-operation bounded Authority port, and a persistent
CPU libav process/decoder/required-sink adapter. V1 source and its publishers are
unchanged. No Runtime shared entry, DTO, migration or frozen contract is edited.

Run isolated acceptance using the existing Guardian test environment:

```sh
.venv-guardian/bin/python -m pytest output_guardian/tests/v2 -v
```

The tests inject explicit contract MOCKs for Authority, Registrar, sole-codec
port and Evidence registration. They exercise actual OS peer PID credentials,
private sockets, file and directory fsync, SIGKILL, persistent CPU FFV1/PCM
encoding/decoding and decoded per-sink ranges. They never start GPU/Worker or
connect to a production RTMP target. CPU Evidence envelopes use synthetic
registration; their schema-compatible sink kinds do **not** assert RTMP output.

The standalone command `python -m output_guardian.v2` always exits 78 with
OUTPUT_FENCE_UNPROVEN, including when Durable LIVE is requested in environment.
Only Agent4's later trusted assembly may expose this module after dependencies
and real output isolation pass. There is no v1 bind fallback or invented
Backend transport. See [HANDOFF](AGENT-4-HANDOFF.md) and [acceptance](ACCEPTANCE.md).

Ownership in the eventual deployment:

| Resource | Exclusive owner |
| --- | --- |
| RTMP publish secret/socket, FFmpeg/libav process, WebRTC media Peer | Guardian-owned production output adapter; Runtime receives none |
| Room binding, current Run/Session/epoch/Generation | Trusted Registrar/Backend truth; Guardian compares the entire installed registration |
| Business consumption latch, Permit/current facts | Agent2 Backend Authority; Guardian has three narrow private operations, no SQL writes |
| Stage signing key and per-start Guardian credential | Trusted deployment provisioner, pinned by Registrar before Stage |
| Runtime process credential and channel identity | Trusted per-start ProcessPin plus kernel UID/PID/create-time and server-derived connection nonce |
| Local barrier, admission, denial journal, decoded CPU sink edges | This Guardian module; never owned by Runtime |

Use separate Linux UIDs, private state/key mounts and a Guardian-owned publisher
network namespace. Runtime has AF_UNIX only, no publish port, external egress,
ingest API/observer credentials, Guardian state, signing key or CONTROL group.
For cross-UID IPC, `PrivateIPC(access_groups=...)` requires two distinct trusted
groups: a 0711 unlistable parent, role-specific 0710 directories, 0660 sockets.
Guardian belongs to both; Runtime only producer; Registrar only CONTROL. Pins
also bind the actual process creation identity and Room scope. Same-UID default
0700/0600 mode is for dedicated local tests, not proof of production isolation.

The Linux templates retain cgroup kill of every owned child on Guardian exit.
Runtime's Worker/Backend access needs Agent4's narrow AF_UNIX supervisory proxies
using existing protocols. No general egress proxy is authorized. Deployment must
prove old keys/connections physically revoked and Room publisher exclusivity
before a new term; absent proof never stages production media. There is no
Docker/Podman executable on this tested Darwin host, so Linux UID/network/cgroup
and bypass tests are NOT TESTED. External platform keys have not been touched.
