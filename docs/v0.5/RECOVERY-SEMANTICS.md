# durable-live-1 恢复语义

默认 recoveryPolicy=MANUAL_ON_UNKNOWN；可选 SAFE_SCRIPT_NEXT_BOUNDARY 仅自动恢复已证明未开始或已本地完成的脚本下一段，不能覆盖UNKNOWN媒体。任何策略均不自动重播歧义评论。逻辑run恢复可绑定新的physical Session；终态Session不复活，新Session重新capture合法Provider Binding，保持现有product context规则。

| 故障情形 | 持久事实与处理 |
| --- | --- |
| 1. DB提交后Backend立即崩溃 | attempt+utterance+outbox同事务都存在。无SEND_STARTED且从未claim可按原ID发送；已claim或存在marker先对账；不留独立QUEUED orphan |
| 2. Runtime接收但HTTP202丢失 | CLAIMED→RECONCILING；以commandId/hash查durable inbox。已STARTED不再执行；仅ACCEPTED可由同存活executor重新排队一次并CAS start；404/重启内存为空不是NOT_EXECUTED |
| 3. Runtime播一半崩溃 | 已有PLAYING，缺完整drain → UNKNOWN；guardian隔离，记录范围，绝不写COMPLETED。旧COMMENT不自动重播；SCRIPT暂停等待人工选择跳过或新话轮重述，保留原attempt |
| 4. Go崩溃但Runtime仍讲话 | 当前段仅在permit有效时继续；journal不可用不开始下一段；permit≤1秒失效后关闭输出。新Backend先接管lease、查询旧attempt并隔离旧output，再激活新epoch；不立即重播 |
| 5. 两个Backend同时恢复 | DB run行锁、DB-time lease、epoch/version CAS只有一个owner成功；另一个409 LEASE_LOST。不是靠Go mutex |
| 6. 旧Runtime租约后重连 | 普通execute/checkpoint写当前投影/permit拒绝STALE_RUN_EPOCH；旧证据只归档。必须新注册producer+安装当前fence且经授权，不能凭更大generation冒充新owner |
| 7. STOP与Recovery并发 | Stop持久desiredState与tombstone永远阻止后续激活，锁顺序统一。Recovery已分配epoch也需在激活/start时再查Stop；只可继续清理，不能继续讲话 |
| 8. 切商品旧Segment待投递 | 先暂停并封存准入，旧READY段INVALIDATED、旧Turn INTERRUPTED(PLAN_CHANGED)、待发Outbox FAILED(no effect proof)。已可能发送者先对账/隔离；新商品新plan及新Session Binding，run可保持同ID，新epoch后恢复 |
| 9. 完成确认重复投递 | eventId/producerSeq/hash唯一；checkpoint与连续cursor一次事务更新；重复只返回原revision，不能再次Yield/追加下一段 |
| 10. 无法判断评论是否被观众听见 | audienceVisibility=UNVERIFIED 始终与本地checkpoint分离；本地drain已证实可业务COMPLETED，但不标AUDIENCE_HEARD。连本地范围也歧义则UNKNOWN；不以外部未知为理由重播旧评论 |

UNKNOWN不是失败，也不是自动重试票据。MarkExecutionUnknown记录reason、lastKnownState、attempt、evidenceRef，挂起相关Turn/Segment并封住slot；只有隔离证明后才能释放物理准入，业务游标仍不越过未知段。人工解决必须带operator decisionId、expectedRevision与reason。允许的决定：WAIT_FOR_EVIDENCE、SKIP_WITH_GAP（记录gap且不伪造完成）、CREATE_NEW_TURN（明确接受重复风险，旧attempt先隔离；旧评论必须显式单独授权）。默认不提供自动跳过未知评论/段的后台逻辑。连续完成cursor和operator gap ledger分别存，不把gap计为COMPLETED；恢复游标可跨经授权gap，但必须引用decisionId。

ResumeBroadcastRun只写恢复意图，不同步等待GPU。RestoreContentPlan是可重复读一致性快照，含run revision/epoch、currentPlan、段状态、完成prefix、gap decisions、未决attempt和slot；恢复策略由Agent3计算，Agent2再次事务校验。恢复无权限/绑定过期/输出隔离未证实则PAUSED或FAILED，不偷偷使用旧凭据。RuntimeSession更换不重置run内comment source去重。

对于v0.4 legacy遗留RESERVED/QUEUED：默认不自动迁移/重放。进入durable模式前停止或隔离legacy Session，留下历史receipt；无法对账的标记为legacy UNKNOWN审计并要求操作员新建run。000005的RESERVED不能被当作未执行证明。

业务安全目标：无未经授权的旧epoch副作用、任务身份不丢失、歧义可见、评论不盲目重复。RTMP不断流是额外媒体/平台目标；可能有停顿、重连、平台缓冲延续。本设计不承诺外部exactly-once播放。当前设计测试未运行真实GPU、RTMP、官方抖音/淘宝、故障注入或持续时长验收，均NOT TESTED。
