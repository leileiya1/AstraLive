# 09 — 阶段 2（第一步）：Runtime receiver-1 客户端，一次消费、一次 TTS

依据：冻结契约 `docs/v0.5/ccr/RECEIVER-BOOTSTRAP-CONTRACT.md`（REGISTERED_RUNTIME 角色）与参考模型 `contracts/v0.5/durable-live-2/examples/python/receiver.py` 的 `RuntimeActor`。没有新增或修改任何 wire 字段、路由、Schema、Grant/PTS/Credit 语义。

## 新增文件

| 文件 | 作用 |
| --- | --- |
| `runtime/app/receiver1/runtime_client.py` | `GuardianChannel`（单个持久、内核身份钉住的 AF_UNIX 通道）+ `ReceiverRuntime`（Runtime 侧状态机） |
| `output_guardian/tests/v2/test_runtime_receiver.py` | 14 个测试，客户端对接**真实** Guardian v2 `Receiver` + `PrivateIPC` |

两者均不在 313 项保护清单内；没有修改任何受保护文件。导入模块不会打开 socket，也不授予任何权限。

## 实现的规则（逐条对应契约）

| 契约要求 | 实现 |
| --- | --- |
| consumeTicket 只来自第一次真 START/续段响应，绝不记录日志，成功/拒绝/不确定后擦除 | `remember_start` 以 SDK `SecretString` 私存；`consume` 在任何结果后 `_forget` |
| 只接受“本通道、仍挂起 nonce”的第一个真 ACK；START 期限 ∩ consume-ACK 期限；拿到新 proof 后再次检查 | `consume` 内依次校验 nonce/grant/artifact，双时钟 `Deadline`，`ReceiverRenew` 之后重检两期限 |
| 每个 execution 只调用一次 TTS，针对已提交的精确 Artifact | `speak_once`：调用**之前**就上锁，异常也不会重开 |
| 媒体携带提交时捕获的 lineage；延迟的旧单元帧拒绝而非改标；外层序号跨单元连续 | `submit` 返回不可变 `Lineage`；`media` 要求 lineage 完全等于当前 execution；序号只在 Guardian 接受后递增 |
| Renew 不授予消费/TTS | `renew` 只更新 proof 期限 |
| Finish 返回已注册 Observer 的 drain 证据（ReceiverProof），由调用方向 Backend 确认 | `finish` 返回 `evidence`，execution 置 FINISHED |
| 查询只给元数据，不能重新武装 | `query` 只返回 summary |
| 任意传输疑问 → UNKNOWN；不重试、不重连同一 execution；取消在标记 UNKNOWN 后继续向上传播 | `GuardianChannel` 出错即永久 dead；`execution.state` 只能 ACTIVE→FINISHED/UNKNOWN |
| Runtime 通过内核身份确认对端是被钉住的 Guardian，ticket 不会发给其他进程 | 连接时校验 socket 对端 PID==钉住 PID 且身份一致；每次请求前后校验钉住进程身份 |

## 测试与证据

| 检查 | 结果 | 证据 |
| --- | --- | --- |
| 新测试（Mac） | 14 PASS | `evidence/stage2/guardian.txt` |
| 变异测试：保留 ticket / TTS 后上锁 / 改标 lineage / 去掉 START 期限 / 去掉 socket 对端钉住 / 拒绝时序号递增 / 吞掉取消 | **7/7 均被检出**；最初 M3、M5 存活，补了两个精确测试后检出 | `evidence/stage2-mutations.txt` |
| 完整回归（Mac） | Guardian 233 PASS/1 SKIP；契约 137；validator v1/v2；生成；diff-check；Runtime 169；gpu_worker 23；前端 45；Go vet；Go race 272/0/8 | `evidence/stage2/full-regression-summary.txt` |
| Linux（school-linux 容器，`459e318`） | 新测试+IPC 3×31 PASS（`--network none`）；全量 232 PASS/0 FAIL/2 SKIP（bridge） | `evidence/school-linux/stage2-459e318.txt`、`guardian-suite-459e318-bridge.txt` |

覆盖的场景：正常 consume→TTS→音视频→renew→finish；单元 2 续段（同一通道、同一 Attempt、新的一次性 Grant、TTS 共 2 次、序号连续、迟到单元 1 帧被拒）；第二个通道竞争同一 Grant；Backend ACK 丢失后只能查询、不能再武装；通道断开后 Guardian 标记 UNKNOWN 并关闭输出；Stop 后拒绝且不重试；START 期限已过时 ticket 根本不发出；错误/冒充的 Guardian 身份与“存活但不是对端”的进程都拿不到 ticket；consume 中途取消。

## 明确未证明（不得视为通过）

1. **Backend 是契约 oracle（mock）**，不是 Go `PostgresAuthority`；Observer 证据是由真实 tail 推导的合成信封。真实 SQL 的唯一 latch 已由 Go receiver1 套件单独证明，但本客户端与它的**端到端**联调尚未做。
2. **生产接线尚未完成**：Python Runtime 目前的 Journal 客户端仍是 v1；v2 的 `JournalStart`/`JournalStartAnswerSegment`/`AcquireOutputPermit`/`JournalConfirmAnswerSegment` 尚未在 Python 侧接入；真实 TTS 提供方未接入。
3. **架构决策待定（Agent4 所有权）**：Agent3 的流式协调器在 Go 中用 RUNTIME_JOURNAL 身份调用 Journal，但生产中只有 Python Runtime 进程持有该凭据及 Guardian 消费权限。需要决定：协调器移入 Runtime 侧，或 Go 协调器通过 Runtime 执行 consume（`ReceiverProofs` 的生产实现）。本步骤没有替该决策做选择。
4. Linux 隔离、真实媒体、GPU、延迟 SLA 均未涉及；`OUTPUT_FENCE_UNPROVEN` 不变，Durable LIVE 仍无法开启。

## 阶段 2 后续步骤（建议顺序）

- 2b：在 Go receiver1 真实 PG 测试框架中，用本客户端替换测试用 Python peer 的 Runtime 角色，做真实 Backend Authority + 真实 Guardian + 本客户端的端到端测试。
- 2c：Python Runtime v2 Journal 客户端（四个 RUNTIME_JOURNAL 操作），以及协调器归属决策落地。
- 2d：真实 TTS 适配器经 `speak_once` 接入（CPU/模拟提供方），PCM 提交时绑定 lineage。
