# AstraLive v0.5 Durable Live Architecture

> CCR-ADL-001 review at PR8 `01a752baf79c25d4d268167d016c8c62e754cfdf`: active durable-live-1 is preserved. [durable-live-2 incremental answer candidate](ccr/CCR-ADL-001.md) and [migration/owner handoff](ccr/CCR-ADL-001-HANDOFF.md) are PENDING OWNER ACK; this historical v1 freeze does not approve that upgrade.

契约版本 **durable-live-1**；角色 Agent 1；基线 `cf6540bdcc788c037929836480812dfaa78362a2`。
2026-10-16 执行 `git fetch origin main`，远程 main 与此 SHA 一致，原工作区干净。交付分支 `design/v0.5-durable-live-contracts`。本文中的 MUST 是待实现要求，不是已有功能或验收结果。

## 冻结范围与兼容边界

本分支冻结 Agent 2 / Agent 3 从上述 main 开始的共同设计。权威顺序：本组文档的语义约束 → `contracts/v0.5/durable-live/protocol.json` 操作/权限映射 → `schema.json` 字段和枚举 → `state-machines.json` 转换边。跨字段、事务和权限条件不能仅由 JSON Schema 证明。修改 ID、接口、状态边、默认恢复策略必须提交编号 CCR，由 Agent 1、受影响 owner 和最终集成 Agent 明确 ACK 后升级版本。

远程实验分支 `origin/exp/v0.5-soulx-staging-golden` 在检查时是 `3ef5371`，其中已有 Agent F 的 `v0.5-frozen-1`。它以 Session 为 runEpoch 范围，并包含 narration/timeline 协议。本任务要求跨 Session 的 BroadcastRun；本组文件**不替换、不修改、不暗中兼容该实验契约**。两开发 Agent 可在本次 main 基线上并行实现；向实验分支集成前必须 CCR 明确 BroadcastRun 与 session-run 的映射、epoch 范围和迁移编号。不得直接拼接两套表或 wire DTO。其他 worktree 未被修改或合并。

Frozen v1.1 的 `contracts/CONTRACTS.md`、两份 OpenAPI、事件 Schema、已有样例及 Go/Python DTO 全部不变。新表、新入口、新适配层默认关闭；既有 v0.4 调用路径继续运行。单 Session 必须选择 legacy 或 durable-live 调度模式，不能双重投递。禁止修改 GPU 模型、TCP Worker wire、消费 credit 和媒体 PTS；没有启动任何收费 GPU。

## 按真实源码审查

| 指定文件 | 已有能力 | 本次需要补足 |
| --- | --- | --- |
| `contracts/CONTRACTS.md` | v1.1 Session/Utterance/FSM、source、priority、Tool、内部 `/internal/v1` 与事件 1.0 | 不在这些 DTO 上加 runId/epoch |
| `contracts/events/speech-plan.schema.json` | SPEAK/text/priority，严格拒绝额外字段 | 不是持久 ContentPlan，不得复用名称混淆 |
| `backend/internal/app/service.go` | 正式 Session/Speak/Stop；命令进程锁；SQL event+FSM 事务及去重 | Speak 的 CreateUtterance 与 HTTP 不原子；READY 提交后 Start 是远程调用，没有 Outbox |
| `backend/internal/app/interaction.go` | Session+Room owner、绑定商品、晚 TTL、busy gate；receipt RESERVED/ACCEPTED/FAILED | reservation、utterance、HTTP、receipt 更新分离，存在 orphan / ACK 歧义；锁不是跨进程 lease |
| `backend/internal/interaction/scheduler.go` | Normalize、去重、合并、TTL、公平评分、限流、Selection/Dispatcher、100ms 唤醒 | 默认忙时等待整个 utterance；高优先级合并问题可选抢占；没有自动内容计划。保留该 Scheduler |
| `backend/internal/eventbus/consumer.go` | Redis group、15秒 XAUTOCLAIM、ApplyEvent 后 ACK、五次失败 DLQ | 不等于 durable command inbox；乱序非法 FSM 可能重试后进 DLQ |
| `backend/internal/fsm/fsm.go` | Session 与 Utterance 独立 FSM | 不修改旧枚举；增加 run/turn/dispatch/checkpoint 投影 |
| `backend/internal/runtime/client.go` | v1 HTTP/202校验、8秒超时、错误映射 | 没有命令对账接口；HTTP timeout 不能证明未执行 |
| `backend/internal/app/session_integration.go` | Prepare/Release seam 复用 Provider Binding | 不重建 SessionIntegration |
| `backend/db/migrations/000001_init.sql` | Session、Utterance、runtime_events、idempotency_keys | 无 run、outbox、lease；复用既有身份/FK |
| `000004_session_integration.sql` | resource_owners、session_provider_bindings、principal FK | 复用 tenant+user 授权和不可变 capture，不复制凭据 |
| `000005_interaction_receipts.sql` | PK(session_id,trace_id)，三态防重复 | 任意已存在状态不重发，可能丢失；不是完整恢复日志 |
| `runtime/app/session.py` | 内存 Session、优先队列、seen_utterances、generation fence、流式分句/LLM/TTS；drain 后完成事件 | 分句没有稳定业务 ID，不是可恢复段；AUTO_SCRIPT 仍走现有回答生成链；v0.5 exact-text executor 必须单独适配 |
| `runtime/app/session_binding.py` | immutable binding resolve、过期监控、Worker admission、Stop/release | binding lease 不是 BroadcastRun lease；保留授权和有效期检查 |
| `runtime/app/bound_media.py` | headless RTMP drain、真实消费 credit，WebRTC OR RTMP 可释放 credit | credit 不是所有必需 sink 的完成证明，更不是平台观众已听见 |
| `docs/v0.4/INDEPENDENT-ARCHITECTURE-REVIEW.md` | 短时单 Backend/Runtime 的证据；清楚记录 crash windows | 历史报告不当作本轮重跑 |
| `docs/v0.4/NEXT-PHASE-READINESS.md` | 长讲解等待17–19秒、busy P95约14.25秒；恢复/官方平台仍待验 | P0目标采用语义段边界仲裁与持久身份统一解决；不承诺3秒外部播放 SLA |

