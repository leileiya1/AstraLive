# 07 — 后续开发、集成与生产验收

CPU 测试通过 ≠ 生产可用。下列阶段严格按依赖顺序推进；每阶段的“退出条件”满足前不进入下一阶段。

## 阶段 1 — Guardian 代码稳定与 PR11 集成（当前）

已完成：P1/P2 修复与回归（本分支）。

剩余：
1. **Agent4 独立审核** `service.py` `12b5→94eb→0a54` 与 `process.py 5d95→56d4`（`evidence/protected/`）。由 Agent4 决定是否登记；本分支不改清单。
2. 由你决定交付方式（需确认）：
   - a) 把本分支修复 cherry-pick 到 `feat/v05-output-guardian` 并推送，更新 PR11；或
   - b) 推送 `rescue/astralive-v05-final` 并对 integration 开新 PR。
   同时需处理 Agent5 本地未推送的 `2bf2600/77b1758`（与本次重复，建议废弃，以免两个未登记 postimage 并存）。
3. Agent4 在合并树上重跑：本报告 05 的全部命令 + receiver1 专用库原生套件（本次 SKIP 的 36 个）+ Agent3 streaming PG 8 个。
4. 跟踪 02 P3-a/b/c/d；P3-b/c 建议在 Linux CI 上做 ≥50 次重复以量化，**不改期限**。

退出条件：PR11 登记后的契约 137/137、validator v1/v2 PASS、组合 Guardian 无 FAIL，PR11 合入 integration（由 Agent4 执行）。

## 阶段 2 — Runtime 一次性 TTS 与 ReceiverProofs

Runtime 侧 receiver1 adapter 消费 v2 Grant，单次 TTS 结果绑定 ReceiverProof；不可重放、Stop 优先。依赖阶段 1 的 Guardian v2 gate。

## 阶段 3 — 真实 Observer 与 required Sink

用独立 Observer 解码实际 Sink 输出（替换当前 CPU 本地解码夹具），`requiredSinks` 全部到达才可 DRAINED。

## 阶段 4 — 可信 PhysicalSource 与 Host Launcher

Agent4 负责：受信 Host Launcher、CoordinatedPhysicalSource、变更前强制 `RetireInstallation`、Session/Generation/Binding 装配。

## 阶段 5 — Linux 真实进程隔离与旧 Publisher 撤销

需**单独授权**的专用 Linux VM/主机：独占委派 cgroup v2、独立 UID/ACL/namespace、隔离网络/目标/DB/凭据、精确清理清单。Agent5 负责独占控制器、旧 Publisher/socket/凭据撤销与 required Sink 证明。之后才可能解除 `OUTPUT_FENCE_UNPROVEN`。**不得在共享 Linux（含 school-linux）上做 cgroup 变更。**

## 阶段 6 — CPU 端到端联调

Backend + Runtime + Guardian v2 + Observer 全链路（CPU、私有 RTMP 目标），含崩溃/重启/Stop/过期矩阵。

## 阶段 7 — GPU 与真实媒体验收

仅在 1–6 完成后。GPU 访问请通过本机 `~/.ssh/config` 别名提供，**不要在对话中粘贴私钥**。正式平台推流需你逐次批准。

## 部署测试（school-linux，你在本轮提出）

可做的范围：在 `school-linux` 上以独立 Docker 容器/网络/端口构建并运行 Guardian 测试套件（私有 PG/MediaMTX 在容器内），验证 Linux 下 v1/lifecycle/v2 行为，跑完清理。**不做** cgroup 变更、不推流到外部、不启用 Durable LIVE、不触碰其他用户的容器/卷。结果另行记录在 `docs/rescue-out/evidence/school-linux/`。
