# School-Linux Environment

Recorded: 2026-10-07 (Asia/Taipei). Acceptance root: `/home/sapiece/AstraLive`.

## Host

- Hostname: `sapiece-ThinkStation-P368-C3G108`
- OS: Ubuntu 26.04.1 LTS, kernel `7.0.0-31-generic`, x86_64
- CPU: Intel Core i9-13900, 24 cores / 32 logical CPUs
- RAM: 61 GiB total; 44 GiB available at final inventory
- Root filesystem: 937 GiB total, 563 GiB available
- GPU: Quadro K2200 4 GiB, driver 580.178.04. It remained a display device; AI acceleration was not required.
- Boot ID before migration testing: `2c39c26e-0e68-4c2d-947f-3a211f5af075`
- Boot ID after failed WebRTC smoke and cleanup: `2c39c26e-0e68-4c2d-947f-3a211f5af075`

## Tooling

| Tool | Initial state | Acceptance state |
| --- | --- | --- |
| System Python | 3.14.4 | unchanged |
| Isolated Python | NOT INSTALLED | CPython 3.12.15 via `uv`, Runtime venv at `runtime/.venv` |
| Go | NOT INSTALLED | 1.24.13 under the user account |
| Bun | NOT INSTALLED | 1.3.14 under the user account |
| Node | NOT INSTALLED | 24.21.0 under the user account; required so `bun run test` invokes Vitest with Node rather than Bun's Node shim |
| Docker | 29.5.1 | unchanged |
| Docker Compose | v5.1.3 | unchanged |
| FFmpeg | 8.0.1-3ubuntu2 | unchanged; apt/snap installation was not needed |

Python 3.12 was installed without replacing `/usr/bin/python3`. The venv installed only `requirements.txt`, `requirements-real-tts.txt`, `requirements-real-avatar.txt`, `requirements-real-media.txt`, and `tests/requirements.txt`; `pip check` reported no broken requirements. MuseTalk, a local LLM, CUDA PyTorch, and legacy CUDA packages were not installed.

## Services

Existing services were reused rather than duplicated:

- PostgreSQL: `127.0.0.1:5432`, isolated AstraLive database/role already represented by `backend/.env.integration`; password omitted.
- Redis: `127.0.0.1:6379/14`, stream `dh.runtime.events.v1`.
- MinIO: not required for the v0.1 core path and not started.

The existing `postgres` and `redis-server` containers were not recreated. During the failed browser smoke they used approximately 74.7 MiB and 49.4 MiB respectively.

## Headless media

Physical sound card: **NOT REQUIRED**.

The real sherpa-onnx provider generated mono PCM16 at 22,050 Hz in memory. Audio was handed to aiortc and initially reached Mac Chrome over WebRTC. No ALSA output, PulseAudio speaker, microphone, dummy sink, or physical audio device was configured.

Full command output is preserved in [school-linux-environment-raw.log](../evidence/school-linux/school-linux-environment-raw.log).