另审查 `backend/db/migrate.go`：现有 runner 无跨进程 migration lock，Agent 2 必须处理部署串行 migration。旧行为的准确边界以源码为准。

## 对象、身份与关系

所有 ID 都是不可复用、非空、大小写敏感 opaque string，使用既有 `ids.New` 风格生成；不依赖时间顺序。外键查询必须包含受信任 tenantId/ownerId，ownerId 映射现有 config_principals.user_id。traceId 只用于关联；不能单独当全局输入幂等身份。

| 对象 / 稳定身份 | 生命周期与关系 |
| --- | --- |
| BroadcastRun / runId | 一场逻辑直播；tenantId/ownerId/roomId 不变。status 与 desiredState 分离；runEpoch 单调递增；currentSessionId/currentPlanId 可空；startedAt/updatedAt/endedAt；recoveryPolicy 默认 MANUAL_ON_UNKNOWN。终态不可复活 |
| RunSession / runSessionId | runId → 既有 live_sessions.id，多对一历史：每个 physical Session 仅归一个 run；保留各任期/绑定。不能把 Python Session 当 run |
| ContentPlan / planId | 属于 run；productId、productSnapshotVersion、revision、segmentOrder、generationSource、createdAt/updatedAt。版本不可变，切商品/事实改变需新 planId，不挪用旧文案 |
| SpeechSegment / segmentId | 属于 run+plan；sequence、content、textHash、state、utteranceId 可空、idempotencyKey、checkpointState、createdAt/updatedAt。textHash=精确 content UTF-8 SHA256，无隐式 NFC/空白重写；sequence 从1开始，唯一；segmentOrder 必须与其一致 |
| Turn / turnId | run 下 SCRIPT/COMMENT/OPERATOR/SYSTEM，priority、state、scheduledAt/startedAt/finishedAt。SCRIPT 必须 sourceSegmentId；COMMENT 必须 sourceCommentTraceId 及稳定 source identity 列表；其他两类两者均 null |
| ExecutionAttempt / attemptId | Turn 的一次实际执行；绑定 runEpoch+sessionId+utteranceId+commandId。一个 segment 多次经授权执行保留多 attempt；segment.utteranceId 是最新 attempt 投影，不替代历史 |
| PlaybackCheckpoint / checkpointId | append-only 证据，绑定 attempt 和单调 producerSeq；独立业务状态，见 STATE-MACHINES。必有 evidenceRef/producerIncarnation，无外部 audibility 推断 |
| DispatchIntent / intentId | attempt 的持久 Outbox；固定 runId/sessionId/utteranceId/commandId/idempotencyKey/runEpoch；状态、nextAttemptAt/claimedBy/leaseExpiresAt、createdAt/updatedAt。所有重试保留完整命令与 hash |
| RunLease / runId | leaseOwner/leaseExpiresAt/fencingToken/runEpoch/leaseVersion；fencingToken=本契约 runEpoch，作用域 runId；续租只增加 leaseVersion，接管增加 runEpoch |
| RuntimeInbox / commandId | Go 中持久 journal，Runtime 在副作用前通过专属内部 token 接受/标记执行；不把内存去重称为 durable |

runEpoch、Python generation_id、Worker epoch、Worker wire generation_id 是四个不同域。runEpoch 范围1..9007199254740991，永不回退/重用；同值只在同 run 下比较。Worker wire 值保留原协议，由 Runtime wrapper 将绑定映射到 attempt，不注入新字段。

## 统一执行主线

Agent 3 生成固定商品计划和完整语义段 → 已有 Scheduler 选择评论 → Turn Manager 在已证明完成的边界仲裁 → Agent 2 原子创建 attempt+既有 Utterance+Outbox → Runtime 外层 fence/exact-text adapter → 既有 TTS/GPU/media → journal checkpoint → Agent 2 原子收证据并推进投影 → Agent 3 选择下一话轮。

数据库从不承载 PCM/video。恢复只从持久对象、当前 fence 和真实证据推导；不是猜测重放。可证明的本地业务恢复不保证 RTMP 不断流；更换 physical Session 可能中断传输并要求重连。

## 交接门槛

本组冻结后允许 Agent 2/3 在同一基线独立开发：双方使用唯一 Schema/协议、Agent 2 唯一数据库 owner、共享热点交由集成 Agent。生产启用另需：竞争认领/事务/崩溃窗口/Stop竞态、Runtime journal 与输出隔离、真实媒体证据、旧路径回归。Schema 测试通过仅代表契约可消费；不代表 P0 已修复。
