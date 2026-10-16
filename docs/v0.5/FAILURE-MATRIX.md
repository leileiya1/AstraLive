# 故障矩阵（Agent 2）

`PASS` 只表示该行列出的隔离测试层。进程测试运行真实 Go HTTP 服务、真实 Python Journal/Inbox、PostgreSQL、Redis；口播 effect 为具名本地文件 sink，**不是真实 TTS/GPU/RTMP 播放证明**。

| # | 故障 | 实现与自动化证据 |
|---|---|---|
| 1 | Outbox 提交后 Go 崩溃 | `TestProcessCommitThenGoSIGKILL`：仅杀本测试 Go 子进程；原 PENDING、Attempt、QUEUED 身份仍在 |
| 2 | 提交失败回滚 | `TestPostgresRollbackNoPartialAttempt`：Receipt 冲突发生在事务中，Utterance/Attempt 不留半成品 |
| 3 | Runtime 接收后 202 超时 | `TestProcessRealRuntimeLost202`：Python 实际 HTTP 接收，响应延迟超过 Go 超时；SQL 对账和重复请求均只有一次文件 sink effect |
| 4 | PLAYING 时 Go SIGKILL | `TestProcessGoSIGKILLWhilePythonPlayingAndReattach`：Python 存活；Permit 到期关闭输出；不重放 |
| 5 | Go 重启附着 | 上述进程测试及 `TestPostgresLost202ReattachNoReplay`：复用持久身份和存活 Inbox；没有重建第二个 Session/执行器。不能据此声称直播连续 |
| 6 | QUEUED orphan | `TestPostgresRuntimeCrashUnknownAndOrphanBusyProjection` / `TestPostgresStopWinsRecoveryAndUnsentOrphan`：显式恢复知识与兼容 Utterance 终态，避免遗留 busy；UNKNOWN 物理 slot 在隔离前仍封住 |
| 7 | Redis 重复、乱序、claim | `TestRedisStreamsDuplicateReclaimAndSQLProjection`：真实 XREADGROUP/XAUTOCLAIM/XACK；`TestPostgresCheckpointOrderingDuplicateAndBusinessCommit`：序号缺口先持久待投影、重复不推进两次 |
| 8 | Lease 失效、双执行者 | `TestPostgresLeaseCompetitionAndOldEpoch`：两个独立 instance 的 SQL 竞争、CAS、失效后不可 renew；`TestPostgresSkipLockedAndNoCrossRoomWait`：持锁房间不阻塞扫描 |
| 9 | 旧 epoch 命令/媒体 | `TestPostgresLeaseCompetitionAndOldEpoch` 及 Python `test_output_gate_rejects_old_epoch_and_generation_at_handoff`；真实 Worker wire 未改 |
| 10 | Stop/Recovery 并发 | `TestPostgresStopWinsRecoveryAndUnsentOrphan`；旧 revision 不丢 Stop；LeaseKeeper 不能复活 tombstone |
| 11 | PostgreSQL 暂不可用 | `TestPostgresIsolatedServerOutage`：停止/重启独立实例；`TestPostgresOwnedConnectionDropRecovery`：仅断开已持有的测试连接；工作未膨胀 |
| 12 | Redis 断连恢复 | `TestRedisIsolatedDisconnectAndSQLFallback`：独立 Redis shutdown/restart，SQL Dispatcher/Coordinator 继续工作 |
| 13 | Python 播放时崩溃 | `TestProcessPythonSIGKILLPreservesUnknown`：仅杀测试 Python；SQL UNKNOWN，不把空内存当成未执行 |
| 14 | Provider Binding 过期 | `TestPostgresBindingExpiryAndWorkerUnavailable`：拒绝发送，已证实未发送任务终结；不重用旧凭据建 Session |
| 15 | Worker 不可用 | 相同 Go 测试的 readiness gate 以及 Python `test_missing_backend_and_unready_worker_fail_before_effects`；使用注入的测试 readiness，真实 GPU Worker 故障为 NOT TESTED |

补充覆盖：不可变信封/复合 FK、商品计划顺序、评论输入幂等、回答准备日志、sealed NOT_EXECUTED、Runtime 禁止 BUSINESS_COMMIT、全 required drain、续租不改写旧信封、Room 跨 Run 输出独占、legacy/durable 双调度拒绝、角色鉴权、通知补偿。

## 明确不能自动证明的状态

- SEND_STARTED 后缺少 ACCEPT / START ACK；可能执行，也可能未执行。
- START 提交后 Python 崩溃，只有 PLAYING 或部分范围，没有完整 drain。
- Journal 与终态 sink proof 冲突、producer 序号缺口无法补齐。
- 原 Publisher 是否物理关闭不可证明、Worker 未 READY、授权或 Binding 失效。
- 整机重启后外部 RTMP Publisher/平台缓冲的实际状态。

以上场景不会靠无限媒体重发解决。UNKNOWN 默认需人工只读对账、隔离后明确 gap/新话轮决定；旧评论不得自动重播。整机重启、真实 GPU 长/短失联、Chrome、RTMP、官方平台观众端均由 Agent 4 独立验证，当前 NOT TESTED。
