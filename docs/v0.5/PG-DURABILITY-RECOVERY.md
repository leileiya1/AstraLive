# v0.5 PostgreSQL Durability & Recovery — Agent A

交付范围：普通 Session / Utterance / Interaction 的持久派发、执行去重、事件接收与保守恢复，以及增量提供给 C/B 的 Continuity 事务接口。默认关闭；可选择完全不连接 Redis 的 PostgreSQL-only 模式。本文的完成证明不包含观众听到声音、Timeline 的所有 sink 播放确认或 Narration 连续恢复。

## 基线与共享文件

- 工作分支：`exp/v0.5-pg-durability`，独立工作目录 `AstraLive-agent-a`。
- 用户核对基线：`cf6540bdcc788c037929836480812dfaa78362a2`。
- 开工 HEAD：`5a24478126211cbcde5a9565d0c6063748426527`；与基线只有 F 的两项文档提交，无源码变化，工作目录起初干净。
- 已读并遵循 F 的 `ARCHITECTURE-CONTRACTS.md` / `INTEGRATION-PLAN.md`，冻结修订 `v0.5-frozen-1`。沿用 TEXT ID、配置名、独立 journal token、语义指纹、运行租约及保守 UNKNOWN 策略。
- 除 A 主要文件外，必要接线涉及 `interaction.go`、HTTP 幂等中间件、Runtime client、Python main/session。没有修改 frozen v1 OpenAPI / event schema、Narration 状态机或旧 Redis 消费实现。共享文件仍须集成方 B/C/F 审查；没有假定其他 Agent 已 ACK。
- 待 F 审查的具体扩展：`RUNTIME_EVENT_SPOOL_DIR` 本地私有持久卷配置；BEGIN_RUN 的 `createSession` / `fenceOnly` 实现字段；journal 的 `/media-start`；非持久 emergency-stop 503 响应。它们没有新增业务完成状态或改变 frozen transport flag。

## 数据与完成层级

迁移 `000006_pg_durability.sql` 为增量迁移。迁移 runner 在专用数据库连接持 advisory lock，避免多个实例同时初始化空库。旧查询与 interaction enum 保留。

| 数据 | 内容与事实边界 |
|---|---|
| `v05_outbox` | immutable command envelope、语义 key/hash、序号、派发 lease/token、attempt、下一次派发、UNKNOWN 起点；发送控制状态 |
| `v05_inbox` | Runtime 接受结果、稳定 operationId、执行 attempt/incarnation、执行 token、generation/timeline；执行去重事实 |
| `v05_receipts` | 追加的接受、执行开始、生成、控制完成及旧媒体阶段证明；按 command/revision 唯一 |
| `v05_events` | 稳定 eventId / producerSeq 唯一，事件体与 hash、APPLIED/STALE/DEAD 游标、错误与失败次数 |
| `v05_session_runs` / `v05_recovery_leases` | scope、绑定快照、epoch、owner/token、控制 barrier、generation 高水位、恢复游标 |
| `v05_interaction_commands` | 与旧 `interaction_receipts` 关联；保留 RESERVED/ACCEPTED/FAILED，详细执行状态从 journal 联查 |
| `v05_recovery_audit` | takeover、人工复核原因与运行 epoch |

状态分层，而非把 ACK 当作播放完成：

| 用户要求的概念 | 存储表达 |
|---|---|
| PENDING | outbox PENDING |
| CLAIMED / DISPATCHING | outbox CLAIMED + fenced lease；派发中也不能证明 Runtime 未接收 |
| ACCEPTED | inbox ACCEPTED，接受 receipt；outbox ACKED 只证明接收/对账 |
| PLAYING | 旧 Utterance PLAYING + immutable legacy stage proof；inbox STARTED |
| COMPLETED | 旧 Utterance COMPLETED = Runtime 媒体 drain 事件；inbox TERMINAL 防止重复逻辑执行；v0.5 receipt 保持 unknown 的完成证明层级 |
| INTERRUPTED | 旧 Utterance INTERRUPTED + interrupted stage receipt |
| FAILED | 证明未发出的派发耗尽时 outbox FAILED；旧任务失败保留，receipt 不伪造所有 sink 的终结证明 |
| UNKNOWN | 发送/进程/物理副作用证据不充分；不转换成可自动重播的失败 |

