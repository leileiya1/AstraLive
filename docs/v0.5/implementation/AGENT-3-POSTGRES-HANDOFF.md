# Agent 3 — real PostgreSQL streaming interop handoff

状态：独立 Backend 域联验完成，交 Agent4 复审并接线；生产 Durable LIVE 仍关闭。真实 PostgreSQL Authority、七条正式迁移、正式 Go wire DTO 已运行。Registrar、Receiver/Guardian ACK、Observer、物理安装来源仍为显式合成 fixture，不能据此认定真实 once-TTS、媒体或 required Sink 验收通过。

## 固定输入与同步

- 原 `AstraLive-agent-3` / `feat/v05-turn-manager`，沿用 Draft [PR12](https://github.com/leileiya1/AstraLive/pull/12)，目标 `integration/v05-durable-live`。没有新建 Agent、Worktree 或分支。
- 原 PR12 HEAD `3c5c6343391b0c1264cf6aad3848666a7c369294`；工作树干净后正常 merge 固定 integration `235258ad75f7d271a279ea89fd88ddf80e797f31`，merge 提交 `0faa98522c7559e48817edd6b1c0c9f06d5ce470`，无 reset、force push 或覆盖未提交文件。
- 实际 Authority merge：`a4a57fcc0effd5dd5ea9689b355a963b007c20f3`，由上述 integration 引入；Authority tree `e15385d5f983ab47d226b160a9c218f34d30752e`。已包含 PR13 earliest-output-deadline 修复。
- Agent4 唯一 wire pin：`e3302f6b2bb19e0184cde3a6cbbcaf3ea4371565`；共享 wire、生成器均未修改或复制。
- 冻结 SHA `c7fd46209d3cbc6f58541dba8b4e1c85609c823e`；22 个规范文件原字节、逐文件哈希及 canonical manifest digest 独立确认：`3c0c317ed00f6fa4d2cf15ef3f61fc002d4bb22bf02d53ee9f1b407458bb28b1`。
- 最终完整 HEAD 在 PR12/交付评论中记录，避免文档自引用 SHA 循环。实际测试源文件哈希在 [manifest](agent-3-postgres-evidence/tested-source-manifest.json)，pin/原字节证据见 [verification](agent-3-postgres-evidence/baseline-verification.json)。

## 本轮代码

`contentplan/answerstream/authority.go` 的 `AuthorityFacts` 使用真实 `Store.ProductProjection` 派生 Rule、事实版本、Assertion 与 valueHash。Projection 不暴露价格/库存字面值，因此在可信 Backend 内只读现有 Product Tool 的 `products` 源表，再校验价格/库存哈希与 Projection 完全相同；读写竞态时拒绝，Authority 在 Prepare/Permit/Consume 事务内仍独立复核商品/计划/快照/完整事实。Runtime 不获取 DB 凭据。价格、库存、尺码、可用性和精确材质模板有真实 SQL 依据；Projection 无法证明的重量、型号、促销、比较关系不创建 Rule。非 CNY 不生成“元”断言。

`AuthorityFacts.Verify` 可作 `Store.Assertions` 的真实预检：验证正式 AnswerArtifact 哈希，识别实际正文的完整语义单元，并将正文对应的全部 dependency/assertionKinds 与新鲜 ProductProjection 对照。删除 PRICE 依赖后重新计算合法 Hash 仍拒绝，LLM 自报依赖不能取得权威。`Observe` 只刷新同值同版本事实，商品值/updatedAt/快照/切商品变化均拒绝旧回答。

`turnmanager/answerstream/authority.go` 的 `AuthorityAdapter` 实现原 `Executor`/`Completion`。所有 v2 修改调用真实 `Store.Handle`，先通过正式 `wire.EncodeRequest`/Role/Method/Route 校验，再进入真实事务；没有内存成功回包或另一个 SQL 状态库。CAS revision 是 tenant/owner/run/command 限定的 Backend 只读投影，争用最多重试 3 次。丢 Prepare 回包时保留同一描述符、Hash 和 key 重试；START/Continuation/Consume 歧义只通过正式 `MarkExecutionUnknown` 记录，不补发新语音授权。

首次 `AcquireOutputPermit → JournalStart → ReceiverProofs.Consume`；后续调用 `JournalStartAnswerSegment`，沿用同一 COMMENT/Turn/Attempt/Utterance/Generation。原始 ticket 私有且消费前移除，最多 32 次单元授权尝试；相对预算从发出授权 RPC 前的单调时钟锚点计算，不能因网络耗时扩展授权。实际 Consume 仍由 Receiver/Backend 在数据库时间下重查最早期限。

Drain 通过 Observer 已登记的 evidence 与真实 `JournalConfirmAnswerSegment`，单元 Finish 不结束 COMMENT。EOF 触发真实 `JournalSealAnswer`；`Completion.Commit` 先取得全回答 aggregate，再提交 Runtime `LOCAL_MEDIA_DRAINED` 和独立 CONTROL `COMPLETED`。缺 Seal、缺 required drain、UNKNOWN、Stop、旧身份等由真实 Authority 拒绝。COMMENT 完成只释放既有业务 Slot，不推进商品 Segment cursor；原 Turn Manager 据权威状态选择下一段，原 Scheduler、公平预算、TTL、merged identity 均沿用。

## Agent4 精确装配要求

1. 外层保持原 Scheduler/Turn Manager 准入，提供已经 Admit/Accept 的原始 COMMENT 身份及正式 RuntimeCommand。不要为 Unit2 新建 Turn/Attempt/Utterance，也不要同时装配 legacy dispatcher。
2. 在可信 Backend 创建 `AuthorityFacts{Store, Control, Binding}`。先 `Load(ctx)` 取得语言，再 `NewBuilder(binding, clock, facts, WireEncoding{})`；用原单个 DeepSeek 请求产生的 bounded Source 创建 Scanner/Coordinator。不要先用 legacy `sentence_stream()` 的标点/长度 fallback 裁剪 Provider token。
3. 配置 `Store.Assertions` 的可信 **按 command 分派器**，调用相应 `AuthorityFacts.Verify`；fixture 为每个 Store 绑定一个已准入 COMMENT，生产共享 Store 不能被最后一个 Session 覆盖回调。Projection 缺少价格/库存字面值的只读源适配在本包内，若以后换成正式 Tool 调用，必须维持 valueHash/snapshot/sourceVersion 同值核对。
4. `AuthorityAdapter` 是 Backend 域适配，不给 Runtime/Guardian SQL 权限。`Runtime/Control Actor` 来自认证组合根，不能由客户端 body、模型或 query 参数构造。共享 HTTP/IPC 入口仍由 Agent4 实现。
5. 实现 `ReceiverProofs` 四方法。`Consume` 必须完整执行原 Receiver ticket、Backend latch、Guardian fsync ACK、Runtime once-TTS；`Playing/Drain/Aggregate` 必须来自可信 Observer/required Sink 的 execution lineage 和连续范围。不得直接使用 `syntheticReceiver`，不得以计数、enqueue、TTS 返回或 Runtime 自报替代证明。Registrar 的可信安装与进程身份仍由 Agent4/5 供给。
6. 在每次真实输出边界刷新同 execution 的 Permit/FactObservation。已消费正常长句可以用新同值 proof 继续，不能重新 Consume/START；输出镜像期限比 Permit/Grant 更早时必须按最早截止拒绝。域适配器不实现实时媒体续期循环。
7. 原 Stop/商品切换/UNKNOWN/旧 Epoch watcher 同时取消 Provider、调用域 Stop/Unknown 并完成 Backend/Guardian 原停止编排；域 Stop 本身不是物理 fence。恢复由 Agent2 Coordinator 先确认合法持久状态；不得创建新域对象盲重播 UNKNOWN。
8. 每个异步 PCM/帧/Finish 必须保留原 execution/Artifact/hash/Generation/ranges。当前 SQL 联验拒绝旧 proof，并不证明真实异步媒体已经保持 lineage。完成后须另跑真实 IPC/Guardian/TTS/媒体/required Sink 故障验收。

本轮没有发现必须修改 Agent2 Authority 或冻结协议的问题；无需通过私改协议绕行。公共接线所需接口就是现有 `Source`、`AuthorityFacts`、`AuthorityAdapter`、`ReceiverProofs`，没有新增公共 DTO、路由、SQL 或生产开关。

## 验证边界与回滚

准确命令、PASS/FAIL/SKIP、A–J 场景、资源和清理记录见 [PostgreSQL 测试报告](AGENT-3-POSTGRES-TEST-REPORT.md)。旧 23 项 Streaming、原 Planner/Turn Manager race、公平/TTL/Stop/FORCE/UNKNOWN 场景继续保留。

真实跨进程 Registrar/Guardian IPC、Guardian fsync/Runtime once-TTS、物理安装、真实 Observer/required Sink、异步 PCM/帧 lineage、DeepSeek/XiaoYa/SoulX/GPU、Chrome/WebRTC/RTMP/观众、忙/闲首句 SLA 均 **NOT TESTED**。本轮本地 PostgreSQL 的 fsync=on 与 Guardian fsync 是不同验收层。

首句仍无需 Provider EOF，但真实时间预算必须包含可信安装/Registrar（如在关键路径）、Authority Prepare/Permit/START/Consume 的 Backend 往返、ProductProjection/事实校验/事务提交、Guardian IPC/fsync/ACK、Runtime once-TTS 和首音画。通过逻辑回归不等于达到首句 SLA，现阶段不报告 P50/P95。回滚为保持不装配这些隔离包，不删除迁移、不改媒体链路，不启用 Durable LIVE。
