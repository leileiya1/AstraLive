# AstraLive SoulX Worker

Operator-only, authenticated loopback service reusing the pinned SoulX Lite environment.

- [Production design](../GPU-WORKER-PRODUCTION-DESIGN.md)
- [Deployment](../GPU-WORKER-DEPLOYMENT.md)
- [Operations](../GPU-WORKER-OPERATIONS.md)
- [Acceptance and limits](../GPU-WORKER-ACCEPTANCE.md)

Run lifecycle commands from the deployed AstraLive code root with the existing GPU Python:
`python -m gpu_worker.cli start|stop|restart|status|probe|check --config /absolute/operator-config.json`.

Build an installer with `python -m gpu_worker.release --out /path/release --archive /path/release.tar.gz`.
On the target run `./install.sh` once, then use the printed `astralive-worker start|stop|restart|status|doctor|run` command.
The installer preserves private configuration and tokens on upgrade. Startup never downloads weights or installs packages.
An optional offline lab snapshot can be exported on the validated GPU host with `--with-lab-config /private/worker.json`.
It requires the same base image and paths; a code-only release is not a complete model/environment image.

RTX2080Ti deployment simulation is separate from real inference acceptance; FlashAttention2.8.3 excludes Turing.
RTX3060 12GB is architecture-compatible but its real-time capacity is not yet measured. CPU simulation never proves GPU readiness.
RTX3080 10GB now passed the direct real Worker short smoke (PCM/FORCE/crash recovery/cache/cleanup).
This is separate from business Session and full WebRTC/RTMP acceptance; see the linked acceptance report.