`Observe` 的 completed 仅允许控制命令，表示该控制操作已执行。SPEAK 不允许用这个接口声称 SegmentCompleted。增量 000007 已提供 Timeline ledger、严格 sink proof 校验和 C 同事务 callback；000008 与字段限定的 proof canonicalization 保留独立 Worker wire ID 的正 63 位整数域，业务 ID 上限不变；详见 [A-owned 接线契约](../../backend/internal/durability/CONTINUITY-SEAM.md)。B/C 的完整接线与 Narration 连续恢复仍未在本分支验收。

## 事务、派发与去重

普通 Speak 的 Utterance、互动 RESERVED/关联、状态和 outbox 在同一 pgx 事务提交。Start 的 PREPARING 与 BEGIN_RUN、Stop 的 STOPPING/tombstone/barrier 与 STOP_SESSION 同样原子提交。HTTP Start/Stop/Speak 的 Idempotency-Key 响应缓存也在此事务提交；响应在 commit 前缓冲，消除成功业务事务与响应缓存之间的崩溃窗口。

Dispatcher 独立轮询，`FOR UPDATE SKIP LOCKED` 安全认领。16 个有界派发槽，同 Session 按序，Stop/FORCE 控制可绕过被阻塞的媒体派发；100ms 轮询兜底，不依赖 NOTIFY。认领有效期10秒，每3秒续租，单次 HTTP 上限8秒。过期 CLAIMED 成为 UNKNOWN，旧 claim token 的 ACK 更新失效。

只对已证明 TCP dial 未发送，或 journal 明确 ACCEPTED 且尚未执行的命令重试原 envelope。最多5次，250/500/1000/2000ms 加不超过20%的 jitter；耗尽未发出命令进入 FAILED 并终结尚未启动任务。HTTP 超时、断连、接收后丢 ACK 均为 UNKNOWN，先查询证明。404/无 receipt 不构成“没有播放”的证明。UNKNOWN 对账预算30秒，耗尽将运行置 RECOVERY_REQUIRED 并写审计，停止自动媒体工作。

同 commandId 相同请求返回稳定 operation/接受结果和当前 receipt；不同语义请求或 envelope 被拒绝 COMMAND_CONFLICT。Go/Python 共享 canonical fingerprint golden vectors，涵盖 Unicode、HTML 字符、反斜杠与整数限制。浮点、重复 JSON key 和不安全整数不可进入命令指纹。

Runtime 必须先持久 Accept，再持久 StartAttempt，才进行外部副作用。开始 marker 的 CAS 仅成功一次。进程内 `seen_utterances` 只是旧实现优化；进程重启后的 journal 查询把旧 incarnation 的 STARTED 变为 UNKNOWN，不再执行它。媒体出队前 `/media-start` 持久分配大于已安装 generation fence 的编号；重复申请、错误 incarnation、过期 token/epoch/barrier 被拒绝。事件携带 attempt/generation/timeline 时必须匹配存储值。

## 事件可靠性与安全

Python publisher 在私有持久目录中使用 SQLite WAL + synchronous FULL，只承担待送事件 journal。publish 返回前已落盘；稳定 eventId/hash/producerSeq 支持重启重送。Go 成功提交 PostgreSQL event 后才 ACK，Python 删除 raw pending body，保留 identity/hash 元数据防止同 id 改体或再次提交。ACK 丢失重送仍是幂等。冲突保留为 CONFLICT；未确认事件不淘汰；pending 上限10000，满时 fail closed。重试指数退避封顶30秒，没有仅内存重试队列。增量 TimelineJournal 同样在 POST 前将 proof 写入该磁盘 journal；重送只提交观察，不解除 B 的 blocked 状态、不重生成媒体，也不根据本地旧 ACK 绕过当前 Go fencing。

