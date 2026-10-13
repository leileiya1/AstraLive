# GPU environment audit — 2026-10-08

SSH public-key login and user-verified ED25519 host fingerprint passed. No credentials are stored in this lab.

Host: autodl-container-xgflfqu4p4-e2731b0c, Ubuntu 22.04.5 container, kernel 5.15.0-78-generic. No systemd inside container.

GPU: NVIDIA GeForce RTX 4090 D (not the original RTX 4090), 24564 MiB, compute capability 8.9. NVIDIA driver 580.105.08 supports CUDA Driver API 13.0; installed nvcc Toolkit is 12.8.93. Initial GPU had no running processes, 0 MiB allocation.

Existing base: /root/miniconda3, Python 3.12.3, torch 2.8.0+cu128, torchvision 0.23.0+cu128, torch.version.cuda=12.8. CUDA availability, device query, synchronized matrix multiplication and torchvision import all PASS. SSH default PATH omits Conda/CUDA; use explicit executables. Only base Conda environment existed. FFmpeg absent from default PATH. No system Python found in PATH.

Storage: /root/autodl-tmp is a separate /dev/md0 50 GiB data disk (50 GiB initially free); use /root/autodl-tmp/astralive-avatar-lab. Root overlay 30 GiB. Cloud instance deletion persistence is not assumed: results must be copied to school-linux and local machine. /autodl-pub/data is shared platform storage and is not our writable lab.

Host-visible resources: 503 GiB RAM, 433 GiB available, no swap; Xeon Platinum 8352V, 128 logical CPUs. These host-visible totals do not establish container allocation limits.

Git 2.34.1, curl/wget/rsync/gcc/make exist. GitHub HTTPS returned 200. Hugging Face direct HTTPS connection timed out; download routing remains under investigation.

Policy: preserve driver, Toolkit and base packages. MuseTalk gets isolated Python 3.10 environment because its MMLab binary extension stack requires a matching older Torch ABI. SoulX gets a separate environment; existing Torch compatibility will be investigated after MuseTalk basic test.

Source assets: school-linux ~/AstraLive/experiments/real-avatar/manifest.json has 11 listed assets, all current SHA256 matches and ffprobe exit 0. Chinese short/medium/long files are actually 6.835556/11.525986/72.051565 seconds. Exact-duration benchmark derivatives must be labeled and generated separately.
