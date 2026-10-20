# durable-live-1 状态与证据

> CCR-ADL-001 review at PR8 `01a752baf79c25d4d268167d016c8c62e754cfdf`: active durable-live-1 is preserved. [durable-live-2 incremental answer candidate](ccr/CCR-ADL-001.md) and [migration/owner handoff](ccr/CCR-ADL-001-HANDOFF.md) are PENDING OWNER ACK; this historical v1 freeze does not approve that upgrade.

机器转换表见 `contracts/v0.5/durable-live/state-machines.json`。每条转换都要同时满足下表 guard、授权、expectedRevision CAS 与当前 epoch；Stop是例外：锁行后读取最新revision写停止，调用者旧revision仅用于审计，不能因此丢弃Stop。任何未列出的边拒绝409 STATE_CONFLICT。同状态重复事件只有相同证据 hash 才 no-op，不产生新副作用。状态不能用数值大小或 occurredAt 排序。

## BroadcastRun

| 从 → 到 | 必须条件 |
| --- | --- |
| CREATED → PREPARING | desiredState=LIVE；授权；首次获得 lease 并分配 epoch；计划与 binding 准备意图已提交 |
| PREPARING → LIVE | current Session 为 LIVE、Runtime fence ACTIVE、合法产品/绑定、输出独占已证明 |
| PREPARING / LIVE → RECOVERING | 可恢复故障或 owner 丢失；暂停所有新媒体，持久恢复原因 |
| LIVE / PREPARING / RECOVERING → PAUSED | 显式暂停或保守策略；desiredState=PAUSED；停止准入并完成本地输出屏障；不声称清除平台缓冲 |
| PAUSED → RECOVERING | 显式 Resume，desiredState=LIVE；新 lease/epoch；重新核验权限/商品/绑定 |
| RECOVERING → LIVE | 对账完毕、无阻塞 UNKNOWN、新/复用 Session fence 生效、旧输出已隔离 |
| 任一非终态（含 CREATED）→ STOPPING | 已授权 Stop 事务提交 desiredState=STOPPED 与 stop tombstone，优先于所有 claim/recovery |
| STOPPING → STOPPED | 当前与历史未释放 physical Session 全部输出隔离/停止已证明；binding cleanup 已完成；无可运行意图 |
| CREATED / PREPARING / LIVE / RECOVERING / PAUSED / STOPPING → FAILED | 不可恢复错误或 Stop清理失败超预算；保留 tombstone/隔离重试，不恢复讲话 |

STOPPED/FAILED 为终态，只能新建 run；FAILED 也不允许 Resume。Stop 在终态重复返回现有结果并可继续清理。Stop 不以 epoch 失效为理由被 recovery 抢走：owner授权后直接锁 run 写 tombstone，再由当前/新控制 owner 仅执行停止。202仅证明停止意图持久，不表示已静音；STOPPING 尚未完成时不得伪称 STOPPED。

## Turn

| 转换 | 条件 |
| --- | --- |
| READY → WAITING | 合法输入被接纳，但边界、速率或公平预算尚不允许 |
| WAITING → READY | 到达边界、TTL有效、模式/商品一致；所有前序必要段已本地完成 |
| READY → DISPATCHING | ClaimNextTurn 单事务获得唯一 run slot，创建 attempt/Utterance/Outbox |
| DISPATCHING → PLAYING | 对应 attempt 的 PLAYING checkpoint 可信并已持久化；HTTP202不是此证据 |
| PLAYING → COMPLETED | checkpoint COMPLETED 原子推进；仅本地业务完成 |
| READY / WAITING → INTERRUPTED | STOP、TTL到期、商品切换或显式取消；证明无 dispatch，记录 reason |
| DISPATCHING / PLAYING → INTERRUPTED | Runtime cancel/fence barrier 证明不再产出；已送出的尾部不可撤回 |
| DISPATCHING / PLAYING → UNKNOWN | 请求/执行/输出存在无法消除的歧义 |
| UNKNOWN → PLAYING / COMPLETED / INTERRUPTED | 仅 reconciliation 携带同 attempt 可验证证据；不能超时自动视为未执行 |

Turn COMPLETED/INTERRUPTED 不复活。已证明未执行的技术失败把旧 Turn 标 INTERRUPTED(reason=NOT_EXECUTED)，是否建新 Turn 按 TTL/策略授权；不是原 Turn 倒退重投。

## Dispatch

