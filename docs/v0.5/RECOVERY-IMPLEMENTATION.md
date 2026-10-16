# Agent 2 — Durable Execution 实现

契约：`durable-live-1`。基线 main `7fe5d24810e2df348c58dd7748e97ffbe5cff384`，包含契约提交 `ae28144d15afcf0e5f5ea8fa425fc42d27fc047b`。实验分支的 `v0.5-frozen-1` 未集成，也没有重用其表或迁移。

## 已实现的调用顺序

旧路径为 `interaction_receipts.RESERVED` → 独立创建 Utterance → Runtime HTTP → 独立更新 Receipt。Runtime 的 `seen_utterances` 只属于当前 Python 进程；Redis `ApplyEvent` 提交后发布 SSE。因此 RESERVED、QUEUED 和 HTTP 错误均不能单独证明是否执行过。

新路径由 `backend/internal/durablelive` 独占实现：

1. Agent 3 使用冻结的 `SaveContentPlan` / `AdmitTurn` 保存计划或 Scheduler 已选话轮。READY 不代表已经获得执行权。
2. `ClaimNextTurn` 短事务锁 run，核验 scope、Session Binding、商品、任期、TTL、slot。话轮转 DISPATCHING、既有 Utterance、Attempt、PLANNED checkpoint、原 Receipt 唯一键、不可变 Outbox 在同一事务提交。
3. Dispatcher 先读候选 run ID，再按 run → lease/slot → turn/attempt → Outbox 的顺序访问。run 与 Intent 都使用 `SKIP LOCKED`，每批最多 64 个认领，最多 4 个并行网络请求。每个网络调用之前先单独提交 SEND_STARTED；事务不等待 Runtime。
4. Python `ExecutionInbox` 查询 SQL Journal，持久 ACCEPT 后才建任务；START 必须匹配已登记 producer、当前任期、有效短 Permit、未 Stop、未过期输入。首次 CAS 返回一次性 `startAuthorized=true`；重复请求不重放 true。
5. Sink 的 PLAYING / 全 required drain 证据按事件及 producer 序号去重。CONTROL 验证 drain 链后才提交 BUSINESS_COMMIT，并原子更新 Turn、Segment、连续完成前缀、slot 与通知。
6. Coordinator 启动即扫描，随后按 SQL last_reconciled_at 公平轮转，定时扫描过期 Lease、Intent、未决证据和 Stop cleanup。缺失 Journal / 断连 / START 歧义进入 UNKNOWN；不重新发媒体命令。

`Store.Call` 是冻结 Schema 的统一 seam；生成的类型方法使用同一实现。17 个 Backend 操作与 3 个 Runtime 操作均沿用冻结名称和请求/响应。生成器复制本地闭包，测试逐字比对原 Schema 并验证 Go/Python hash vectors，未增加 wire 字段。

## 数据库与并发

新增 `000006_durable_live.sql`，不修改 000001–000005。`dl05_*` 表包含 scope 复合 FK、稳定身份 unique、不可变信封/证据 trigger、计划连续序列 deferred trigger、RunSession/Attempt/Outbox 关联检查。Session 接入与 Utterance FK 插入串行化；deferred trigger 阻止 legacy 与 durable 双调度。

Migration runner 使用独占连接持有 PostgreSQL advisory lock；错误时不把仍持锁的连接归还连接池。事务有有限 lock/statement timeout。新路径不使用 Service 全局 commands 锁；按 run 行锁实现 Stop、Operator、自动话轮的最终准入顺序，跨进程通过 Lease/Fencing 验证。旧路径的全局锁未被擅自替换。

权威事实为 PostgreSQL；Redis 是可选通知。SQL 暂不可用时拒绝新的 effect/Permit。短 Permit 到期后关闭本地 handoff；不能把这等同于平台观众静音。

## 恢复与人工处理

- 从未认领、没有 SEND_STARTED 的 PENDING 意图仍保留原命令身份；只有合法原任期 owner 可以发送。接管后不改写旧信封的 epoch。
- 旧任期已证明未发送的任务可终结为 INTERRUPTED/NOT_EXECUTED；是否重建下一脚本话轮由 Agent 3 根据业务检查点决定。
- UNKNOWN 保留证据与占用槽，直到输出隔离得到证明。`ResolveUnknown` 使用冻结 Decision 对象，记录 WAIT、显式 gap 或新话轮决定；gap 不计为 COMPLETED。
- `SealNotExecuted` 要求独立输出隔离且 START 从未提交，持久封存旧 executor。普通查询的 404/空内存不具备该证明。
- Legacy RESERVED/QUEUED 默认只记 `LEGACY_UNKNOWN` 审计，禁止自动导入或重播；先停止/隔离旧 Session，再新建 durable run。

共享文件只有独立补丁，当前正式 main 入口未启用新模式。部署和端到端限制见 `AGENT-2-HANDOFF.md`，验收边界见 `RECOVERY-ACCEPTANCE.md`。
