# 最新验收记录（2026-10-09，固定Mac音频设备）

音画同步专项PASS：同Session3600.781秒、63FORCE；Chrome原生估计P95 30ms、正式浏览器录像P95 44ms、RTMP P95 40ms，无可信>250ms。正式Stop与清理完成。

完整原始全链路门槛仍为 **BLOCKED — AV SYNC / MEDIA / WORKER**：末约5分钟28条LLM_FAILED，旧Key停止后401；新Key CPU200。用户明确不重跑、按音画效果专项验收。完整报告：[SOULX-FINAL-ONE-HOUR-PINNED-ACCEPTANCE.md](SOULX-FINAL-ONE-HOUR-PINNED-ACCEPTANCE.md)。

以下保留此前失败验收记录，未覆盖原始证据。

---

# SoulX 最终一小时验收 — 2026-10-09

**最终 Verdict：BLOCKED — AV SYNC / MEDIA / WORKER**

## 结果与范围

同一Agent内完成诊断、最小实验修复、自动回归、一次最终连续小时、正式APIStop与清理。最终Session `session_ec9497702ee2986b5d2e0e0a16b4e388`，房间 `room_4dc90f75d74acb88dd794c069c11e35b`，真实连续 **3610.847秒**。6个检查点来自同一Session/Chrome PeerConnection；启动/编译/预热/协商未计入。52次正式FORCE，156业务循环，207个真实GPU speech jobs。不能因持续一小时且连接健康就宣布音画达标。

阻断项：Browser canonical native-track recording P95 **155.063ms >150ms**；3个高可信窗口 **276.875/315.875/325.187ms >250ms**；原生音频轨道1.567sPTS空洞和原生playout估计峰值1611ms未证明为无害录制误差。降级根因已找到并修复，RTMP修复达标，但整体未达到正式通过要求，不切正式生产Avatar默认Provider。

## 环境与真实链路

用户业务COMMENT/OPERATOR → Go Backend → 真实DeepSeek LLM → XiaoYa/sherpa-onnx真实TTS → 16k PCM → 云RTX4090D SoulX-FlashHead Lite → school-linux Runtime → Fanout → Mac Chrome154原生播放及实验FFmpeg/MediaMTX RTMP。

GPU24,564MiB、Driver580.105.08、Py3.12.3、Torch2.8.0+cu128、Toolkit12.8、FlashAttention2.8.3；7权重已有SHA验证，模型revision9bc03de06bb0de82cd6bc477804512ae06144bf2。Worker PID7753，epoch4d42cf3032314c73aac0b14e41bc817c，cachea847a19bf3f074a826e3157756673586f347ea0be93d8284961a33811fe8281f，全程同一resident Worker。学校bootId2c39c26e-0e68-4c2d-947f-3a211f5af075，Runtime1365154/Backend1365157/FFmpeg1365515/reader1366050。进程实际启动时间保存process-start/gpu-process-start/driver-process，setsid/受控supervisor独立于SSH及临时Agent命令；没有3600秒外层timeout。未新建收费实例、未安装依赖/下载权重、未改神经网络/采样参数。

## 根因与修改

误降级：客户端使用audio-horizon admission年龄判断视频stall，原失败窗口6.078s，但GPU最后真实发布仅2.920s，学校最后解码距降级2.061s。新判据关注所需源窗口已ready后真正没有视频推进的等待时长，保留5s阈值及有界队列。同步修复包括原生录制路径与实验RTMP配对源时钟，原始AudioContext停顿及新原生轨道异常区分记录。详见两个root-cause报告和原始样本，历史物理播放根因不夸大为已确认。

实际文件：