| 转换 | 条件 |
| --- | --- |
| PENDING → CLAIMED | nextAttemptAt到期、SKIP LOCKED及claimVersion CAS。媒体要求DB-time有效ACTIVE run lease且未Stop；INSTALL_FENCE要求有效PENDING_INSTALL任期；STOP_RUN只要求已授权持久Stop及独立cleanup claim，不受媒体未Stop条件阻塞 |
| CLAIMED → ACCEPTED | 同 commandId/requestHash 的 durable RuntimeInbox accepted receipt |
| CLAIMED → PENDING | 仅发送前证明未发出或原子 REJECTED_NO_EFFECT 证据；重用原身份，退避 |
| CLAIMED / ACCEPTED → RECONCILING | 超时、lease过期、连接断开；先查 journal，不直接重发 |
| RECONCILING → ACCEPTED / COMPLETED | 找到同身份 accepted 或完整完成证据 |
| RECONCILING → PENDING | 媒体须原子封存旧executor并证明NOT_EXECUTED且同epoch/TTL有效；幂等STOP清理可在tombstone仍有效时重送，INSTALL仅pending任期仍有效时重送，均不得产生媒体 |
| RECONCILING → UNKNOWN | journal/输出事实不足或冲突；禁止自动旧评论重放 |
| ACCEPTED → COMPLETED | 绑定 attempt 的业务 checkpoint 完成；控制命令则需其 fence/cleanup proof |
| PENDING / CLAIMED / ACCEPTED / RECONCILING → FAILED | 已证明拒绝/取消/不可执行；接受后必须先有执行取消证据，不能将timeout当失败 |
| UNKNOWN → RECONCILING | 新证据或操作员发起只读对账；不是重新执行授权 |

Dispatch ACCEPTED 表命令持久接收；Turn PLAYING 表媒体开始；Segment COMPLETED 表业务本地完成，三者必须分列存储。

## PlaybackCheckpoint

| 状态 | 最低真实证据 | 不证明 |
| --- | --- | --- |
| PLANNED | immutable plan/segment 与文本 hash 提交，或 COMMENT attempt 输入已提交 | 已发命令 |
| DISPATCHED | sender 在网络前提交 SEND_STARTED marker；表示可能发送 | 对方一定收到 |
| RUNTIME_ACCEPTED | journal 接受事务提交，返回 receiptId 与 revision，Runtime内存排队不够 | 已生成/播放 |
| PLAYING | 当前 fence 下首次关联音视频被具名本地 sink 接纳，含 attempt/generation、首 sample/frame；仅观察 PCM 不够 | 扬声器或官方平台实际播放 |
| LOCAL_MEDIA_DRAINED | 完整内容最终范围已确定，全部 requiredSinks 的连续 audio/video watermark 达到尾部；无未决队列/歧义尾部，记录 ranges、sink、generation | 抖音/淘宝观众已听见 |
| COMPLETED | 上述 drain proof 验证后，checkpoint+segment/turn投影+连续完成游标在同一 SQL 事务提交，evidenceType=BUSINESS_COMMIT | 远端 exactly-once audible |
| INTERRUPTED | cancel/fence barrier 已安装；记录已提交/消费范围与作废尾部 | 已传输内容被撤回 |
| UNKNOWN | 记录 lastKnownState/reason 与缺失或矛盾证据 | FAILED或可安全重播 |

正常链为 PLANNED→DISPATCHED→RUNTIME_ACCEPTED→PLAYING→LOCAL_MEDIA_DRAINED→COMPLETED；未终止态可在有证据时 INTERRUPTED，网络发送后的态可 UNKNOWN。UNKNOWN 只能由对账恢复为有证据的非 PLANNED/DISPATCHED 状态。空音频/缺少 required sink 不得制造 COMPLETED。requiredSinks 在任期启动前固定且非空；RTMP生产可将preview列optional，纯WebRTC必须指定实际peer。不得把现有 OR credit 当 all-required drain。sink变化要暂停、封存未完成 attempt 并开启新任期，不能减弱进行中 attempt 的要求。

乱序：inbox 去重键为 eventId，另有 UNIQUE(attemptId,producerIncarnation,producerSeq)；同键异hash报 EVIDENCE_CONFLICT。序号缺口先保存为待投影并拉取 journal；不能跳过所需证据。完整drain事件若带齐全部前序证据引用，可在同事务校验并补齐中间投影。迟到的旧阶段只归档，不回退。旧epoch只能补历史证据，不修改当前 slot/游标/状态；需对账事务显式验证历史 attempt 完成，不能释放新epoch slot。Stop后到达完成证据可归档并完成历史统计，不撤销Stop/不触发下一段。冲突的terminal proof必须隔离对账。
