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

## 架构决策（2026-10-20，仓库所有者选择方案 1）

流式答案协调器的逻辑**移入 Python Runtime**：它本来就持有 RUNTIME_JOURNAL 凭据和 Guardian 消费权限，凭据与权限边界最简单。Agent3 的 Go 协调器及其测试保留为语义参考与回归（不删除），生产路径由 Runtime 侧实现，后续 2c 落地。

## 2b：真实 PostgreSQL Authority + 真实 Guardian + 独立 Runtime 进程（已完成）

`backend/internal/durableintegration/receiver1/interop_test.go` 新增 `TestPostgresReceiver1RuntimeClientOnceTTS`；`testdata/guardian_peer.py` 新增 `runtime_client_flow` 动作，在**独立钉住的 Runtime OS 进程**中运行生产客户端 `runtime_client.py`：

- 真实链路：Go Backend JournalStart（真实 PG，一次性 ticket）→ Runtime 客户端 → Guardian（真实 PR11 receiver + PrivateIPC）→ Backend `QueryReceiverAuthority`/`CommitReceiverConsume`（真实 PG 唯一 latch）。
- 断言：一次真 consume；TTS 恰好 1 次，第二次 `TTS_ALREADY_STARTED`；ticket 已擦除；媒体被 Guardian 门接受、序号从 Session 原点连续；SQL `dl05_receiver_consumptions` 恰好 1 行且 `runtime_principal` 是认证过的 Runtime 进程；同一 ticket 在第二个已注册 Runtime 进程中既不能消费也不会触发 TTS。
- Finish 必须被拒绝（Observer 是关闭夹具）——测试反向断言不得出现 DRAINED。
- START 期限锚点：Go 在 JournalStart **之前**记录时间，把已用毫秒传给子进程向前回拨，保证不会比契约更宽松。
- 结果：`-race` 3/3 PASS；完整回归 Go race 273 PASS/0 FAIL/8 SKIP。端到端变异：保留 ticket（E2E-M1）被检出；“TTS 后上锁”（E2E-M2）在 TTS 成功的端到端流程中不可观测，由 Python 测试 `test_tts_failure_never_reopens_the_latch` 检出（已如实记录）。
- 客户端新增 `sequence_origin`：外层序号从受信 Session 原点继续，不按单元归零。

仍未证明：真实 TTS、真实 Observer/Sink drain、浏览器音视频、延迟 SLA。

## 2c 第一步：Runtime 自己调用 Backend Journal（方案 1 的传输层，已完成）

- **Go `JournalServer`**（`backend/internal/durableintegration/receiver1/journal_server.go`）：只开放 11 个 RUNTIME_JOURNAL 操作，全部交给 `authority.Store.Handle`（它负责角色、范围、状态校验）。私有 AF_UNIX、内核对端身份、每请求 1 秒、最多 16 并发、URL 中的 runId 必须等于请求体 runId，失败只返回冻结错误码；超时或认证存疑时不返回成功（丢失的 START 回复不会被另一个成功替代）。
- **`NewJournalPin(runtimePin)`**：由可信部署代码从已托管的 Runtime pin 派生 RUNTIME_JOURNAL 身份——同一 principal/incarnation/OS 进程（一次性 ticket 的 verifier 绑定该 principal），但**单独的新凭据**；Runtime pin 退役或进程结束即失效；Guardian pin 不能派生。
- **Python `JournalClient`**（`runtime/app/receiver1/journal_client.py`）：官方 SDK 编解码，钉住 Backend 进程身份，每次调用返回请求**之前**的双时钟锚点，供一次性 ticket 计算期限；任何传输疑问为 `JournalUnknown`，不重试。
- **端到端测试 `TestPostgresReceiver1RuntimeOwnedJournalFlow`**：Runtime 进程自己 Prepare → AcquireOutputPermit → JournalStart（真实 PG，拿到 ticket）→ 在真实 Guardian 消费 → TTS 恰好 1 次 → 媒体被接受；重复 START 不会再给 ticket；另一个已注册 Runtime 进程拿着偷来的 Journal 凭据在任何状态变化前被拒（`UNAUTHENTICATED`）。`-race` 3/3 PASS；去掉内核对端校验的变异被检出（`evidence/stage2c-mutations.txt`）。全量回归 Go race 274/0/8。
- 仍未做：凭据向生产 Runtime 进程的投递（属于阶段 4 Host Launcher；测试中经可信父进程管道传入）；Runtime 侧完整协调器（多单元、drain 确认、seal、Stop/UNKNOWN 处理）。