- `streaming/async_link.py`：视频 stall 以当前等待过程和真实解码推进为依据；Cancel/Begin 串行、取消 ACK 按 generation 匹配。
- `streaming/prefetch.py`：降级状态不创建无 PCM 的 GPU job；失效代际不误报 provider failure。
- `streaming/runtime-experiment/app/soulx_remote.py`：只有当前 pipeline owner 可清理/恢复 idle；旧任务 finally 不清掉新任务；保留完整异常原因。
- `streaming/runtime-experiment/app/soulx_rtmp_clock.py`：新增实验性 40ms 配对源时钟，1 视频帧配 2 个 20ms 音频块；视频/音频共同推进或共同 filler；管道 writer 分离且各最多 2 对。
- 实验 `app/main.py`：仅 `SOULX_PAIRED_RTMP=1` 时使用配对 RTMP sink，保留既有诊断字段。
- `browser_final_acceptance.html/.py`、`final_player_gate.js`、monitor/start/reader：真实原生 AV element、直接收到的 AV tracks 录像、Canvas 独立诊断、ready 后起计时、独立受控进程、同一连接 6 个检查点。
- `sync_measure.py`、`sync_warped.py` 与针对性测试：记录全部窗口；使用独立的实际消费 cadence 构造有 underflow 的参考 PCM；不拟合播放 offset，不删除异常。

18个本地正式Runtime源码SHA与基线一致，Frozen公共Contract/默认Avatar未变。正式学校源码版本与本地可能不同，此SHA证明范围仅本地；部署位置均既有school隔离实验目录。

## 自动回归与准备运行

原可靠Runtime测试79项：11环境性skip，余项PASS，隔离版亦保持。31项流式回归PASS（prefetch6、async3、resample2、既有final5、degradation8、paired4、cadence3）；GPU CPU Adapter5项PASS；浏览器ready/gate10项PASS。覆盖sample→videoPTS、16k重采样、AudioContext暂停/时钟、Canvas/MediaRecorder输出、generation owner/cancel ACK、队列背压、start/stop、旧帧拒绝与重连时钟初始化。实际FFmpeg配对underflow回归max0.375ms。测试原断言未降低。

准备阶段保存了Worker未ready、诊断字段缺失、FFmpeg预读取deadlock的0秒正式计时Session；另有误降级修复后的562.309秒RTMP失败，发现后保存并正常APIStop。不累加它们的时间；没有第二轮一小时。Worker始终复用，不为短CPU回归反复重启模型。

## 音画测量

绝对值 median / P95 / max（ms）：

| 路径 | 可信样本 | median / P95 / max | >250ms |
|---|---:|---:|---|
| BrowserNativePlayback | 3611 | 8.000 / 30.000 / 1611.000 | 9 estimates; not independent physical proof |
| BrowserRecording | 2680 | 124.000 / 155.062 / 325.187 | 3 |
| CanvasDiagnosticRecording | 2677 | 159.875 / 195.062 / 334.187 | 4 |
| RTMPRecording | 322 | 40.000 / 40.062 / 160.000 | 0 |

原生播放一栏是Chrome receiver estimatedPlayoutTimestamp差，senderNTP时间基准，不是物理speaker-loopback；P95虽30ms，max1611ms未解释，不能独立PASS。canonical录像用原生收到的audio+video tracks；Canvas诊断录像额外延迟且P95195ms，独立标记FAIL，不混同现有前端原生video。

参考源PCM480ms帧对齐，按独立实际消费cadence展开underflow。全部窗口与低可信状态保存，原500ms、100ms结果亦保存；原始600ms仍可被校准方法检测。3个>250ms样本学校同源消费19.568/20.563/20.010ms，偏差位于浏览器下游。没有固定600ms补偿、异常样本丢弃或跨主机wall clock直接相减。更详细证据在audio-video-sync/cadence-aware-sync/outlier-final-verification。RTMP322可信窗口max160ms、P9540.063ms，无音频PTS空洞。

## 同一小时检查点

