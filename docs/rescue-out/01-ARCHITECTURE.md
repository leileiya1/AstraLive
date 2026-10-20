# 01 — AstraLive 架构、分支与完成情况

> 基于 2026-10-20 实际 `git fetch --all --prune` 后的远程状态与源码阅读。所有 SHA 均为该时刻的远程值，未使用历史文档中的旧 SHA 作为依据。

## 1. 工作目录与安全基线

| 项目 | 值 |
| --- | --- |
| 统一工作目录 | `/Users/sapiece/innovationProject/AstraLive` |
| 开始时分支 / 状态 | `design/v0.5-durable-live-contracts` @ `ae28144`，工作区干净 |
| 修复分支 | `rescue/astralive-v05-final`，基于 **远程** `origin/feat/v05-output-guardian` @ `47eedbb` |
| 其他 Agent 目录 | `../AstraLive-agent-{1-ccr,2,3,4,5,f}` 仅通过 `git show/diff/log` 只读引用，未执行、未修改 |
| 本地 Python 环境 | `.venv-guardian/`（已被 `.gitignore` 忽略），版本与 Agent5 环境逐包对齐（Python 3.12.13，aiohttp 3.14.5，asyncpg 0.32.0，av 17.1.0，pytest 9.1.1 等） |

**发现（需要你知道）**：Agent5 本地分支 `feat/v05-output-guardian` 比远程多 2 个**未推送**提交（`2bf2600`、`77b1758`），内容是先前一次 P1 修复尝试。按要求本分支以远程为基线，这两个提交仅作为只读参考；本次修复独立完成后与其对比（见 04-CHANGELOG §4）。

## 2. 分支拓扑（远程，2026-10-20）

| 分支 | SHA | 相对 main 领先 | 角色 / 状态 |
| --- | --- | --- | --- |
| `main` | `7fe5d24` | 0 | 主分支，含 v0.4 与 v0.5 冻结契约（PR4）。**未修改** |
| `integration/v05-durable-live` | `e4292ac` | 64 | Agent4 集成分支，PR8 Draft。最新 3 个提交只追加审查证据（P1 阻塞报告） |
| `feat/v05-output-guardian` | `47eedbb` | 85 | Agent5 Guardian，PR11 Draft，目标 integration。已合入 integration 的较早提交 `864cdbf` |
| `feat/v05-durable-recovery` | `08de61e` | 44 | Agent2 持久化/恢复，PR13 已合并进 integration（之后仅有审查文档提交） |
| `feat/v05-turn-manager` | `c0f36e1` | 51 | Agent3 Streaming/Turn Manager，PR12 已合并，完整为 integration 祖先 |
| `design/ccr-adl-001-answer-contract` | `c14085c` | 32 | Agent1 冻结协议与 CCR 治理，为 integration 祖先 |
| `exp/v0.5-soulx-staging-golden` | `3ef5371` | 251 | 实验分支（SoulX staging），与本次无关 |
| `rescue/astralive-v05-final` | 本分支 | — | 本次修复；**仅本地提交，未推送，未开 PR** |

本分支相对 `integration/v05-durable-live` 的非文档差异 = PR11 的全部 Guardian 内容 + 本次修复。

## 3. 模块与依赖关系