## 2c 第二步：Runtime 侧答案流协调器（方案 1，已完成）

`runtime/app/receiver1/answer_coordinator.py`：

- **`AnswerCoordinator`**：逐条移植 Agent3 Go 协调器状态机——最多 2 个未 drain 单元（1 播放 + 1 预备）；最新单元仍 PREPARED/STARTING 时不再 Prepare；只有 Prepare 在回执不确定时可用**同一** Artifact/幂等键重试；前一单元 DRAINED 后才 START/续段；START、消费、一次 TTS 任何失败都终止为 UNKNOWN 且不重试；drain 需要 Guardian 已注册证据 + Backend 确认；只在来源真正结束时 seal；业务完成仍归 CONTROL；Stop 不可逆、不从内存恢复。
- **`JournalExecutor`**：用 Runtime 自己的凭据实现执行器——`JournalClient` 做 Prepare / AcquireOutputPermit + START 或续段 / ConfirmAnswerSegment / Seal；`ReceiverRuntime` 做一次消费、一次 TTS、按 lineage 推送媒体并定期续 proof；Finish 拿到 Guardian 证据后才确认 drain。
- **修订号并发**：Guardian 在 Backend 提交消费时会合法地推进 answerRevision（参考模型第 233 行），因此写操作前用只读 `JournalQueryAnswer` 刷新；只有带稳定幂等键的写（Prepare/Confirm/Seal）在 `STATE_CONFLICT` 后刷新并原样重试一次；发 ticket 的 START/续段永不重试。
- **Seal 哈希**：manifestHash = 有序 `{artifactId, sequence, artifactHash}` 的 digest；finalAnswerTextHash = 各单元文本拼接的 SHA-256，与 Go builder 和参考实现一致（oracle 校验通过）。

测试（`output_guardian/tests/v2/test_answer_coordinator.py`，真实 Guardian Receiver + PrivateIPC + ReceiverRuntime；Backend 为契约 oracle，接口与 JournalClient 相同）：两单元 Prepare→START→drain→续段→drain→seal 全流程，**oracle 校验单元 2 的首个音频样本正好接在单元 1 末尾**（真实 Guardian 保持会话时钟连续）；Prepare 回执丢失只重试同一单元；START 回复丢失 → 终止 UNKNOWN、不 TTS；播放中 Stop 不可逆；Observer 不可用 → 不确认 drain、不开始下一单元；他人命令的 Artifact 在 Prepare 前被拒。6 PASS；6 个变异全部检出（`evidence/stage2c-coordinator-mutations.txt`）。

真实链路（`TestPostgresReceiver1RuntimeCoordinatorFailsClosedWithoutObserver`，-race 3/3）：协调器驱动真实 JournalServer + 真实 PostgreSQL + 真实 Guardian：Prepare、START（含真实 JournalQueryAnswer 刷新）、一次消费、一次 TTS 成功；Observer 是关闭夹具，drain 必须失败——Backend `dl05_answer_drain_receipts` 为 0 行，latch 恰 1 行。

全量回归：Guardian 239/0/1，Go race 275/0/8，其余全绿（`evidence/stage2c/coordinator-full-regression-summary.txt`）。第一次全量运行中出现 1 个与本改动无关的负载偶发失败，原始日志保留，见 02 P3-f。