| T+秒 | 实际秒 | Browser累计decoded | 正式FORCE累计 | 原生录像累计median/P95/max ms | 离线Gate |
|---:|---:|---:|---:|---:|---|
| 90 | 90.004 | 3407 | 1 | 115.000 / 119.000 / 119.000 | PASS |
| 300 | 300.004 | 8657 | 4 | 102.187 / 122.125 / 141.125 | PASS |
| 900 | 900.005 | 23653 | 15 | 97.938 / 143.875 / 325.187 | FAIL |
| 1800 | 1800.004 | 46153 | 27 | 121.125 / 155.062 / 325.187 | FAIL |
| 2700 | 2700.003 | 68655 | 38 | 124.000 / 155.062 / 325.187 | FAIL |
| 3600 | 3600.006 | 91154 | 52 | 124.000 / 155.062 / 325.187 | FAIL |

在线6个连接/worker/队列Gate均PASS；这些不等于离线音画验收。完整录像离线得到15分钟时已含3个异常，30分钟起累计P95亦失败；报告明确标记offline FAIL，没有将在线passed=true伪装正式PASS。当时仅native估计瞬态无法独立确认物理播放失败，未凭单一噪声窗口自动终止；全量独立录像核查在正常Stop后完成。这个在线同步Gate仍需改进，不能称可自动保护商业直播。

检查点保存ICE/connection、RTP/jitter/playout、GPU PID/cache/显存/温度/util、学校CPU/RSS/boot、Fanout及实际track队列/累计消费/背压、RTMPpublisher/FPS/重连、业务计数。allocator精确检查点在某些idle代际没有同generation样本，显式null；已有全量GPU allocator日志，不能编造瞬时值。

## 性能与资源

- GPU model call+RGB readback：**92.37 FPS**；加audio-feature耗时：**85.26 FPS**。不是仅CUDA kernel计时。
- 实际发布并学校解码GPU真帧54896，按整小时有效 **15.20 FPS**。
- 浏览器decoded输出 **24.999 FPS**；真GPU source帧54749（15.16FPS）；held GPU重复帧33157、cached idle2318、Lightweight0，重复帧未计入GPU推理FPS。
- FirstPCM→学校首GPUdecode median/P95/max：749.344 / 1138.138 / 3109.747ms；FirstPCM→原生帧回调：1300.165 / 1732.829 / 3643.542ms，RTT校准13.4ms，不含LLM首token前等待。
- Runtime采样RSS startup/peak/end：81.391 / 714.000 / 698.918MiB；峰值CPU44.9%。RSS有增长，不能声称恒定内存或已证明多小时无泄漏。GPU使用显存约5911MiB；allocator约4.1–4.3GiB allocated、5.34GiB reserved，原始日志为准；温度约39–54°C、util按需变化。
- 浏览器decoded掉帧0，freezeCount0；结束packetLost30，正式窗口增26，有重传，不称丢包0。RTMP processStarts1/reconnect0/writeFailures0，配对40ms时钟保持25FPS。

## 业务、FORCE与代际安全

正式COMMENT 127条，等待完成156个业务cycle，OPERATOR策略 {'FORCE': 52, 'INTERRUPT_LOWER_PRIORITY': 15, 'NONE': 14}。包含商品价格/尺码/库存/介绍、长短句问答、Idle/Talking、NONE/LOWER_PRIORITY/FORCE。真实语音和GPU增量生成，不循环预录音。

52正式FORCE；旧GPU结果拒绝/取消保留逐条日志，模型未重新加载。Canvas按**有序事件流**fence之后新到达旧代际展示0；一条与fence共享相同100us时间戳的展示在事件序列中发生于fence之前，已留索引证明，不能用时间戳<=误判/删帧。Runtime旧帧拒绝538，反映在途旧包被挡住。Native request之后仍出现780个旧代际帧，最迟1234.100ms；其包含API请求/控制传播和RTC解码缓冲，不等于GPU cancel后新发布泄漏，但也是实际用户可见残留，不能宣称端到端旧画面0。RTMP最多2对内部pipe buffer外还有已编码传输缓冲；未逐次量化显示旧代际末帧，作为限制保留。商业中断安全尚需独立接收端确认。

