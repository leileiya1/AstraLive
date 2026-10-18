# Agent 2 — durable-live-2 PostgreSQL / Authority handoff

本次为真实 SQL 与隔离 Authority 域实现，目标 integration/v05-durable-live，由 Agent4 审核。Durable LIVE 保持关闭；没有公共 HTTP/Runtime 接线，没有启动 GPU 或操作共享/生产数据库。

- 开工基线：`e98d8cf53d1aa5518f9c908785b7a5feae5117f8`。原 Worktree `AstraLive-agent-2`、原分支 `feat/v05-durable-recovery`；开工时干净，以 ff-only 同步，未 reset/force/stash/clean。
- 冻结：`c7fd46209d3cbc6f58541dba8b4e1c85609c823e`；22 文件 digest `3c0c317ed00f6fa4d2cf15ef3f61fc002d4bb22bf02d53ee9f1b407458bb28b1`。独立重算一致，000001–000006 保持原字节，见 [provenance](../evidence/agent-2/durable-live-2/provenance.json)。
- **正式 DTO SHA：`e3302f6b2bb19e0184cde3a6cbbcaf3ea4371565`。** 末轮 fetch 收到该交付后，在未覆盖现有修改的情况下 ff-only 同步；当前实现显式 import 这一唯一 Go wire 包，未复制 Schema/DTO。`New` 使用官方 strict validator，`Handle` 校验官方 operation/role/target/method/route、闭合 raw JSON 和生成类型；真实 SQL 消费通过官方 typed response 验证。新增 duplicate-key/extra-key/小数身份/角色/路由/Hash 测试。公共 HTTP/认证 Context/Runtime 入口仍由 Agent4 接线，此 PR 保持 Draft 待其独立审核。

实现与测试源码提交由交付元数据记录；原始 evidence 同时保留补丁前失败及修正后的通过记录。

## 实现范围

唯一新增迁移 [000007_answer_stream.sql](../../../backend/db/migrations/000007_answer_stream.sql)；代码在 [authority](../../../backend/internal/durablelivev2/authority/README.md)。复用既有 Run、租约、Slot、Turn、Attempt、Outbox、Runtime Inbox、Checkpoint、SSE notification 表；不建立第二业务数据库。

迁移包含 run revision 隔离、可信 process/key/install mirror、DB-time stage challenge、immutable bootstrap/registration sidecar、AnswerStream、完整 Artifact 正文/UTF-8 SHA256/hash/facts/version、Artifact child、Prepare 原始键与 alias/原始 receipt、FactObservation、Permit、one-shot Grant、仅 verifier 的 ticket、唯一消费 latch、execution knowledge、完整 Drain 身份回执、Observer evidence 和 audit。复合 FK/UNIQUE、条件更新、append-only/不可变/tombstone/revision 约束及 PUBLIC 权限撤销实际在 PostgreSQL 执行。

支持 CONTROL Registrar 注册 ACK 丢失后的有 scope 历史 repository readback（只读、无新 wire 操作），注册/撤销、Prepare、Permit/FactObservation 刷新、全局 START、Continuation、Drain、Seal、Answer/Execution Query、受限 Authority Query/Commit/metadata、Checkpoint、CONTROL Stop/UNKNOWN 和 bounded expiry recovery。操作与字段来自冻结协议；模块不挂路由。Backend 权威写、Guardian 只有三项受限调用、Runtime 没有业务 SQL 凭据。真实角色/token/peer/channel/SQL role 装配仍由 Agent4 接线。

外部 InstallationSource、Assertions、Observer、physical CheckpointProof 都在 Begin 前运行。缺失则拒绝。事务内复核当前 SQL sourceVersion/valueHash/snapshot、Provider Binding、lease/slot/session/epoch/producer、process incarnation、registration 与 output mirror；产品/身份行加共享锁，全部写操作先锁既有 Run。Agent4 的 source retirement、process replacement、epoch/session/output 安装必须使用同一 Run 锁域。锁与 statement 有界，validator 必须为本地无网络校验。

## 崩溃、Stop 与 UNKNOWN

