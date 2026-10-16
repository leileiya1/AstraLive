# Outbox / Inbox / Journal

版本固定 `0.5` / `durable-live-1`。业务状态机和操作以 Agent 1 的机器 Schema 为准，不增加“重试中”等自定义状态。

## 持久事实

| 对象 | 含义 |
|---|---|
| `dl05_requests` | 操作幂等响应；丢失数据库提交响应后返回同一结果，不创建第二个 Attempt |
| `dl05_outbox` | 不可变命令、requestHash、固定 Command/Utterance/IdempotencyKey、认领版本与发送 marker |
| `dl05_runtime_inbox` | 接受、一次性 START、封存/终态的持久 Journal；Python 不能直接写数据库 |
| `dl05_checkpoints` | append-only 原始证据；投影状态独立，支持待投影、历史、隔离 |
| `dl05_notifications` | 与 checkpoint 同事务创建的通知意图，补偿数据库提交后未发布的通知 |

规范 JSON 禁止重复 key、float、非有限值和越界整数；精确保留 Unicode、文本空白和 metadata。传输重试不重新生成 commandId、traceId、createdAt。数据库禁止修改命令信封。

## 崩溃边界

| 窗口 | 处理 |
|---|---|
| Claim 事务未提交 | 全部回滚，没有独立 QUEUED Utterance |
| 已提交、未发送 | SQL 扫描能找回原 Intent；不依赖进程内队列 |
| 已认领但未完成 | 超时进入 RECONCILING；旧 claimVersion 不能再提交发送 marker |
| SEND_STARTED 后失联 | 不重发；查同 CommandId/hash 的 SQL Journal |
| Runtime ACCEPT 后 202 丢失 | 查询收据；同存活 Inbox 返回状态，不创建新任务 |
| START 提交但 ACK 丢失 | 不重复授权；即使可能尚未发声，也保持保守 UNKNOWN |
| Python 重启、内存为空 | Journal 仍在；STARTED 不重新执行；丢失 ACCEPTED 本地队列也不由新进程扫出重播 |
| 全部 drain 已证实 | CONTROL 提交 BUSINESS_COMMIT；HTTP 202 或 TTS 完成不具备此效力 |

媒体投递在 SEND_STARTED 后没有自动重发循环。STOP/INSTALL 是不产生媒体的幂等控制命令，最多 5 次退避发送，随后 UNKNOWN；新的独立清理证明可以只读对账为完成。

## Runtime 与通知

`runtime/app/durable_live_journal.py` 提供实际 HTTP JournalClient、ExecutionInbox、一次性 START 消费、版本化 routers、RuntimeControl 和 OutputGate。执行器/Worker readiness/Guardian 由受信任注册器注入；缺失必要依赖时拒绝执行。

SCRIPT_TEXT 不经旧 LLM 回答链重写；执行器必须使用已冻结文本。COMMENT_QUESTION 在 START 前必须保存实际回答文本及 hash，不能把问题 hash 当作回答。仓库内提供 `RecordAnswerText` 和 `dl05_answer_artifacts`；冻结 wire 缺少跨进程 answer-prepared 操作，需 Agent 1/4 解决接线后才能启用该模式，当前缺失时拒绝 START。

Redis 新通知只引用已经持久化的 checkpoint，不能在 Redis 中伪造完成事实。保留 XREADGROUP / XAUTOCLAIM / XACK；五次非法通知进入 DLQ 并记 SQL 审计。旧 v1 Runtime 事件对 durable Utterance 只作观察记录；不能绕过 Journal 推进状态。

通知为 **at-least-once**：发布成功后、写 published_at 前崩溃可能重复通知，消费者按 checkpointId 去重。此边界不代表口播重试，更不承诺外部 exactly-once 播放。
