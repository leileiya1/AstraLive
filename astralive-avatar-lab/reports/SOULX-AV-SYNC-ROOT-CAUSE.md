# SoulX 音画同步诊断与修复 — 2026-10-09

## 结论

原始约 600ms 异常已确认包含 **AudioContext/MediaRecorder 录制时间轴停顿**。修复录制路径后，本轮连续一小时又发现原生收到的音频轨道 PTS 空洞与浏览器录像偏差；**不能断言所有异常都仅发生在录像，也没有证明原生实际扬声器播放始终同步**。最终 `BLOCKED — AV SYNC / MEDIA / WORKER`。

## 原始证据与时间线

原 436.463s 测试与失败报告保留，未覆盖。已亲自读取要求的 7 份报告，检查并解码 `public-dual-one-hour-20261009`、`latency-gate-evidence-20261009` 的 Browser/RTMP 视频、stats、事件与偏差片段。原 job `1791506334562328` 的 sample40000、48000，Browser 视频领先音频604.75/573.75ms；学校同源消费最大21.422ms，旧 RTMP同段约120.375ms。177对学校同源消费观测支持上游同步，但不证明浏览器播放。

原音频编码 packet 在199.453s/200.142s附近出现76ms/506ms空洞，累计582ms；AudioContext.currentTime 相对同机单调时钟少推进约584ms，即便 state仍是 running。32000→40000 sample的实际录制间隔多出约582ms。CPU Chrome 独立校准：人为暂停AudioContext600ms，其合成destination录像出现约595msPTS空洞，原生tracks录像未出现对应空洞。详见 `original-packet-audit.json`、`original-runtime-consumption-audit.json`、`cpu-clock/`。这确认录制路径机制；**历史 AudioContext/OS render stall 的触发源及历史物理原生播放：ROOT CAUSE UNCONFIRMED**。

可信链路：16k source sample → Runtime音频绝对sample/PTS → Worker同源frame_sequence(640samples/40ms) → 学校 Fanout consumed monotonic → RTP音频48k/视频90k → Chrome estimatedPlayoutTimestamp与requestVideoFrameCallback → 原生AV element / 原生tracks录像 → Canvas独立录像。学校、GPU、浏览器不同主机 wall clock未直接相减。GPU时间差仅同GPU；学校消费差仅同学校；浏览器↔学校首帧使用最小RTT单调时钟校准（RTT13.4ms），明确非物理扬声器测量。

## 路径分别验证

A 原生WebRTC Audio+Video：前端现有 `<video srcObject=stream>` 和验收原生AV element。记录Chrome音视频RTP、jitterbuffer、media-playout与帧回调，音频未muted。

B 原生Audio+Canvas：另存Canvas录像，Canvas等原生视频展示回调后再绘制，独立标识其额外展示延迟。

C AudioContext+Canvas：CPU校准重现暂停机制；正式一小时路径使用原生音频，不使用AudioContext。

D Canvas.captureStream+AudioContext destination+MediaRecorder：保留旧失败样本及CPU重现。正式canonical录像改用原生收到的audio+video tracks；没有添加固定600ms延迟。

E RTMP：使用实验MediaMTX及接收端完整录像，不接真实商业平台。

## RTMP独立源时钟缺陷

误降级修复后第一条准备运行在562.309s结束：RTMP job1791510223893151 source136000 发生约−300ms差，500ms相关.744、100ms相关.718；同源native约−41ms。两个独立音视频writer/filler定时器分别积累underflow且视频sourcePTS未用于共同推进。证据保存到 `previous-rtmp-failure/`，真实Session正常APIStop至ENDED。未计入最终小时。

实验配对时钟修复使音视频源进度一起消费或一起等待；保留有界缓冲，不扩大正式队列。最初单writer触发FFmpeg512帧demux预读取死锁，已改两个容量2对的独立writer；CPU真实FFmpeg带underflow回归最大差0.375ms。最终HourRTMP P95约40ms，max160ms。没有更改正式RTMP核心或模型。

## 测量与不得美化的剩余失败