- Prepare 的正文、hash、facts、child、receipt、alias、CAS 一次提交；失败无部分记录。重复返回原 receipt，不增加单元或授权。
- START/Continuation 同事务提交不可变 Grant、ticket verifier、unit/inbox CAS。仅首次 true 响应给明文 ticket；SQL、Query、重复响应及日志均不保存/返回可恢复 ticket。
- Consume 在 Run 锁内重新验完整 scope、当前 authority、原 Grant deadline/proof、nonce/channel/ticket verifier。唯一 latch + ISSUED→CONSUMED 条件更新原子；16 并发连接只有一个 true。重复同身份只能 false/null；不同身份冲突。
- Commit 后 Go 子进程 SIGKILL、响应未交付：新 Backend 保留原 latch，只返回 false/null。不能用 receipt/Query 重新授予 TTS 权限。
- Stop 不被陈旧 expectedRevision/失效 lease 否决。原子写 tombstone、seal term/lease、撤销 registration/ISSUED Grant、保留已消费 latch 并投影 UNKNOWN/audit；同时持久化每 Session 的稳定 STOP Outbox 意图及 CONTROL decision。重复 Stop 不膨胀任务。SQL Stop **不等于物理输出已隔离**。
- ReconcileExpired 有界扫描，再逐 Run 短事务复核 lease/旧 Epoch/command deadline/未消费 Grant 过期；生成真实 UNKNOWN Checkpoint、audit、notification 与幂等回执。保留业务 Slot/消费证据；旧 utterance 投影 INTERRUPTED/RECOVERY_UNKNOWN，避免旧 busy gate 永久悬挂。没有无条件重发、重建 Session 或重播。
- Unit1 trusted Drain 后，同一 Turn/Attempt/Session/Generation/registration 的 Unit2 使用独立 Artifact/Grant/execution；Unit Finish 不写 Run Stop。只有 seal + 连续 all-required trusted drain + CONTROL business commit 释放 Slot。
- UNKNOWN 不自动转 ACTIVE。真实 sink 尾部不明、Runtime/Guardian 重启、两层 ACK 丢失、旧身份/过期 Binding 等保持拒绝，待独立物理证据与人工对账；本模块不声称自动重建 Session/连续推流/观众 exactly-once。

## 测试和原始证据

[证据目录](../evidence/agent-2/durable-live-2/) 保留命令、exit code、原始日志和隔离 PostgreSQL inventory。真实 PostgreSQL 17.11，loopback 独立 initdb，fsync on；Redis 为另行新建的专用实例；测试只终止自己启动的 Go/Python 子进程或自己持有的 DB connection。

| 验证 | 结果 / 边界 |
| --- | --- |
| 真实 PG Authority race | 30 PASS、0 FAIL、1 helper SKIP；含多连接唯一消费、Prepare 并发、alias/Drain scope、回滚、Stop×Commit/首次注册、旧 Epoch/Generation/跨租户拒绝、过期 facts/proofs/Binding、unused Grant ACK loss、UNKNOWN audit、提交后专用 Go SIGKILL |
| 000006→000007 / 空库 / 并发迁移 | PASS；保留旧 product 字节与 v1 run revision；4 个并发 migration runner；实际低权限 SQL SELECT/INSERT 被拒绝 |
| 137 契约、11 Journal、13 官方跨语言 wire、两 Validator | PASS；22 normative 文件及 313 protected hashes 未改 |
| Runtime regression | 169 PASS、11 opt-in SKIP、50 subtests PASS；cwd=runtime，PYTHONPATH=runtime:repo |
| 全 Go race | **未经补丁原样运行 FAIL**：唯一共享测试把 migration 数写死为 6；其余包通过。独立补丁经临时 overlay 后 172 PASS、0 FAIL、11 SKIP，未改共享文件 |
| go vet | PASS |

