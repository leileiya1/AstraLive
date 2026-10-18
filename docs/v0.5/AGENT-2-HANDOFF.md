# Agent 2 Handoff — durable-live-1

Agent 2 ACK `durable-live-1`，不采用实验分支的 `v0.5-frozen-1`。

- 已执行 `git fetch origin`，GitHub PR #4 状态为 MERGED，merge/main 为 `7fe5d24810e2df348c58dd7748e97ffbe5cff384`。
- 已验证 main 包含 `ae28144d15afcf0e5f5ea8fa425fc42d27fc047b`。
- 保留既有 Worktree `AstraLive-agent-2`、分支 `feat/v05-durable-recovery`，确认原本干净后 `merge --ff-only origin/main`。
- 实现首提交 `28ea86924ac1ab206ed51565415e764e2ce21ef7`；最终验收源码提交 `26ebe57b06356cbe83b76055583014947f7c043e`。文档/证据提交另行追加，最终 PR head 以 PR 和交付消息为准。

## 源码与迁移范围

- `backend/internal/durablelive/**`：冻结 Schema 生成 DTO、全部 Backend 操作、计划/话轮存储、Outbox、Journal、Recovery Coordinator、LeaseKeeper、Permit、证据投影、通知与 Redis hint 适配、角色鉴权和部署组合器。
- `backend/db/migrations/000006_durable_live.sql`：真实、可执行的新增迁移。`dl05_*` 事实表、幂等响应/通知/审计 sidecar、回答日志、不可变及复合 FK/unique/CAS 约束。未改写 000001–000005。
- `backend/db/migrate.go`：必要的部署 migration 串行化，独立连接 advisory lock；错误后不归还持锁连接。
- `runtime/app/durable_live_journal.py`：真实 HTTP JournalClient、ExecutionInbox、RuntimeControl、OutputGate 与 versioned routers；导入不启用功能。
- 新增测试与 `scripts/durable-live/*`：纯生成工具、共享补丁验证、隔离实例 runner、真实子进程故障 probe。
- `go.mod/go.sum`：本地 JSON Schema 2020-12 验证器；没有引入新大型服务。

未直接编辑共享 Service/interaction/eventbus/httpapi/main、旧 Runtime Session/Binding/media、Scheduler、GPU validated 协议、模型、PTS/Credit。共享接线位于 `integration/agent-2-shared.patch`，只在临时快照应用验证。

## 已覆盖的崩溃窗口

Claim 原子提交/回滚；提交结果丢失后的持久幂等响应；事务提交后 Go SIGKILL；SEND_STARTED 模糊发送；真实 Python 202 延迟到 Go HTTP timeout；一次性 START/ACK 歧义；PLAYING 时 Go/Python SIGKILL；Backend 重启对现存 Journal/Inbox 查询；Lease 竞争/过期、旧 epoch/Generation handoff 拒绝；Stop 竞争；独立 PostgreSQL/Redis 服务停启及连接中断；事件重复/乱序、全 required drain、通知补偿。

稳定原身份不会因传输错误更换。新任期不能把旧信封的 runEpoch 改大再发；旧任务有证据地终结后，新的业务执行需要新的、获授权的 Attempt。没有外部 exactly-once 播放保证。

## UNKNOWN 与人工路径

缺失 ACCEPT、START ACK 不明、播放无 drain、旧输出隔离不可证明、序号缺口/冲突、进程重启后丢失队列都不会自动重播。

`MarkExecutionUnknown` / `QueryExecutionStatus` / `RestoreContentPlan` 显示持久知识；`ResolveUnknown` 使用冻结 Decision 保存 WAIT / SKIP_WITH_GAP / CREATE_NEW_TURN 的显式决定。UNKNOWN 在有真实 barrier 前不释放物理 slot。gap 不是完成，连续完成前缀不越过未知段。旧评论不能凭新 Session 绕过 source 唯一键；显式新评论重答需集成方处理授权与来源关系，当前不自动进行。

`SealNotExecuted` 要求未提交 START 且有独立 Guardian 隔离证明，原子封存旧 executor。不能拿空内存或 404 调用这条安全证明。

Legacy RESERVED/QUEUED 的自动导入/重播禁止。`InspectLegacyOrphans` 记 LEGACY_UNKNOWN；先人工停止或隔离原 Session，再创建 durable run，保留旧 Receipt。

## Agent 3 集成接口

直接导入 `durablelive` 生成 DTO 和 Store 方法，或者调用 `Store.Call`。请求/响应均验证同一冻结 Schema：