LOWER_PRIORITY在本轮提交15次，多在idle阶段；真实active抢占仅有单元覆盖，不能宣称本小时现场验证。SSE只在Stop前追加订阅，business-sse-audit不是全小时事件全集；全小时业务证据为browser事件/utterance等待结果及runtime各speech source WAV。

## Idle与故障降级

全native录像首60秒后全量采样luma黑帧0，12个分散时间点contact-sheet人工查看，人物脸部/背景连续。静态抽检无法证明每次眨眼自然/每次头部运动流畅，完整native/canvas录像保留。cachedIdle与真推理帧已分别统计。

误降级正式Hour事件0/Lightweight帧0。另在主Hour前真实Worker未ready时Session保留，COMMENT→真实PCM→degraded SpeechEOF，音视频继续消费，535decoded、1069audio packets，APIStopENDED；该准备driver未捕获单条UTTERANCE_COMPLETED，不称完整降级业务最终验收已通过。没有在正式Hour里主动断线。

## Stop、Cleanup与备份

正式API Stop：LIVE→SESSION_STOPPING(03:01:06.860Z)→SESSION_ENDED(03:01:08.363Z)，数据库状态ENDED、Runtime activeSessions0。之后GPU cancel、ConnectionCleaned sender_stopped=true，队列/任务清理，再停止仅本次owned基础设施。Runtime/Backend/FFmpeg/reader/Chrome/supervisor均已退出，无本次zombie；Worker SIGTERM后GPU0MiB/0%，实验MediaMTX停且restart=no。没有kill-all伪装正常Stop。

原失败证据未覆盖。当前完整录像、原失败关键片段、源WAV/日志、版本代码、权重SHA/环境锁、回归、checkpoint、normal-stop/final-summary备份到Mac独立bundle及school-linux独立results目录，并逐文件SHA256校验，结果见backup-verification.json。敏感.env、SSH私钥、DeepSeekKey、真实平台streamkey均排除；文本测试RTMP identifier脱敏。模型权重不重复备份。

租赁GPU实例保留，**仍可能持续计费，请用户自行暂停或释放**。本轮工作停止，不自动再跑一小时，不推进生产默认Provider、不开发其他平台/模型。

## 主Hour结束后的独立故障降级回归

GPU Worker保持关闭，独立CPU回归Session `session_e98404a4fb4728cd521b339c6ae85296`（78.024s，正式Hour计时0s）完成真实COMMENT→DeepSeek→XiaoYa→Lightweight Avatar；捕获UTTERANCE_COMPLETED。WebRTC decoded1808帧、audio packets3633，掉帧/丢包0；实验RTMP publisher ready，独立8秒接收录像可解码198视频帧、375音频帧。APIStop至ENDED、activeSessions0、RTMP publisher消失、仅此回归Runtime/Backend清理完毕。没有重启GPU或第二轮一小时。此前准备阶段完成事件缺口已补齐。证据：fallback-postcheck-summary.json及fallback-postcheck/。


## 2026-10-09 CPU 浏览器修复追加证据

同一 Mac 的 CoreAudio 与浏览器 timestamp 确认上一小时约T+828s默认扬声器切换至蓝牙，Chrome音频设备StartIO耗时1492ms；RTP/视频继续，实际音频播放停顿，随后三个>250ms可信窗口发生在时钟追赶阶段。隔离Chrome AudioService暂停1.6s可独立CPU重现。固定具体内置输出的120秒录像P95/max59.06/92.63ms；实际产品Hook在音频恢复后只重建同Session预览，恢复录像P95/max25.63/49.63ms，独立原生播放估计P95/max33/38ms。故障空洞及所有低置信度窗口保留。

原436秒600ms事件也有711ms蓝牙StartIO，因旧数据缺少精确同机wall anchor，仅作为机制佐证。详见 [CPU修复报告](SOULX-CPU-BROWSER-AV-REPAIR.md)。本轮没有GPU/全链路新一小时测试，原正式验收Verdict仍为 **BLOCKED — AV SYNC / MEDIA / WORKER**。