共享补丁：[agent-2-v2-shared.patch](../integration/agent-2-v2-shared.patch)，仅调整共享集成测试的迁移数 6→7；交 Agent4 应用。overlay 文件在临时目录，不在原工作树落地。完整 Go 日志逐项列出 opt-in SKIP；whole-server PostgreSQL outage 未运行，旧测试硬编码专用端口，未挪用实际服务。旧真实连接中断恢复、Redis stream/reclaim 与专用 Redis outage 已执行。

独立重跑 SQL：

```sh
python3 backend/internal/durablelivev2/authority/run_postgres_acceptance.py
```

脚本创建新的 loopback PostgreSQL 集群，覆盖测试 DB 环境变量；最终只停自己的集群，保留 data/logs。要求本机 PostgreSQL binaries、Go；不使用现有 DATABASE_URL。已验证该脚本完整执行。其他准确命令见 `contracts-results.json`、`postgres-results.json`、`runtime-regression.json`。Helper 的顶层 SKIP 是由父测试专门启动的 SIGKILL 子进程，不能误计为未执行的故障注入。

时延只测本机 race 模式 SQL 域调用，12 个样本；Prepare+Permit+START 与 Backend Consume P50/P95 见 `SQL_LATENCY` 原始日志。没有测 LLM 首句、网络 RPC、Guardian fsync/最终 gate、媒体传输或观众时延，不能据此承诺 3 秒 SLA。

## Agent3 / Agent4 接线

Agent3 使用同一 durable Turn/Attempt 和正式 Agent4 DTO；正文、语义边界和断言由 Agent3 产出，通过 Prepare/Continuation/Drain/Seal 操作持久化，不直接写本迁移。商品事实必须来自 `ProductProjection` 的权威 sourceVersion/valueHashes；Assertions 适配器要验证实际正文，不可信任 Runtime 声称的空依赖。当前 tests 的语义/物理 callback 为显式 synthetic fixture。

Agent4 后续需要：

1. 复核已固定的 DTO SHA 与本模块 `Handle` typed adapter，接正式认证 Context/transport/错误响应；不得把 `Actor` 从请求 JSON 解码。官方 Go DTO+SQL 已测，真实私有 HTTP/IPC 仍未测。
2. 接可信 installation/process/key source 与 CONTROL registrar，保护 process retirement 与 Run/Epoch/Binding 锁顺序；shared HTTP/Runtime 文件由 Agent4 修改。
3. 将 revision-scoped Outbox/STOP dispatch 与本 Backend Journal 接线；不得把 v2 run/command 送入旧 v1 handler，不能给 Runtime/Guardian DB DSN。
4. Runtime coordinator 使用首响应 ticket，先 Guardian durable consume/fsync/final ACK 再 TTS；ACK 丢失与 UNKNOWN 不可恢复能力。保持 pending nonce、原 channel、期限和 once-TTS latch。
5. Agent5 用真实受限 Authority client、独立 Observer 和可撤销真实媒体边界验证 Unit2、Stop/Restart/旧 output；这些不由 SQL PASS 推断。
6. 验证 notifications→SSE 的至少一次重发/客户端去重边界；DB notification 已持久化，实际 SSE 广播仍未接线。
7. 应用共享测试补丁，独立审核迁移和完整 scope/SQL 权限，再进行跨进程 CPU 集成。此 PR 不能直接进 main。

## NOT TESTED / 回滚

真实跨进程 DTO/HTTP interoperability、公共 HTTP/受限 IPC 认证、真实 Registrar installation 来源、实际 LLM/assertion 提取、Guardian fsync/ACK/物理媒体边界、Runtime v2 TTS、Worker/真实 GPU、Publisher/Decoder/Sink/RTMP/WebRTC/观众、跨主机故障、整机重启和生产发布均 NOT TESTED。现有 v1 Provider Binding、Comment Scheduler、SoulX/PTS/Credit/Worker wire 与媒体文件原字节保留。

回滚应用先关闭 v2 新准入、Stop/取消并隔离旧输出；无法证明安全则保留 UNKNOWN/Slot/output reservation。迁移无破坏性 down，不删除 latch、注册、审计、正文或去重证据，不把活跃 v2 run 改为 v1。实际业务数据和模型均未修改。
