# 14 — 阶段 3b：Guardian RTMP 推流 Sink + 独立 RTMP Observer

## 结论

Guardian 自有子进程把每个已准入的媒体项写入**一条贯穿整个 Session 的 RTMP 推流连接**。独立的 Observer 进程作为该管道上的**被动 tap**，按字节解析推流，并原样转发给 ingest（MediaMTX，今后是平台）。单元结束时，由 Observer（而不是 Guardian）从管道上实际出现的字节构造 `RTMP_PIPE_WRITE` 证据；Guardian 用这份证据得到 `LOCAL_MEDIA_DRAINED`。整个过程不补齐、不 flush、不断开连接，也不在单元之间重新定时。

- 本阶段证明的是：单元尾部样本已写入 RTMP 管道。
- 本阶段**不**证明观众可见：`audienceVisibility` 保持 `UNVERIFIED`。
- Backend 记录这份证据（经 `ObserverClient`）并真正 DRAINED 的 Go 端到端测试是 3b-3，尚未做。
- `OUTPUT_FENCE_UNPROVEN` 保持不变。

## 实测发现（决定了设计）

| # | 现象 | 证据 |
| --- | --- | --- |
| 1 | MediaMTX v1.21.1 接受 H264+LPCM，但要经过 track 分析期（>2 s）才宣告上线。1–2 s 的流从未上线，经 MediaMTX 拉流的 reader 会错过开头 | `stage3b-ingest-acceptance.txt`，以及更早的探针 |
| 2 | libav 的 RTMP/FLV **读取端**会扣住最后一个 tag，直到下一个 tag 到达。nobuffer/probesize 最小化后只识别出视频流 | `stage3b-probes/libav_listen_observer*_probe.py` |
| 3 | 真正的根因在**发布端**：libav muxer 的交错器会把单元最后一个包排队，等待另一条流的包。最后 640 个样本要到断开连接时才离开进程，`max_interleave_delta=1` 无效，PyAV 也不提供 flush 接口 | TCP 中继逐字节计时；tap 显示 25 帧视频、24 包音频 |

因此，如果继续用 libav 发布，“已写入”的确认是不真实的。现在子进程**自己说 RTMP**：
- 简单握手；
- `connect` / `createStream` / `publish`；
- `@setDataFrame` + `onMetaData`（音频 PCM，flag `0x32`，采样率由元数据给出，与 ffmpeg 的写法一致）；
- 每个 FLV tag 都用 fmt-0 chunk 头、经 `sendall` 写出，用户态不留任何缓冲。

因此“确认”的含义是“已交给 RTMP 管道的内核 socket”。写入设有 1 s 超时：ingest 停滞时子进程退出，结果是失败关闭。

## 组件

| 部件 | 内容 |
| --- | --- |
| `output_guardian/v2/rtmp.py` `RTMPMedia` | 继承 `CPUMedia`：所有权、撤销边、readiness challenge、sink 行和 tail 比对全部沿用，只替换子进程的媒体工作（`child_target` / `ready_kind` / `child_args` 三个挂点，`cpu.py` 只加了这些挂点）。音频为 16-bit PCM，视频为 libx264 zerolatency、无 B 帧、每秒一个关键帧，每帧恰好产出一个包（否则 `OUTPUT_FENCE_UNPROVEN`）。每次管道写入**之前**都检查可撤销边。推流 URL（可能含凭据）只在内存中交给子进程，repr 中已脱敏。 |
| `runtime/app/receiver1/rtmp_observer.py` `ChunkParser` / `Ledger` | 增量解析 RTMP chunk 流（fmt 0–3、扩展时间戳、Set Chunk Size）。音频必须是 16-bit 单声道 PCM，且时间戳等于按样本累计的位置（缺口或重叠都会 fault）。视频必须是 AVC，每个 NALU 消息算一帧，时间戳严格递增。出现 Aggregate 消息、孤立的续块或格式变化时一律 fault：停止转发，不再出具证据。 |
| `RTMPObserver` | 每个 Session 只接受一个推流连接，转发到 upstream。`prove()` 先等单元尾部真正出现在管道上（`settle` 0.5 s，超时为 `OUTPUT_FENCE_UNPROVEN`），再核对：该区间 PCM 的 sha256 等于 Guardian tail 的 `audioHash`；每个 tail PTS 恰好对应一帧（多帧、少帧、改时间都算 `EVIDENCE_CONFLICT`）。只有核对通过后才构造证据，可选先经 `ObserverClient` 向 Backend 记录。证据通道是 0700 目录下的 AF_UNIX socket，内核对端 pid 加进程身份钉在 Guardian 上。 |
| `TapEvidence` | Guardian 侧的 `evidence_builder`：只发送它即将声称的 tail，并反向钉住 Observer 的进程身份。证据完全由 Observer 生成。 |
| `python -m runtime.app.receiver1.rtmp_observer` | 独立进程入口：stdin 读一行不含秘密的配置，就绪后 stdout 输出 `READY <port>`。OBSERVER 凭据（`load_inherited`）由阶段 4 的 Host Launcher 接入。 |