```
                ┌───────────────── contracts/v0.5 (冻结 22 文件, 313 项保护登记) ─────────────┐
                │  durable-live-1 (v1 wire) · durable-live-2 (receiver1/v2 wire) · protected-files│
                └──────────────┬───────────────────────────────┬──────────────────────────────────┘
                               │ 生成代码 (generate_v2_wire)     │ validator v1 / v2
     ┌─────────────────────────▼───────────┐       ┌───────────▼─────────────────────────────┐
     │ backend (Go)                        │       │ runtime (Python)                        │
     │  durablelive      v1 Journal/Outbox │◄─────►│  durable_live_journal, guardian_media   │
     │  durablelivev2/authority  Grant/Stop│ HTTP  │  receiver1/ (官方 wire adapter)          │
     │  turnmanager + answerstream (Agent3)│       │  rtmp_media / webrtc_media / TTS        │
     │  durableintegration/receiver1 (A4)  │       └───────────┬─────────────────────────────┘
     │  PostgreSQL 7 migrations, Redis     │                   │ PCM/RGB via 私有 IPC
     └─────────────────┬───────────────────┘                   │
                       │ Permit / Authority SQL (只读角色)        │
     ┌─────────────────▼──────────────────────────────────────▼───────────────────────┐
     │ output_guardian (Agent5, PR11)                                                    │
     │  v1: service.Guardian ── Publisher(子进程 FFmpeg/PyAV) ── RtmpProxy ── MediaMTX    │
     │      authority.PostgresAuthority · ingest(MediaMTX API) · observe(解码覆盖验证)     │
     │  v2: receiver/gate/ipc/cpu/journal/physical/linux_fence (receiver-1 门, 默认拒绝)   │
     └───────────────────────────────────────────────────────────────────────────────────┘
                       │ 生产: PhysicalSource (无条件拒绝) / GPU worker (未启用)
```

### Guardian v1 生命周期（本次修复所在）

- `Guardian` 持有全局状态：`_life`（当前 `_Lifecycle`）、`barrier`（每次 `invalidate()` 加 1）、`right`（当前 Permit 期限）、`publisher/receiver`（单槽子进程）。
- `install`/`bind`/`finish`(同步段) 持有 `operations` 锁；**新 Generation 只能由 `bind` 在锁内创建**。
- `retire()` = `invalidate()`（同步：barrier+1、清 Right/secret、标记 REVOKED）+ `close_resources()`（合并的清理任务：杀 Publisher/Receiver、关 socket/WebRTC、`ingest.isolate`）。
- `_retire_life(life)` 仅当 `life` 仍是当前且 barrier 未变时才调用 `retire()` —— 这是“作用域撤销”原语。
- `Publisher.call` 在进入锁前捕获 `expected` 进程/管道，旧请求不会写入新子进程；`abort(expected)` 不会杀死更新的子进程（已核验，本次未改）。

## 4. 完成情况（按事实分类）

| 模块 | 状态 | 依据 |
| --- | --- | --- |
| v0.5 冻结契约 / 生成代码 | 完成并冻结 | validator-v1 PASS、generator `--check` PASS（`3c0c317e…`） |
| Agent2 持久化恢复 (PR13) | 已合入 integration | 私有 PG 下 Go race 228 PASS/0 FAIL |
| Agent3 Streaming/Turn Manager (PR12) | 已合入 integration | 同上；answerstream 的 8 个 PG 用例需 Agent3 专用库，本次 SKIP |
| Guardian v1 Finish/Renew 协调 | 已实现（Agent5），本次保留 | lifecycle 35 原用例全 PASS；Agent4 原始媒体探针 66/66 PASS |
| **Guardian v1 旧 Generation 回调隔离 (P1)** | **本次修复** | 见 02/04/05 |
| **生命周期测试 SQL fixture 并发 (P2)** | **本次修复（测试层）** | 见 02/04/05 |
| Guardian v2 receiver-1 门 / IPC / CPU 连续性 | 实现，默认关闭 | v2 142 PASS / 1 Linux SKIP |
| cgroup 变更控制器 | **有意不可用**（拒绝所有 kill/procs/rmdir） | `OUTPUT_FENCE_UNPROVEN` 保持 |
| PhysicalSource / Host Launcher / 必需 Sink / Observer | 未实现（生产无条件拒绝） | 后续阶段 3–5 |
| Linux 真实隔离、GPU、正式推流 | 未测试 | 后续阶段 5–7 |

**Durable LIVE 保持关闭；`OUTPUT_FENCE_UNPROVEN` 保持生效；本次没有任何结果可被解读为生产可用。**
