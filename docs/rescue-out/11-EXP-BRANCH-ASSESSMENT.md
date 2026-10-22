# 11 — 实验分支评估：`exp/v0.5-soulx-staging-golden`（只读评估，2026-10-22）

## 结论：不合并；保留为参考实现，后续按需移植具体部件

## 它是什么

- Agent F 在 2026-10-11 至 10-15 之间的**另一套 v0.5 方案**，自定契约 `v0.5-frozen-1`（MediaTimeline、Narration 连续性、本地 UDS IPC、Worker QUIC、SoulX staging）。
- 分叉点 `cf6540b`（v0.4 合并），早于正式 v0.5 契约进入 main（PR4 `durable-live-1`，以及后来批准的 CCR-ADL-001 `durable-live-2`）。两套设计是**平行竞争**关系，而不是同一设计的增量。
- 251 个分支独有提交、244 个代码文件、约 4.4 万行；main 侧此后独有 112 个提交。

## 为什么不能直接合并

| 问题 | 事实 |
| --- | --- |
| 数据库迁移冲突 | 两边都有 `000006`、`000007`，内容完全不同（分支：`pg_durability`/`continuity_journal`；main：`durable_live`/`answer_stream`），分支另有 `000008`。合并会破坏迁移历史，生产库无法安全升级 |
| 契约冲突 | 分支实现 `v0.5-frozen-1`；main 已冻结并批准 `durable-live-1/2`（22 个规范文件、313 项保护）。同时存在两套“持久化执行真相”违反单一权威原则 |
| 受保护文件 | 修改 313 项清单中的 **28 个**文件（Backend app/server/migrate、Runtime session/providers/media、GPU worker 等） |
| 文本冲突 | `git merge-tree` 显示 8 个文件冲突（main.go、migrate.go、service.go、server.go、scheduler.go 等） |
| 改变现有默认行为 | 不只是新增：删除了现有弹幕互动的优先级抢占路径和 busy 准入判断，改用分支自己的连续性门控——会悄悄改变当前可用的产品 |
| 自身验收 | 真实一小时测试 hour7 **FAIL**；条件响应估计 9.374s / 12.093s，高于 5s / 8s 目标；最终源码没有新的真实 GPU 或整小时验收 |

主体以新增模块为主（`media_timeline.py` 745 行、`gpu_worker/staging_service.py` 708 行、`soulx_staging.py` 462 行、`narration_segments.py` 457 行、Go `durability.go` 312 行等），删改的现有行很少；但这些删改恰好是行为变更，不是可单独移植的通用缺陷修复。没有发现“main 现有代码的独立 bug 修复”需要立即带回。

## 值得以后借鉴的部分（按需移植，不整体合并）

| 部件 | 可用于 | 方式 |
| --- | --- | --- |
| SoulX staging GPU 服务与契约（`gpu_worker/staging_*`、`runtime/app/soulx_staging.py`）及真实 GPU 失败/修复记录 | 阶段 7 真实 GPU 验收 | 参考其适配经验和失败模式；按 main 的 Generation/Grant 规则重写接线 |
| 一小时连续实测夹具与观察检查点 | 阶段 7 | 移植测试夹具思路 |
| 评论打断 → 回答 → 过渡语 → 恢复讲解（narration bridge） | main 的 NATURAL COMMENT INTERRUPTION / EXPLANATION RESUME 门槛（阶段 2c/6） | 参考其提示词与状态设计，在 main 的 contentplan/turnmanager 上实现 |
| audio-master 时间线、Stop 时排空在途帧/ACK 的若干修复 | 阶段 3/6 的媒体 drain | 作为已知竞态清单，用 main 的测试复现后再修 |
| 本地 UDS 控制传输、Worker QUIC | 非当前阻塞项 | 暂不需要 |

## 处理

- 分支与 `../AstraLive-agent-f` 工作区保持原样，不删除、不修改。
- 如将来需要其中某个部件，单独开分支从 main 出发移植，并走完整回归与受保护文件流程。