信任说明：Session 音频原点 `audioOrigin` 是 Observer 的会话配置，不取自 Guardian 的请求字段。

## 验证

`output_guardian/tests/v2/test_rtmp_sink.py`（真实 MediaMTX + Observer 独立进程，4 项）：

- **一个 1 s 单元**（25 对 40 ms 音视频，按实时节奏发送）：
  - 结果为 `LOCAL_MEDIA_DRAINED`，`sinkProofs[0]` 为 `RTMP_PIPE_WRITE`、`terminal`、`[0,16000)`、`finalVideoFrame=24`；
  - 推流子进程与 Observer 都仍然存活，即管道保持打开时尾部已经可证；
  - 管道上从未出现的尾部 → `OUTPUT_FENCE_UNPROVEN`；错误哈希 → `EVIDENCE_CONFLICT`；中间一帧改时间 2 ms → `EVIDENCE_CONFLICT`。
- **非钉住进程**请求证据 → `UNAUTHENTICATED`。
- **撤销**（音频、视频各一次）：
  - 先写入并确认另一种媒体；
  - 下一项编码完成、停在写入前时执行 Stop，再放行；
  - 结果：该项没有确认行；用**正确**的哈希和 PTS 询问 Observer，答复仍是 `OUTPUT_FENCE_UNPROVEN`，说明字节从未进入管道。

`test_rtmp_observer.py`（9 项，无网络）：
- 用 Guardian 自己的 Publisher 帧生成字节，按 1/3/4096 字节以及整段切分喂给 parser，结果完全一致；
- 缺口、AAC、同一时间戳两次、非 AVC、Aggregate、孤立续块都会 fault；
- 扩展时间戳（约 4.6 小时）往返正确；
- `prove` 在尾部到达前不出证据。

MediaMTX 接受性（`stage3b-ingest-acceptance.txt`，6 s 流）：
- MediaMTX 宣告 `2 tracks (H264, LPCM)`；
- tap 收到的 PCM 与发送的逐字节一致；
- 经 MediaMTX 拉流得到的是一段连续、逐字节一致的切片，一直到最后一个样本（开头部分因分析期缺失，这正是证据不采用 reader 的原因）。

变异（`stage3b-mutations.txt`），8/8 被检出：
- 子进程丢弃每项最后一个样本；
- Observer 不查哈希、不钉对端、不查音频连续性、不等尾部、不查视频 PTS；
- 子进程在音频或视频写入前不检查撤销边。

第一轮中 M7a/M7b **存活**：原撤销测试只发一种媒体，探针无法区分“泄漏”和“未写入”。已改成先写入另一种媒体，并用正确哈希探测，之后两项均被检出。

稳定性：RTMP、Observer 与 CPU 测试连续 8 轮均为 20/20。

### 过程中的问题（如实记录）

- 撤销测试一度**卡死**：
  - 测试没有续期 Permit，proof 过期后 watchdog 杀掉了停在 multiprocessing Event 上的子进程，`Event.set()` 的 `notify_all` 于是永远等待一个已死的 sleeper；
  - 修复：测试期间持续续期；放行改为在 daemon 线程里 `set()`，并限时 join。
- 第一次全量回归运行期间，我同时运行了变异脚本（它会临时改写源码），所以那次回归**作废**，结果保留在 `evidence/stage3b-aborted-contaminated/` 并附说明，随后重新完整运行。

## 下一步

- **3b-3**：Go 端到端测试。在 receiver-1 中托管 RTMP Observer（OBSERVER 角色与凭据），Observer 用 `ObserverClient` 记录证据，Runtime 用同一证据确认，得到真正的 DRAINED；并验证 Observer 退役或 fault 后失败关闭。
- 之后：协调器接入 Runtime 评论入口；阶段 4（Host Launcher，交付凭据与 Session 原点）；平台 AAC 转码位于已证明的 sink **之后**，不进入证据。
