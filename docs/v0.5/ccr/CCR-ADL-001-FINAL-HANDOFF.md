# CCR-ADL-001 — 正式实施交接

本文件是非规范性的审批后实施分工，不增加或修改技术契约。获批对象固定为 `c7fd46209d3cbc6f58541dba8b4e1c85609c823e`，normative digest 为 `3c0c317ed00f6fa4d2cf15ef3f61fc002d4bb22bf02d53ee9f1b407458bb28b1`，版本 durable-live-2 / receiver-1。22个规范文件和原 manifest 必须保持原字节；技术变化必须另走 CCR/受影响 owner 重审。最终审批：[PR9正式决定](https://github.com/leileiya1/AstraLive/pull/9#issuecomment-6231271734)、[Issue7同步记录](https://github.com/leileiya1/AstraLive/issues/7#issuecomment-6231275931)和[当前审批台账](CCR-ADL-001-FINAL-APPROVAL.json)。

批准解除架构契约门槛，允许后续由 Agent4 协调在 integration/v05-durable-live 按该固定规范实施。**本轮仅完成审批与交接，没有启动、派发或执行以下开发任务。** PR9继续Draft，等待Agent4独立集成审核与合并；不合并main、不启用Durable LIVE、不启动GPU。旧durable-live-1、Frozen v1.1和默认关闭保护不变。

## 唯一契约来源和审批记录

[冻结manifest](../../../contracts/v0.5/durable-live-2/manifest.json)列出的22个文件是唯一技术规范：schema.json、protocol.json、receiver-protocol.json、state-machines.json、Go/Python样例、Golden Vectors、完整/Stop/续期trace及冻结设计文档。使用同一路径在获批提交读取，不从Issue7原whole-answer提案或旧PR评论推导另一套协议。25个核心操作和13个私有操作均已有版本化路径、角色、闭合请求/响应和错误码。

原 [CCR-ADL-001-ACKS.json](CCR-ADL-001-ACKS.json) 是冻结候选审批前历史快照，已明确标记被 FINAL-APPROVAL 台账取代；其 BLOCKED/PENDING 字段仅表示当时状态。冻结文档/validator里的评审阶段文字也保留不改。当前批准、完整ACK、范围和权限以 FINAL-APPROVAL 台账及Agent1正式GitHub评论为准。这是治理状态更新，不是变更技术规范，也不把任何后续代码自动纳入旧ACK。

## 代码所有权

| Owner | 独占实施范围 | 接口与交付 |
| --- | --- | --- |
| Agent2 | 单一v2 additive migration；backend/internal/durablelive及经Agent4登记的隔离v2持久层/Authority模块；Backend Journal、Recovery、Lease/Fencing与UNKNOWN/Stop持久语义 | PostgreSQL注册/challenge/source mirror/Artifact child/ticket verifier/唯一consumption latch；原子Artifact正文+Hash+商品版本+事实依赖+receipt/CAS；受限Authority Query/Commit/metadata和CONTROL登记/撤销处理器 |
| Agent3 | backend/internal/contentplan/**、backend/internal/turnmanager/**；沿用既有Comment Scheduler，必要scheduler修改先登记文件归属；隔离的讲解/评论编排模块 | 保守完整语义单元、bounded streaming AnswerArtifact生产、实际回答断言/事实依赖提取、Prepare/Continuation/Drain/Seal协调及同一COMMENT Turn续讲；不再创建第二套Session/Utterance/调度器/数据库 |
| Agent4 | 总体集成与基线；可信CONTROL Registrar/安装记录/Session/Generation/Binding；Runtime v2 DTO/客户端/协调与共享入口接线；跨模块测试与发布门槛 | 冻结Schema生成隔离DTO；独立可信安装读取与closed stage→登记流程；认证进程/incarnation/channel；Runtime first-ticket/once-TTS/取消/期限与Journal客户端；跨进程端到端证据 |
| Agent5（Agent4协调） | output_guardian/**、infra/guardian/** 的隔离v2 receiver/Authority client/输出适配；不修改Worker二进制协议或推理模型 | Guardian私有IPC、真实短gate/barrier/deny-replay fsync、连续Publisher/Decoder/Sink的可撤销输出边界、逐单元真实drain/媒体归属及Stop/重启隔离；不另建业务SQL权威 |

共享热点只由Agent4集成修改：backend/internal/app/service.go、backend/internal/app/interaction.go、backend/internal/app/session_integration.go、backend/internal/httpapi/server.go、runtime/app/session.py、runtime/app/session_binding.py、runtime/app/bound_media.py。涉及runtime/app/durable_live_journal.py或现有Runtime IPC入口的跨owner接线由Agent4统一合入，Agent2提供Journal语义/补丁和复核。Agent5如需Runtime客户端修改，交给Agent4，不直接改其工作树。

各Owner使用自己的既有工作区/分支提交独立PR；不checkout、reset、clean、stash或编辑其他Agent工作树，不覆盖未提交内容、不force push。共享文件需求由提供方提交明确patch/集成说明，Agent4串行合入。Agent2独占迁移编号和SQL授权；Agent3/5不得另建冲突表或迁移。必要的新隔离包路径由Agent4登记，不能借此改写已冻结接口。

## 任务依赖和交付顺序

1. **Agent4固定集成基线。** 独立审查PR9及审批记录提交，确认与最新integration兼容后自行处理PR9→integration的合并；PR保持Draft直至其独立决定。公布基线SHA、契约pin/digest、生成DTO归属、共享文件锁和下一空迁移编号。本次审批不执行这一步，也不自动变更PR状态。
2. **独立模块可并行实施。** Agent2实现持久层/Authority；Agent3实现保守语义/Turn编排；Agent5实现使用冻结RPC的Guardian适配。三者只依赖固定契约，允许先用显式Mock对端；Mock不算真实互操作验收。Agent4统一生成/登记隔离v2 DTO与认证上下文，避免多套不一致类型。
3. **建议合并顺序：** Agent4的隔离DTO/默认关闭基础 → Agent2 additive migration及Authority → Agent3独立stream/Turn模块 → Agent5独立Guardian模块 → Agent4共享Runtime/Backend/Registrar接线。Agent3/5可以先开发、先单测，具体无共享冲突的PR顺序由Agent4调整；实际receiver互操作必须依赖真实Agent2 Authority和可信Agent4 Registrar。
4. **集成验收后再决定发布。** Agent4汇总真实PostgreSQL+私有IPC+CPU媒体输出测试及故障证据，解决模块边界问题；然后才进入另行授权的真实服务/媒体/GPU验收和单独发布启用决策。所有开发PR合入时保持v2默认关闭，不以CCR批准自动开LIVE。main合并与生产发布均不是本轮交接动作。

## 必须保持的跨模块协议

- CONTROL Registrar由Agent4提供独立可信物理安装/进程来源；Agent5先closed stage，Agent2在run锁域登记。首次Prepare原子添加不可变Artifact子绑定，登记先于首次Permit/START。Runtime不能自报Generation/incarnation成为权威。
- Agent3提供实际回答正文和完整断言/事实依赖；Agent2原子持久化textHash/artifactHash/productSnapshotVersion/facts/receipt/CAS并复核权威版本。输入问题requestHash绝不替代ANSWER Hash；外部LLM/Tool/事实预检不能占SQL事务。
- 首次全局START或continuation响应独占consumeTicket；持久层只存verifier。Agent5用受限Authority Query/Commit获得Backend唯一latch，完成本地deny-replay fsync、最终证明/gate后首次ACK；Agent4 Runtime只在原连接、原pending nonce和期限内接受一次ACK并TTS一次。所有重复/查询均不能再返回true或重建ticket。
- Unit2保留同一COMMENT Turn/Attempt/Utterance/Generation/parent registration，只有自己的Artifact/Grant/execution。前驱STARTED或可信DRAINED可Prepare；实际continuation/消费仍等可信前驱drain。普通Finish只关闭单元并提高barrier，不写Run Stop、不推进脚本cursor、不提前释放业务Slot。完成回答需seal+连续all-required drain+既有CONTROL业务提交。
- Guardian的Run Stop tombstone独立于Backend Stop且不可逆；最终Consume ACK、Renew、Media、Finish与Stop/Restart共享短gate。RPC/fsync/Observer/网络/背压等待都在gate外，返回后及最终提交处复核完整身份、barrier、证明和期限。Backend已消费但ACK截断保留CONSUMED/UNKNOWN，绝不删latch或重授。
- Agent5必须把原execution/Artifact/barrier归属穿过Runtime IPC、子进程、连续Publisher、Decoder和每个required sink，在各自不可逆边界复核；不允许按current slot重贴迟到帧。真实Observer绑定终止单元和连续尾部/ranges，计数、enqueue、PCM生成均不等于drain或观众听见。
- 已消费Grant的首次消费期限不截断合法长句；持续输出受当前同身份Permit和追加式同值FactObservation控制。新证明不重授START/TTS，事实过期/变化、Stop、旧Epoch/Binding、UNKNOWN、进程更替均fail-closed。Python Runtime无业务SQL权限；Guardian无任意SQL/CONTROL写权限；v2不降级到v1 Attempt-only接口。

## 各Owner通过标准

| Owner / 层 | 必须提供的实现证据（当前均未完成生产验收） |
| --- | --- |
| Agent2 / 真实PostgreSQL | 多连接唯一latch/CAS/竞争认领、完整Scope/FK/不可变约束；Prepare alias/Drain身份冲突；Bootstrap/Commit与Stop竞争；事务rollback/提交后崩溃/ACK丢失；事实/商品版本原子性和expiry；UNKNOWN/撤销/去重保留及非破坏回滚；不得锁内等远程调用 |
| Agent3 / CPU+流式 | 中文完整语义及数字/价格/单位/否定条件正反例；首单元不等provider EOF；有界token/assembler/lookahead/backpressure；两种Prepare/Drain顺序和迟到Unit2；真实回答Hash/事实过期拒绝；单Turn/一次START/无额外TTS；seal/all-drain业务完成与正常续讲/Stop区分 |
| Agent5 / 真实进程与输出边界 | IPC角色/凭据/不同channel拒绝；两Runtime竞争一次消费；两层ACK丢失、fsync失败/重启；独立本地Stop先于Backend；最终ACK/Media/Renew/Finish和Stop/Restart真实竞争；子进程/decoder/sink在途旧输出可撤销、Unit2迟到Unit1隔离；连续Publisher不重绑Generation/不重置PTS/Credit；可信required sink尾部drain |
| Agent4 / 集成 | 可信install→stage→register→Prepare→Permit→START→Consume→一次TTS→Media→真实Drain→Unit2→Seal/CONTROL完成；真实Go/Python/PG/IPC身份互操作、商品切换/旧Epoch/Binding/Stop/Recovery故障；独立v1隔离和default-off；共享入口全量Go/Runtime回归与发布/回滚演练 |

冻结契约的基线证据是137项contract/mock回归（原99+38 Stop）、11项Journal、两个validator及Go/Python13向量与5秒续期parity。每个实现PR须保留这些回归，并新增与实际代码层匹配的测试；不能用Mock PASS替代上述真实SQL/进程/输出证据。原始命令和日志在evidence/stop-2026-10-17，三方正式ACK又独立复测137/11。本轮只是检查这些已提交证据，没有虚构再次执行整套测试。

实现时必须实测首句、Permit/事实验证、Authority往返、fsync、最终证明和gate/队列接受的总成本，报告P50/P95及环境/采样方法；不承诺尚未实测的3秒SLA。测试timeout只做死锁检测。观众听见、audible exactly-once、RTMP完全不断流和整体v0.5生产验收不由CCR批准推定。

## 合并失败和回滚

- 共享冲突或新接口需求先停止该PR合并，由Agent4协调文件Owner；不覆盖另一Owner工作区。技术契约变化另开CCR/新digest/受影响Owner复审，不能静默改22个冻结文件。
- 失败或回滚先禁用v2新准入，执行Stop/取消上游并fence旧输出；无法证明隔离/尾部状态则保留UNKNOWN，等待对账/人工处理。不得盲重播COMMENT、删latch、重发ticket或把UNKNOWN当NOT_EXECUTED。
- Agent2的迁移是additive；保留既有000006，使用Agent4协调的下一个空编号。回滚应用不删除active/UNKNOWN/去重/事实/消费证据，不执行破坏性down migration。单个未结束run不混用v1/v2；不能通过自动fallback让v1执行v2行。
- 旧v1路径维持原行为和default-off配置。只有独立确认旧输出隔离、run身份/版本边界和持久数据兼容后，才能按既有策略回到明确的v1新任务；不是重解释原v2 run。真实发布/收费GPU/平台推流测试需要后续单独授权，不属于本轮。

## 当前结果

架构契约已获正式批准，Agent2/3/4对同一冻结SHA/digest的必要ACK齐备，未发现未解决的当前契约阻塞。生产实现、真实PostgreSQL/OS/IPC/fsync/Guardian媒体/Decoder/Sink/GPU/Chrome/WebRTC/RTMP/观众及所有时延SLA仍NOT TESTED。本轮没有启动开发Agent、创建Worktree、实现协议、修改main、合并PR、开启LIVE或启动GPU。