固定500ms源PCM假定连续播放，在真实underflow和视频hold期间会制造偏差；100ms短窗口也会匹配重复语音。原始结果全部保留。新版480ms、40ms帧对齐窗口，参考音频根据独立同机音频消费cadence展开；RTMP根据已验证配对源时钟展开。相关系数>=.7标识可信窗口，低相关、缺时序、未发声、缺锚点窗口全部保存状态，不删离群点。已合成验证：400msunderflow假偏差被解释；真正额外600ms延迟仍检测为600ms。原始600ms样本用短窗口仍测得601.75/573.625ms，分析器不能把真实大偏差隐去。

最终本轮Browser原生轨道录像2680可信窗口 P95 **155.0625ms**，max**325.1875ms**，3个高相关>.7窗口>250ms（相关.891/.942/.931），独立学校同源消费分别19.568/20.563/20.010ms。job1791512043967373 source153600、job1791512063292404 source7680/30720保留于 `outlier-final-verification.json`。Native/Canvas audio同段有**1.567s PTS空洞**，Chrome原生播放估计连续9个样本>250ms，max1611ms，随后恢复。只有录像与估计，缺物理speaker-loopback，因此无法确定用户实际听到的差值；更无法将其全归为无害录像误差。150ms门槛已经独立失败。

- `streaming/async_link.py`：视频 stall 以当前等待过程和真实解码推进为依据；Cancel/Begin 串行、取消 ACK 按 generation 匹配。
- `streaming/prefetch.py`：降级状态不创建无 PCM 的 GPU job；失效代际不误报 provider failure。
- `streaming/runtime-experiment/app/soulx_remote.py`：只有当前 pipeline owner 可清理/恢复 idle；旧任务 finally 不清掉新任务；保留完整异常原因。
- `streaming/runtime-experiment/app/soulx_rtmp_clock.py`：新增实验性 40ms 配对源时钟，1 视频帧配 2 个 20ms 音频块；视频/音频共同推进或共同 filler；管道 writer 分离且各最多 2 对。
- 实验 `app/main.py`：仅 `SOULX_PAIRED_RTMP=1` 时使用配对 RTMP sink，保留既有诊断字段。
- `browser_final_acceptance.html/.py`、`final_player_gate.js`、monitor/start/reader：真实原生 AV element、直接收到的 AV tracks 录像、Canvas 独立诊断、ready 后起计时、独立受控进程、同一连接 6 个检查点。
- `sync_measure.py`、`sync_warped.py` 与针对性测试：记录全部窗口；使用独立的实际消费 cadence 构造有 underflow 的参考 PCM；不拟合播放 offset，不删除异常。


## 2026-10-09 CPU 浏览器修复追加证据

同一 Mac 的 CoreAudio 与浏览器 timestamp 确认上一小时约T+828s默认扬声器切换至蓝牙，Chrome音频设备StartIO耗时1492ms；RTP/视频继续，实际音频播放停顿，随后三个>250ms可信窗口发生在时钟追赶阶段。隔离Chrome AudioService暂停1.6s可独立CPU重现。固定具体内置输出的120秒录像P95/max59.06/92.63ms；实际产品Hook在音频恢复后只重建同Session预览，恢复录像P95/max25.63/49.63ms，独立原生播放估计P95/max33/38ms。故障空洞及所有低置信度窗口保留。

原436秒600ms事件也有711ms蓝牙StartIO，因旧数据缺少精确同机wall anchor，仅作为机制佐证。详见 [CPU修复报告](SOULX-CPU-BROWSER-AV-REPAIR.md)。本轮没有GPU/全链路新一小时测试，原正式验收Verdict仍为 **BLOCKED — AV SYNC / MEDIA / WORKER**。


## 2026-10-09 最终固定设备真实GPU对照

同Session3600.781秒、63FORCE：native estimated P95 30ms/max65ms、正式原生录像P95 44ms/max79.75ms、RTMP P95 40ms/max44.06ms；所有可信窗口无>250ms，完整录像audioPTS gap0。保持设备固定和此前paired RTMP修复，未改模型/固定加600ms延迟。新证据进一步支持Mac音频设备切换阻塞修复有效；原436秒600ms样本缺精确墙钟锚点的不确定性保持。末5分钟出现28次LLM失败，停止后旧Key401，新KeyCPU200；音画专项PASS，未伪报完整业务PASS，用户要求不重跑。详见SOULX-FINAL-ONE-HOUR-PINNED-ACCEPTANCE.md。
