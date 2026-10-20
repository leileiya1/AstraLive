# school-linux Docker 测试部署（2026-10-20）

**性质**：Linux CPU 测试部署，不是生产部署。生产 compose（`infra/guardian/compose.yaml`）需要真实 Authority 库、受保护配置、Runtime producer 和 RTMP 目标，且生产 PhysicalSource 无条件拒绝，在共享主机上部署既无验证价值又会触及真实资源，因此未执行。

## 主机（只读勘察）

Ubuntu 26.04.1、Linux 7.0.0-31、x86_64、32 核、61 GiB、Docker 29.4.3、cgroup v2，**共享主机**（ricegrow/rabbitmq/postgres 等他人容器及 v0.4 disposable PG/Redis 在运行）。GPU Quadro K2200 未使用。

## 隔离方式

- 构建上下文 = `git archive <commit>` 通过 ssh 流式传入，远端不落盘源码。
- 镜像 `infra/guardian/rescue-test/Dockerfile`：python:3.12-slim-bookworm + PGDG PostgreSQL 17 + 官方 `bluenviron/mediamtx:1.21.1`；非 root（uid 22099）。
- `docker run --rm --cap-drop ALL --security-opt no-new-privileges --cpus 8 --memory 8g --pids-limit 4096`，无端口发布、无卷；`--network none` 或默认 bridge（仅为 WebRTC ICE 需要非回环网卡）。
- 未做任何 cgroup 变更、未推流、未启用 Durable LIVE、未触碰其他容器（`cleanup.txt` 前后容器列表一致）。

## 结果（计数不可相加）

| 运行 | 镜像 | 结果 | 日志 |
| --- | --- | --- | --- |
| 全量 #1 none | ff5bc6a | 211 P / 7 F / 2 S | `guardian-suite-run1.txt` |
| IPC `[v1]` ×5 | ff5bc6a | 5/5 FAIL（确定性，Linux RST） | `ipc-unprovisioned-x5.txt` |
| WebRTC 单项 bridge | ff5bc6a | PASS（证明 none 下失败为环境） | `webrtc-bridge.txt` |
| 全量 none / bridge | f036fa3（错误的 teardown 修复） | 211/7/2 ；212/6/2 —— IPC 仍 FAIL，**该修复无效，已保留** | `guardian-suite-f036fa3-*.txt` |
| IPC 文件 ×5 | wip（`send()` 修复） | 5×17 PASS | 见 `d17d008` 提交说明 |
| 全量 none | d17d008 | 212 P / 6 F / 2 S / 1 E | `guardian-suite-d17d008-none.txt` |
| 全量 bridge | d17d008 | 212 P / 5 F / 2 S / 1 E | `guardian-suite-d17d008-bridge.txt` |
| v1+lifecycle ×3（仅摘要） | d17d008 | 76P/1F；75P/1F/1E；76P/1F | `v1-lifecycle-x3-d17d008.txt` |
| v1+lifecycle ×2（全日志） | d17d008 | 76P/1F；76P/1F | `v1-lifecycle-run{4,5}-d17d008.txt` |
| 新回归 `test_stale_generation.py` ×5 | d17d008 | **85/85 PASS** | `stale-generation-x5-d17d008.txt` |

### 剩余 FAIL / ERROR 分类

| 项 | 分类 | 依据 |
| --- | --- | --- |
| `test_retained_real_ffmpeg_physically_kicked_before_activation` | 环境：镜像无 `ffmpeg` 可执行文件 | `FileNotFoundError: 'ffmpeg'` |
| `test_evidence_archive.py` ×4 | 环境：归档上下文无 `git`/仓库历史 | `FileNotFoundError: 'git'` |
| `test_webrtc_real_peer_closed_on_expiry`（仅 none） | 环境：无非回环网卡，ICE 停在 `new` | bridge 下 PASS |
| `test_real_ipc_denies_unprovisioned_context[v1]` | **测试缺陷，已修复**（`d17d008`） | 修复后 Linux 全量与 ×5 均 PASS |
| ERROR teardown `test_two_physical_publishers…`（none、x3#1） | 受保护 `rig` fixture：MediaMTX SIGTERM 后 3 s 未退出 | `TimeoutExpired … mediamtx … 3 seconds` |
| ERROR setup `test_competing_guardian_real_sql_lock`（bridge） | 受保护 `rig` fixture：`start()` 失败后 `close()` 抛 `OUTPUT_FENCE_UNPROVEN` 掩盖原因 | traceback 止于 `service.py:253` |
| ERROR `test_real_stale_media_ack_keeps_new_generation[2]`（x3#2） | **原因未知**：该次只保留了摘要行；单独 ×5 及之后 2 次全日志运行均未复现 | 诚实记录为未解释 |

**结论**：本次修复在 Linux 上的行为与 macOS 一致（新回归 85/85、生命周期与 v2 业务断言全部通过）。剩余项为镜像缺少 ffmpeg/git、受保护 fixture 在 Linux 负载下的进程/就绪计时，以及 1 次未复现的 ERROR。没有任何生产隔离（cgroup/UID/网络）被测试；`OUTPUT_FENCE_UNPROVEN` 不变。

远端保留镜像 `astralive-rescue/guardian-test:d17d008`（1.15 GB）供复跑；如需删除：`docker rmi astralive-rescue/guardian-test:d17d008`。
