# 13 — 阶段 3：真实 Observer 与 required Sink

## 现状核实（实现前）

- Backend 只有在**同一份**证据先由角色为 `OBSERVER` 的已登记进程经 `Store.RecordDrainEvidence`（可信仓库接缝，非冻结 wire 操作）记录、并通过独立校验回调 `Store.Observer` 之后，才接受 `JournalConfirmAnswerSegment` 的 drain；之后还会再核对证据哈希、required sinks、Generation、区间单调、单元间连续以及消费 latch。
- `Store.Observer` 在生产中为 nil → 记录一律 `FORBIDDEN`（失败关闭）。这就是此前所有 v2 drain 都失败关闭的原因。
- Guardian v2 的 `CPUMedia` 在**自己的信任域内**编码→解码→回传各 sink 并与 tail 精确比对，然后把证据交给缺失的 `evidence_builder`。CPU 模式没有任何“对外投递”的输出可供独立方观察。
- 冻结契约中 `SinkProof.kind` 只有 `RTMP_PIPE_WRITE` 和 `WEBRTC_TRACK_RECV` 两种。

## 设计结论

我最初设想的“独立进程解码 Guardian 内部 CPU 无损流作为 Observer”会不得不把证据标成 RTMP 或 WebRTC，属于**错误标注**，已放弃。诚实的 Observer 证据只能来自真实 RTMP 输出或真实 WebRTC 轨道。因此阶段 3 分为：

- **3a（本次完成）：Backend Observer 接缝**——所有方案都需要；
- **3b（下一步，需要你选方向）：真实 required sink + 独立 Observer**：RTMP（Guardian 推到 MediaMTX，独立 Observer 用自己的凭据拉流解码，类似 v1 已有的观测器）或 WebRTC（Observer 作为 WebRTC 接收端）。

## 3a 实现

| 部件 | 内容 |
| --- | --- |
| `StartManaged` / `load_inherited` | 接受 `OBSERVER` 角色；与 Runtime 一样不得持有签名密钥或 CONTROL 配置 |
| `ObserverPin` | 托管的 OBSERVER 进程 + 部署配置的可观察 sink 类型（RTMP 观测器不能为 WebRTC 作证，反之亦然）；Runtime/Guardian pin 不能成为 Observer |
| `ObserverVerifier` | 真正的 `Store.Observer`：调用方必须是在线、已登记的 Observer pin，证据类型 ALL_REQUIRED_DRAIN，每个 sink proof 必须 terminal 且类型在该 pin 授权范围内；之后 Store 自己的事务继续做范围、latch、连续性检查 |
| `ObserverServer` | 单一私有路由 `/registrar/receiver-1/observer/drain-evidence`，内核对端身份 + 独立凭据、严格 JSON（拒绝未知字段）、有界并发与超时；未安装 verifier 时拒绝启动；结果存疑时不给成功 |
| `ObserverClient`（Python） | Observer 进程使用自己的部署凭据；钉住 Backend 进程身份；存疑为 UNKNOWN |

## 验证（真实 PostgreSQL，`TestPostgresReceiver1ObserverSeamRecordsThenRuntimeDrains`）

真实 Runtime 进程经 JournalServer 完成 Prepare/START/一次消费/一次 TTS；单独启动并经 Registrar 登记的 OBSERVER 进程：
- Runtime 进程用自己的凭据记录证据 → `UNAUTHENTICATED`；
- RTMP Observer 为 WebRTC sink 作证 → `EVIDENCE_CONFLICT`；
- 未记录的证据用于确认 drain → `EVIDENCE_CONFLICT`；
- Observer 记录 → 成功，重复同一记录幂等；随后 Runtime 用同一证据确认 → **DRAINED**（v2 Go 测试中首次真正 drain）；drain 回执 1 行、Observer 证据 1 行；
- Observer 退役后再记录 → `UNAUTHENTICATED`。

**证据数值是明确标注的夹具**（尚无真实 sink），本测试证明的是接缝的安全与数据路径，不是播放。

`-race` 3/3 PASS。变异：verifier 不检查 sink 类型、server 不检查内核对端身份——均被检出。第一次 3 连跑中 2 次失败是测试缺陷：固定的 evidenceRef 在同库多次运行中被另一命令复用，Backend 正确拒绝（证据重放防护生效）；已改为每次唯一，失败记录与当时无效的变异结果均保留在 `evidence/stage3a-observer-seam.txt`。

全量回归：Go race 276/0/8；Guardian 242/0/1（复跑）；第一次全量运行出现已知负载偶发 P3-f（近 9 次全量中 3 次，机器负载 4–4.8）。