## 2d：接入真实 TTS（已完成）

`runtime/app/receiver1/speech_media.py`：`SpeechMedia` 是交给 `speak_once` 的唯一一次 TTS 调用。它流式读取现有 TTS 提供方（本机实测 sherpa-onnx VITS `zh_CN-xiao_ya`，CPU，22050 Hz），用**一个**有状态 libav 重采样器转换到受信 Session 采样率（16000/24000/48000）并在结尾 flush，切成 ≤200 ms 的块；配置头像时把每块喂给现有 CPU 轻量头像引擎并交错输出口型视频帧。一个 `SpeechMedia`（及其头像引擎）贯穿整个 Session，视频 PTS 跨单元连续递增。

为接入真实流式 TTS 而修复的问题（均由真实测试暴露）：
- `speak_once` 原先 `await synthesize(...)`，流式 TTS 返回异步生成器会崩溃——现在接受可等待对象或流；一次性闩锁仍在调用前获取。
- 执行器原先按“每 8 个媒体项”续 proof——真实合成耗费墙钟时间，改为**按剩余 proof 时间**续期（剩余 <0.35 s 时续）。
- 执行器原先尽快推送媒体，Guardian 有界队列（8 项）满后按契约 `OVERLOADED` 失败关闭（10 次中 4 次）——Runtime 现在按**实时节奏**推送（音频最多领先墙钟 0.25 s），这也是真实直播推流的行为。修复后 10/10 通过。
- 执行器改为流式交付：媒体边合成边推送，不先整段缓存。

测试 `output_guardian/tests/v2/test_real_speech.py`（真实模型缺失时显式 skip，绝不假通过；模型 SHA-256 记录在 `evidence/stage2d-real-tts.txt`）：
1. 同一次合成内重采样样本守恒：输出 = 输入×16000/22050，误差 ≤1 个样本（实测 libav flush 后为向上取整；不 flush 会少 16–17 个样本），块大小受限，RMS 证明是真实可听语音。VITS 有随机性，不跨两次合成比较。
2. 头像帧：PTS 严格递增且跨单元不归零；帧数≈时长×25；尺寸等于 Session 尺寸。
3. 端到端：协调器 × 两个答案单元 × 真实 TTS + 真实头像 → 真实 Guardian Receiver/IPC → **真实 CPU 输出子进程编解码**（消费 Guardian 队列）→ drain 证据（信封合成，区间来自真实解码）→ oracle 检查单元 2 音频紧接单元 1 → seal。TTS 恰好 2 次；Guardian 的 tail 与 TTS 实际输出样本数完全一致。

稳定性：节奏修复后 10/10 PASS（每次约 7 s，按实时播放）。变异：去掉重采样 flush、丢弃最后不足一块的音频、每单元重置头像时钟、去掉实时节奏——**4/4 均被检出**（第一次的变异结果在基线不稳定时无效，已在证据中标注；S3 第一次的变异写错、S1 第一次因容差 32 过宽未检出，均已修正并如实保留）。全量回归：Guardian 242/0/1、Go race 275/0/8，其余全绿；第一次全量运行出现 1 次已知负载偶发（02 P3-f）。

真实发现（未修改受保护文件）：该 VITS 中文模型**静默跳过拉丁字母**（日志 “Ignore OOV 'T'/'S'/'M'/'L'”）。“纯棉T恤有S、M、L和XL尺码”会被读成“纯棉恤有……XL尺码”，S/M/L 不读。现有 `spoken_sizes()` 只覆盖“尺码有 S、M…”等句式。见 02 P8。

## 阶段 2 后续步骤（建议顺序）

- ~~2b~~ 已完成（见上）。
- 2c：Python Runtime v2 Journal 客户端（RUNTIME_JOURNAL 操作）与 Runtime 侧流式协调器（按方案 1）。
- ~~2d~~ 已完成（见上）。剩余：把协调器接到 Runtime 实际的评论处理入口（与阶段 6 一起）。
