# 2026-10-09 新 GPU 真人链路重试

最终状态：`BLOCKED — LATENCY`。没有完成一小时验收，不宣布 `REAL AVATAR INTEGRATION ACCEPTED`。历史阶段 A/B 结论保留。

## 新实例核验与恢复

新端口 45713 已实际连通；原实验目录起初不存在，按已验证来源重新恢复隔离环境。RTX 4090D 24GB，Python 3.12、PyTorch 2.8.0+cu128、CUDA 12.8、FlashAttention 2.8.3；实际 BF16 CUDA 运算与隔离环境依赖检查通过。官方代码实际 HEAD 为 `9bc03de06bb0de82cd6bc477804512ae06144bf2`，7 个模型文件按原 SHA-256 验证；没有换模型、训练、重做选型或购买服务。

新 Worker epoch `a21a8b1283d8457b95728cf381f4a7e4`。本次启动至 `GPU_WORKER_READY` 53.605 秒，含加载、人物准备及三块预热；不把这个数字冒充已清空所有编译缓存的冷启动。后续对话、待机和 FORCE 共用同一驻留模型。

## 已执行门禁

- 真实公开 Go COMMENT / OPERATOR FORCE → DeepSeek LLM → XiaoYa 原生 TTS → 状态化 16k PCM → 私有 SoulX Worker → school-linux → Chrome WebRTC。公开注册表保留既有 MOCK 枚举，实际实现由隔离 Runtime 的 Feature Flag 选择，不新增 Frozen Public Contract 字段。
- 原生 TTS 有界回调与 PCM/视频信用控制；仍保留原模型 8 秒滚动特征窗口、24 新帧/960ms 音频块与 9 帧运动历史。追加音频不重算不断增长的全 WAV；非因果 wav2vec2 特征不能直接当作等价嵌入追加。
- 浏览器实验 canvas 代际显示门禁、真实 FORCE、GPU 隧道断连后同 Session 后续回答继续使用 LIGHTWEIGHT_AVATAR，均执行。此门禁只属于实验页面，不声称正式前端或任意 RTMP 客户端已具备代际撤回功能。
- 90 秒单 WebRTC 短测：97.168 秒正式计时，零记录丢包/解码掉帧。双 Sink 短测：30.566 秒正式计时，零记录丢包/解码掉帧，RTMP 收到可播放的 H.264/AAC、512×512、25FPS 文件。
- 原 Runtime 25 项与新增 Adapter 5 项校验此前本次恢复后通过；本地正式 Runtime 17 文件与原 SHA 基线一致。school 正式 Runtime 本次中途快照 14 文件至清理后保持一致，不能将本地 17 文件清单误称为 school 清单。

## 阶段 C：同一 Session 主动终止

Session `session_fa9af9f58fd31a9b9bb23ca86c4a1221`；同一连接与同一 Worker epoch，未累计多个测试时长。

90 秒检查点实际 90.003 秒；5 分钟检查点实际 300.002 秒。最后成功周期为第 27 次，正式计时 436.463 秒；当时解码 11672 帧、丢包 0、解码掉帧 0。没有 15/30/60 分钟记录。

浏览器回调中 FORCE 后旧 business generation 新帧显示计数为 0。FORCE 期间人工绘制的缓存待机图没有独立回调样本，不能把这个计数扩大为对所有缓存画面、原生解码缓冲及 RTMP 客户端的全面证明。

抽查发现 job `1791506334562328` 的 source sample 40000 与 48000：浏览器录制视频分别提前音频 604.75ms、573.75ms，相关系数 0.9625、0.9565；排除附近峰后仍是唯一强匹配。对应 school 同样本消费最大差 21.422ms；同段 RTMP 录像差约 120.375ms。异常范围缩小到 WebRTC/浏览器播放/AudioContext/录制支路，具体根因未确定；不能说只是录制伪影，也不能归因于 SoulX 模型或整个网络。

