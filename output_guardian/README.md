# AstraLive Output Guardian candidate

**OUTPUT GUARDIAN BLOCKED** for production. Independent source, deployment templates, CPU process/network-media fault tests and a Runtime IPC adapter are delivered. Existing production durable LIVE guards remain closed.

Read the [acceptance report](../docs/v0.5/guardian/ACCEPTANCE.md) and [Agent 4 handoff](../docs/v0.5/guardian/AGENT-4-HANDOFF.md) before integration.

The service owns one registered Room, a protected Unix IPC listener, publisher/decoder child processes, the real guarded RTMP socket, and WebRTC peers. PostgreSQL supplies authoritative binding/Permit/Stop state. It never restores an output authorization from disk. Media handoff uses local bounded authorization, not a database query per frame. Supervisor and the controlled ingest server supply physical cleanup evidence.

Install dependencies into a separate Python 3.12 environment using `requirements.txt`. Run from the repository root, with a protected operator-created configuration based on `infra/guardian/config.example.json`:

```
python -m output_guardian.supervisor --config /etc/astralive-guardian/config.json
```

The supervisor owns the configured MediaMTX instance and kills its complete process groups on failure. Never target a shared/existing ingest server. For the two-container arrangement, use `infra/guardian/compose.yaml`, which runs the Guardian entrypoint directly and places MediaMTX in its network namespace with a separate UID/read-only recording mount. These Linux/container templates have not been executed on the macOS test host.

Test with CPU media only:

```
uv pip install --python .venv-guardian/bin/python -r output_guardian/requirements.txt -r output_guardian/requirements-test.txt
GUARDIAN_TEST_MEDIAMTX=/path/to/mediamtx GUARDIAN_TEST_PG_BIN=/path/to/postgres/bin \
  .venv-guardian/bin/python -m pytest output_guardian/tests -q -s
```

MediaMTX must be v1.21.1 and PostgreSQL ≥16. Tests create a dedicated loopback cluster and temporary databases; they do not use a configured production database. `ffmpeg` on PATH is used only for the retained-legacy-process isolation test. The production publishing child uses PyAV's FFmpeg libraries, with private inherited-FD configuration and no URL/secret argv.

Production remains blocked on verified OS/network isolation and legacy key revocation, Agent 4's formal Session/Binding/Credit bridge, continuous short-segment and Session-wide timeline support, and trusted WebRTC full-range completion/external ICE. A finite zero-origin RTMP receipt proves only its explicitly tested local ingest range.