`SaveContentPlan → AdmitTurn → RestoreContentPlan → ClaimNextTurn → DispatchTurn → ConfirmCheckpoint → YieldAtSegmentBoundary`。

Claim 由 Agent 3 提供 candidateTurnId，Agent 2 只做持久资格/CAS，不重做内容策略或 Comment Scheduler。一次 Claim 的可执行 Turn 投影、Attempt、Utterance、Outbox、slot 同事务；Dispatch 只唤醒原 Intent。

任何策略调用不得持有 Scheduler/controller mutex 等待 SQL；不提供 borrowed transaction。动态事实通过 `Store.Facts` 的受信任权威校验回调，在事务外执行，事务内仍校验原命令、商品、时间和 proof hash；缺失 hook 时拒绝动态事实执行。

## Agent 4 必须完成/验证

1. 审核并应用独立共享补丁；在 main 的受保护注册器中创建不同 CONTROL / RUNTIME_JOURNAL / OUTPUT_GUARDIAN token，scope 从现有 owner/Binding 推导。运行 `NewDeployment(...).Run`，包括 Dispatcher、Coordinator 和 LeaseKeeper；不能用请求 JSON 自报 scope。
2. 通过现有正式 LiveSession + Provider Binding 流程新建/校验 Session，检查 Worker READY 和资源 ACL，再调用 `AttachSession`。绑定过期、旧 Session 输出未隔离时不得恢复。跨进程模式严禁双 scheduler。
3. 部署真正唯一的输出 Guardian，持有发布凭据/连接和 WebRTC peer；把所有 sink handoff 接入 OutputGate，确保旧 Runtime 无旁路。注入真实 install_fence / verify_stop / stop_session 回调，不能以文件 sink 测试代替。
4. 接入 SCRIPT_TEXT exact-text TTS/Avatar、真实 Generation/Worker Epoch 映射和全 required sink drain；旧 Worker wire、PTS、Credit 保持原协议。
5. **契约接线缺口：** 冻结 wire 没有 answer-prepared 操作。`RecordAnswerText` 与回答 artifact 已实际实现，但 Python 跨进程写入的正式入口需 Agent 1/4 明确 CCR/接线。未解决时 COMMENT_QUESTION 的 START 拒绝；不能绕过为旧问题直接合成。
6. 真实 Session 重建/Worker 失联/整机重启、跨主机 DB/Redis、双真实 GPU Publisher、Chrome/WebRTC、RTMP、官方观众及长时运行均须另验。逻辑 Run 恢复不代表物理推流无中断。
7. 新路径默认关闭。应用回滚先关闭准入、Stop/隔离旧输出并导出 UNKNOWN，保留新表。未执行破坏性 DDL down 或业务数据清理；不得把旧应用接到仍活跃的 durable Session。

## 验收记录

最终结果、命令、进程注入证据及版本见 `RECOVERY-ACCEPTANCE.md`、`FAILURE-MATRIX.md`、`agent-2-evidence/final/acceptance.json` 与同目录原始文本。Mock 与真实层：Go HTTP/SQL、Python Journal/Inbox 和进程终止为真实；模型、TTS、GPU 和口播使用测试 adapter/文件 sink，生产媒体为 NOT TESTED。

最终部署不是本 PR 自动执行的动作。Agent 2 的组件和补丁可运行、可审查；正式入口集成/Guardian/观众端验收不能记为已通过。


最终验收源码：`26ebe57b06356cbe83b76055583014947f7c043e`。隔离 PostgreSQL 17.11、Redis 8.10.2、真实 Go/Python 子进程与文件 sink。Durable Go race：35 PASS、0 FAIL、1 helper SKIP；该 helper 已由父进程测试调用。Python Journal 11 PASS；既有 Runtime 159 项，148 PASS、11 opt-in SKIP；冻结 v1.1/v0.5 契约 unittest 17 PASS；全 Go 回归、44 文件 hash validator、临时快照共享补丁检查均退出 0。

## durable-live-2 additive implementation（2026-10-18）

以上为 durable-live-1 历史交付。获批 CCR 后新增的 `000007_answer_stream.sql`、隔离 Backend Authority、真实 PostgreSQL/崩溃验收和当前接线依赖，详见 [AGENT-2-V2-HANDOFF](implementation/AGENT-2-V2-HANDOFF.md)。已消费 Agent4 唯一 DTO `e3302f6b2bb19e0184cde3a6cbbcaf3ea4371565` 并实现隔离 typed adapter；公共入口未接线，增量 PR 保持 Draft 并由 Agent4 审核；SQL 测试通过不表示 Durable LIVE 或真实媒体已验收。原始迁移/公共 app/runtime/v1 协议保持不变。