据“存在明显音画延迟时不浪费一小时继续测试”，00:43:26 UTC 请求公开 Stop，公开 Session 最终 ENDED。测试器等待被取消的 utterance 后记录 gate timeout，随后重复 Stop 返回 SESSION_NOT_READY；原始 FAILED summary 完整保留。这是人工门禁终止后的测试器收尾局限，不是将失败改写成通过。

完整浏览器录像 544 个可信语音窗口：绝对偏差中位数/P95/最大值约 126.2/179.5/604.7ms。RTMP 抽查 433 窗口约 120.4/140.4/320.4ms。scope 选择使用近似时钟偏移；A/V 偏差来自同一录制文件 PTS，不依靠这个近似跨机偏移。

## 性能与测量边界

30 次首个重采样 PCM 获得 → school 首个视频解码 P95 722.7ms，最大 776.7ms。没有本次原生 TTS callback 起点及首帧编码/网络收包全节点的独立完整统计，不能称完整首 PCM→浏览器 P95。突发 TTS 输入也不能替代实时麦克风 960ms 预缓冲测量。

内核推理吞吐 92.27FPS，仅统计 GPU inference 耗时，不含特征、传输、播放等待；GPU 输出 10920 帧包含取消后丢弃，不能冒充最终发布计数。90→300 秒真实 RTC 解码速率约 24.98FPS，但包含缓存/重复画面，不能等同于持续真实 GPU 新帧吞吐。canvas 回调和录制也不能冒充 GPU 性能。

编码耗时 P95 5.618ms；观察到 PCM 待处理队列最大 2000ms、视频队列最大 960ms，信用最多 4 帧。未观察到 WorkerError / TransportSenderError。旧 B 的 RTT/P95 不能冒充本次 RTT；本次完整 RTT/传输/解码耗时分解尚缺。OOM/crash/stall 全部真实故障矩阵也未完成，不夸大断连实测范围。

## 证据与清理

完整浏览器录像与事件：`streaming/integration/public-dual-one-hour-20261009/`。对应公开 Stop、ENDED 查询、原始失败 summary、同 Session 90/300 秒检查点均在其中。

school 完整 RTMP 文件：`~/AstraLive/experiments/real-avatar/soulx-streaming/rtmp/one-hour-received.mp4`，时长 460.010 秒，包含计时前门禁，不是 1 小时。

可播放的同段浏览器/RTMP 10 秒截取：`streaming/integration/latency-gate-evidence-20261009/browser-offset.mp4` 与 `rtmp-offset.mp4`；新实例日志在 `streaming/evidence/new-instance-20261009/`。GPU 17 文件与 Mac、school 的 SHA-256 一致；校验清单 `streaming/evidence/new-instance-backup-verification-20261009.json`。

Worker 与监测进程已停止，GPU 显存 0MiB；隔离 Runtime/Backend 已停止，实验 MediaMTX 已停止；生产服务及 RTMP key 不改。删除 GPU 下载 prefix/range 重复文件 29 个、7,784,340,580 字节，完整模型重新 SHA 验证并保留。凭据没有进入备份。5个完整浏览器文件在Mac/school逐个SHA一致后，删除重复record分片，Mac合计释放116,281,886字节；较早一轮的逐分片清单未保存，重建依据及最新一轮清单在RETRY-CLEANUP-2026-10-09.json中。

保留源码、依赖锁定、权重 manifest、报告、时间戳、关键完整录像和片段。模型权重可按不可变 revision/SHA 重下载，本次没有再把约 8GB 权重传到 Mac。GPU 关机后分析不依赖它；释放临时实例前不要假定 autodl-tmp 会保留模型。

## 下一步技术门禁

先利用已保存音频/画面在 CPU 环境核对：直接原生 RTC 音轨、AudioContext 输出时钟、canvas/MediaRecorder 的 PTS，以及 RTP jitterBufferDelay/实际播放统计。分开录制两支，对照相同 source sample。修正计时与录制/播放问题后再做短测，不能盲目给一条轨增加延迟或缩短 SoulX 音频窗口。问题澄清后才重新申请同一 Session 的一小时验收，本次到此停止。
