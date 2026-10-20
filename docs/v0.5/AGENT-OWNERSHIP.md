# durable-live-1 Agent Ownership / ARCHITECTURE HANDOFF

获批v2实施的当前所有权覆盖表见 [implementation/ownership.json](implementation/ownership.json) 和 [IMPLEMENTATION-BASELINE.md](IMPLEMENTATION-BASELINE.md)；Agent4独占共享入口/统一DTO，Agent2独占000007/Authority，Agent3独占策略，Agent5独占Guardian。以下原durable-live-1分工保留，不能用其旧Runtime归属并发覆盖新公共接线。

> CCR-ADL-001 review at PR8 `01a752baf79c25d4d268167d016c8c62e754cfdf`: active durable-live-1 is preserved. [durable-live-2 incremental answer candidate](ccr/CCR-ADL-001.md) and [migration/owner handoff](ccr/CCR-ADL-001-HANDOFF.md) are PENDING OWNER ACK; this historical v1 freeze does not approve that upgrade.

**契约设计冻结，可允许 Agent 2 与 Agent 3 在 main `cf6540b` + 本PR交付提交上并行开发。** 该许可是接口/数据模型准备完成，不是v0.5功能上线或P0验收通过；不授权集成实验分支或自动merge。两Agent开工均需记录完整交付SHA、contractRevision=durable-live-1并回复ACK；禁止使用浮动main或另行发明Schema。

| Owner | 独占实现范围 | 不得自行修改 |
| --- | --- | --- |
| Agent 1（本交付） | docs/v0.5本组7文件；contracts/v0.5/durable-live/**；tests/test_durable_live_contracts.py；scripts/validate-durable-live-contracts.py | 正式migration、运行时业务实现、既有冻结v1.1 |
| Agent 2 Durable Execution | backend/internal/durablelive/**；必要Go持久层与SQL queries生成；唯一正式新migration；Outbox/Recovery/Session reconciliation/Lease/Fencing；新增runtime/app/durable_live_journal.py客户端及输出permit协议实现草案 | Planner/Turn策略、第二套评论Scheduler；共享热点接线必须提交集成patch |
| Agent 3 Turn Manager | backend/internal/contentplan/**、backend/internal/turnmanager/**；Content Planner、语义分段、计划编排、话轮公平仲裁；runtime/app/durable_live_segments.py纯新增exact-text辅助模块 | 任何DB migration/独立数据库/repo SQL、Lease/Recovery事实规则、旧Runtime全局FSM |
| 最终集成 Agent | 共享app/httpapi/runtime接线、DTO生成与接口编译适配、feature flag、guardian部署/输出隔离、端到端回归；按顺序整合A2再A3 | 未经CCR改语义；不得据文档测试宣称媒体验收 |

共享热点明确锁定：`backend/internal/app/service.go`、`backend/internal/app/interaction.go`、`runtime/app/session.py`、`runtime/app/session_binding.py`、`backend/internal/httpapi/server.go`。额外共享 `backend/cmd/server/main.go`、`backend/internal/eventbus/consumer.go`、`runtime/app/main.py`、`runtime/app/bound_media.py`、生成DTO及 `interaction/scheduler.go` 接线由集成Agent所有。A2/A3提交各自独立patch/接口说明，不并行覆盖热点；Scheduler纯策略改动也先请求集成协调。

## 接口交接与验收责任

双方都消费 `protocol.json` 全部operation及schema refs。Agent3对 ClaimNextTurn/DispatchTurn 等可用显式Fake seam单测策略；Agent2用固定机器样例做存储和journal测试，无需猜内容策略。Agent2负责所有业务持久化（含plan/turn repo方法），Agent3通过SaveContentPlan/AdmitTurn调用。接口签名调整只通过CCR后同步DTO+schema+例子+测试；不允许“先实现再由对方适配”。

Agent2最低证据：PostgreSQL FK/unique/CAS、两个Backend竞争、SKIP LOCKED、提交后crash、lost202、STARTED歧义、lease expiry/旧epoch/Stop竞态、无SQL事务等待网络、cleanup/rollback。Agent3最低证据：中文数字单位/价格/否定完整语义、2–4秒估计与超长拒绝、固定商品和动态事实过期、评论边界/公平预算/TTL/override、重复selection/yield、UNKNOWN不越过cursor。集成Agent最低证据：legacy v1.1/0.4回归、真实journal与guardian fail-closed、当前段drain、恢复/Stop/切商品，并将Chrome、本地RTMP、官方观众验收分别记录。

## 变更与已知门槛

实验分支已有 `v0.5-frozen-1`，本组未改变其文件。将本设计接到该分支前，必须提交CCR解决runEpoch范围（run vs Session）、narration与plan/turn映射、表/迁移及Runtime命令入口；没有解决就只能在本基线隔离开发，不能宣称与已有A/B/C/D/E实现可直接拼装。

输出guardian、Runtime exact-text执行、持久journal均为待实现门槛；现有Runtime generation与credit不能代替它们。默认关闭，不启动收费GPU，不修改模型/TCP/PTS，不自动合并main。

基础验证命令：`python3 scripts/validate-durable-live-contracts.py`（环境需tests/requirements.txt）；再运行既有v1.1合约与Go回归。最终PR说明应记录实际测试命令/数量及未测媒体层，不能把Schema验证称为故障恢复验证。

本次交付的实际结果：[验证清单](evidence/contract-checks.json)及同目录原始日志。Schema验证通过：69个定义、20个操作的请求/响应、14个对象样例、4组hash vectors、5个FSM、44个基线文件hash；Python契约测试17项通过（新增14+既有v1.1三项）；`cd backend && go test ./...`通过。数据库依赖测试按现有测试环境可能skip，该结果不是实际v0.5 PostgreSQL恢复验收。真实GPU/Chrome/RTMP/官方平台、v0.5故障注入均NOT TESTED。