Go event ingest 通过独立机器角色鉴权，不接受浏览器 cookie，也不接受调用者自报 tenant/user；scope 来自已持久命令、Session 与 Room owner。token 文件必须私有、角色不同。Python HTTP 禁代理、禁重定向、不自动重试 POST；Go→Runtime 保留现有 TokenTransport。日志不输出 token 或原始业务文本。

PostgreSQL event processor 把 FSM 投影、旧 events 表、receipt 与 APPLIED 游标放进同一事务。并发 worker SKIP LOCKED；同 Session 数据库锁协调 Stop/恢复。缺少前置事件的乱序 stage 保留 PENDING，每秒重试，最多30次进入 DEAD；重复/倒退不回退业务终态。旧 epoch、退休 run 或失效 ACTIVE lease 的迟到事件落库为 STALE，供审计，不能推进当前工作。

PG raw envelope、未确认 spool 与冲突数据不自动删；当前没有自动 retention/purge。运维必须配置容量监控，并制定与审计保留期一致的归档策略。已确认 spool 不再保留原始事件文本。事件产生与物理设备副作用之间无法原子提交：进程若在输出之后、创建终结事件之前崩溃，会留下 STARTED/UNKNOWN，而非伪造终结事件。卷丢失也按这个边界保守处理。

## 恢复、Stop 与锁

Coordinator 独立续租（2秒 tick，2秒超时），扫描未终结运行和命令，查询 Runtime receipt。未启动且有明确 ACCEPTED 证明的命令可重送同一 envelope。已启动、已终结、缺少证明或已停止的旧媒体任务均不自动重播。

运行 lease 过期后，在同 Session 锁下获取新 owner/token、提升 runEpoch，退休旧运行，把旧未发媒体取消、旧 STARTED 标为 UNKNOWN，提交审计和 fence-only BEGIN_RUN。它只安装取消 fence，不创建 Session、不恢复媒体、不宣称新 epoch 健康。新运行保持 RECOVERY_REQUIRED，交由业务或人工策略处理。Stop 已进入 STOPPING 时保持原 epoch 的清理状态，不能重新进入 ACTIVE。数据库业务 ENDED/FAILED 同样封存运行。

推荐人工处理：查询 command/run/receipt 和旧事件，确认不会继续旧媒体；对已 LIVE/DEGRADED/STOPPING Session 发带新 HTTP Idempotency-Key 的 Stop，待 ENDED 后创建新 Session 和新的绑定快照。初始化失败或 RECOVERY_REQUIRED 的 PREPARING/READY Session 暂无自动恢复入口，需集成方制定显式终结/替换策略，不能直接 UPDATE 成 LIVE。没有“未知是否播出就重播”的开关。

durability 模式不再持有旧全局 `Service.commands` 跨 HTTP 锁：进程内使用 Session 锁，跨实例由 Session 行锁、条件更新、控制 barrier 与 fencing 维护。事务不包含 Runtime HTTP；不同房间不会因一个慢 Runtime 请求持全局业务锁。legacy 模式保留旧锁和流程以控制兼容风险。Runtime watcher/副作用入口检查 lease/barrier，过期立即本地取消；实际最终音视频 sink 的完整 tuple 校验仍需 B 的实现与长会话验证。

PG 故障时不能接受持久新工作。已完成权限核对的 Stop 请求若在事务开始时数据库断连，会尝试受控制角色保护的本地 emergency-stop，且仍返回失败，不返回202或持久成功。Runtime emergency endpoint 自身返回503并标记 durable=false；无足够权限证明时依赖现有 lease 的到期 fence，不放宽权限。

## 配置与模式对比

两端须一起开启，保留现有 v0.4 认证、Session binding 配置及可用 PostgreSQL：

```sh
ASTRALIVE_DURABILITY_ENABLED=true
ASTRALIVE_EVENT_MODE=postgres_only
RUNTIME_JOURNAL_TOKEN_FILE=/private/secrets/runtime-journal.token
# Runtime：现有 Backend URL；独立私有持久卷，目录0700、文件0600
CONFIG_BACKEND_URL=http://127.0.0.1:8080
RUNTIME_EVENT_SPOOL_DIR=/private/astralive/runtime-events
```

这些路径为示例。通过既有安全部署流程生成独立 token，不能复制 control/Tool/identity/worker token。启动自动应用增量迁移；postgres_only 会跳过 Redis URL 解析、连接和 readiness 检查。PG 故障不降级到 memory。Runtime/Go 的 transport flag 不一致应视为部署错误。

| 模式 | 事件/命令事实来源 | Redis 依赖 |
|---|---|---|
| durability=false + legacy_redis（默认） | 原有 HTTP / Redis Stream / consumer group 流程 | 保留原要求；没有本分支的可靠派发保证 |
| durability=true + postgres_only | PG outbox/inbox/receipt/event；Runtime 磁盘待送 journal | 完全无依赖；invalid Redis URL 也可启动 |
| durability=true + legacy_redis | durable journal 仍为 PG 真相 | 保留 Redis readiness/连接要求；当前没有双写镜像，不运行旧 Redis consumer 投影 durable 事件 |

Redis Streams、XAUTOCLAIM 和 publisher 保留未删除。最后一种组合适用于保留旧部署依赖，不能宣称已实现 Redis/PG 双写一致性。

机器接口只应在受保护的内部网络可达：

- Go `/internal/v0.5/durability/{accept,start,grant,media-start,receipts,events}`。
- Go GET `/internal/v0.5/durability/sessions/{sessionId}/commands/{commandId}` 返回 scoped command/receipt proof。
- Runtime POST `/internal/v0.5/sessions/{sessionId}/commands`；GET `.../{commandId}/receipt`。
- Runtime POST `/internal/v0.5/sessions/{sessionId}/emergency-stop`，非持久取消，响应503。

数据库只读查询模板在 `backend/db/queries/durability.sql`，由现有 sqlc 1.30.0 生成。GetDurableCommand / GetInteractionCommandState 同时展示派发与执行状态；ListRecoveryRequiredRuns / ListDeadDurableEvents 供 scope 内审计。访问需现有 owner 权限，不能将内部接口直接给浏览器。

## 测试与证据

可复现入口 `backend/scripts/test-durability-faults.sh`：创建自己拥有的临时 localhost PG cluster，以随机端口隔离；退出只清理 ownership marker 匹配的测试 cluster。不会停止共享 PG/Redis，不启动付费 GPU。

```sh
DURABILITY_PG_BIN=/opt/homebrew/opt/postgresql@17/bin \
DURABILITY_TEST_PYTHON=/path/to/runtime-python \
backend/scripts/test-durability-faults.sh
# 额外 Runtime 全量回归
cd runtime
PYTHONPATH=.. /path/to/runtime-python -m unittest discover -s tests -v
```

Go 测试需 `DURABILITY_TEST_DATABASE_URL`；真实 legacy SQL 回归另设 `CONFIG_TEST_DATABASE_URL`。没有这些配置会明确 SKIP，不能算数据库验收。脚本设置二者并串行执行 package，正常 Go + race 均启用真实数据库。故障脚本还测试真实 PG stop/start、Python durable unit 与 v1.1 contract validator。CPU Runtime 测试需对应 Python 依赖，不使用真实 LLM/TTS/GPU/RTMP。

| 故障 / 并发 | 测试与实际层级 |
|---|---|
| commit 前 / commit 后且 Runtime 未接收 SIGKILL | TestTransactionSIGKILL，真实 Go child + PG；前者无任务/命令，后者二者均可发现 |
| Runtime 接受 / start 后 ACK 断连 | TestAcceptedBeforeLostACK，真实 HTTP hijack close；UNKNOWN 查询证明而非新执行 |
| Runtime 播放中 SIGKILL、Runtime 重启 Go 不重启 | TestRuntimeProcessCrashRedisOff，真实 uvicorn child、CPU 模拟 sink 已写后 SIGKILL；新 incarnation UNKNOWN，同 command 不再产生模拟输出 |
| Go SIGKILL、Runtime 保持同一 PID、Go 重启 | TestPostgresOnlyServerStartup，真实 server binary + uvicorn；同 HTTP key 返回同逻辑 JSON，只有一条 Utterance/首次模拟 sequence，Stop 可达 ENDED |
| 双 Dispatcher / lease 过期 / 旧 ACK | TestTwoDispatchersLeaseExpiryOldAck，真实并发 PG row locks；旧 ACK CAS 被拒 |
| 旧 epoch 命令迟到 | TestRecoveryStopRaceAndOldEpoch、TestForceFencesDelayedSpeakAndStopExpiredRun；不能开始旧媒体 |
| 同 command 同体 / 改体 | TestPostgresJournalIdempotencyAndFences，稳定 operation；改体409，无重复 start |
| generation / attempt / event fence | TestMediaAttemptGenerationAndEventFence，新 generation 超过 floor，重复 media-start、错误 executor/事件 generation 拒绝 |
| 重复、乱序、迟到事件 | TestEventDupConflictReorderAndTerminal；相同 id 幂等、改体拒绝、前置缺失缓冲、终态不倒退 |
| Redis 完全不可用 | 两个真实进程测试；PG-only server 甚至使用无法解析的 Redis URL，仍 ready 并完成事件入库 |
| Go 不可用时 spool 重送 / Runtime 重启 spool | Python durable disk restart/outage 测试；真实进程 Go 重启期间的 warning 重送 |
| PG 短暂不可用恢复 | TestOwnedPostgresOutage，只对脚本自己 cluster 执行 pg_ctl stop/start；断连拒绝接受，恢复后同命令仍幂等 |
| 不同房间 Speak/Stop、慢房间 SQL 锁 | TestDifferentRoomsAndConcurrentSpeakStop；一个房间持锁时另一个独立提交 |
| Stop 与恢复同时发生 | TestStopConcurrentWithRecovery，真实并发事务；Stop tombstone 不被恢复撤销 |
| 未发重试耗尽 / UNKNOWN 无证明 | TestBoundedUnsentRetryDeadLetter、TestUnknownProbeBudgetAndNoReplay；5次边界、30秒复核预算、404不重播 |
| 增量迁移、并发 migrate、回放 | TestMigrationConcurrentAndReplay + 每个测试全迁移独立 schema |

最终执行结果和环境版本见同目录 `evidence/agent-a/VALIDATION.md` 与原始日志。Python 原有 suite 的 skip 原因保持原样，没有把 skip 当真实服务通过。启用 legacy 数据库回归发现原 interaction audit fixture 删除顺序违反外键；仅调整为先删 receipt 后删 utterance，保留原断言。

逻辑“恰好一次”指 stable command/accepted operation + at-most-once durable StartAttempt、已明示终结任务不再执行。物理音频不是与 PG 同一事务；播放后失去证明进入 UNKNOWN，并可能保守停止一个其实尚未播出的任务。CPU 模拟输出次数只能验证软件调用边界，不能证明观众声音恰好一次。真实浏览器播放、SoulX/GPU、RTMP、跨主机时钟、Timeline sink ACK、Narration 续播与长时间停顿后的最终 sink fence 尚未验收。

## 回滚与运维边界

迁移 additive，不提供破坏数据的 down migration。回滚前关闭新工作入口，Stop/安装 fence，核查 journal 中 STARTED/UNKNOWN，待运行封存并停止 durable dispatcher。保留所有 PG journal、spool 与 UNKNOWN 审计；不能删表/清空 spool 来“重试”。然后两端同时回到 durability=false / legacy_redis，恢复 Redis 服务，只创建新 Session。切换旧存活的 durable Session 到 legacy HTTP 可能绕过去重，因此不支持该操作。

租约在不可用期间保守失效；PG 恢复后发现未完成任务、退休 epoch、人工复核优先于媒体连续性。若操作人员需要自动恢复 Narration，必须先取得 B/C/F 对合法 checkpoint、sink proof 和新 epoch 契约的冻结与验收，不能根据旧 COMPLETED 或内存 seen 集合推断。
