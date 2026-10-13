# 2026-10-09 最新状态

`BLOCKED — LATENCY`。浏览器 544 个可信窗口 P95 179.5ms，最大 604.75ms；对应样本 school 消费差最大21.422ms、RTMP差120.375ms。具体根因未确定。首重采样PCM→school解码P95 722.7ms不能冒充完整原生PCM→浏览器统计。

完整证据与边界见 [本次重试报告](SOULX-LIVE-RETRY-2026-10-09.md)。

---

以下是此前收尾记录；涉及旧实例与尚未执行事项，以本次重试报告为准。

# 音视频延迟测量

首PCM、AudioFeatureReady、GPUInferenceStart、GPUOutput、EncodedFrameAdmitted、school接收/解码、消费者tick和BrowserFrameDisplayed分别记录。固定960ms新PCM模型窗口及120ms显式播放缓冲不隐藏；不缩短模型窗口。GPU与school monotonic不直接相减。

按采集时长实时释放PCM的10秒网络短测，首PCM→school接收1.422278秒、解码1.434371秒、paced tick1.554491秒；同一600秒测试为1.460659 / 1.462076 / 1.582277秒。这只是两次首帧，不能声称首帧P95达到2秒。

600秒编码P95 5.491ms、解码P95 0.358ms、Health RTT P95 104.384ms（1203样本）。不将各P95相加，不将RTT称为单向传输时长。独立transport单向时延尚未校准。

真实LLM/TTS预取：native22050Hz→状态化16000Hz，274帧；第一native PCM→school解码0.551428秒、paced释放0.674278秒。TTS突发很快提供960ms媒体，所以这不是实时麦克风窗口被缩短。独立文件消费者最大调度迟到3.541ms，EOF补607样本（37.94ms）已记录。

真实Chrome短测三次首段resampled PCM→首次对应marker显示1.10548 / 1.06326 / 1.07084秒。浏览器performance时钟与school校准采用最小RTT中点，单次不确定性约6.6ms；不是首帧P95。日志见streaming/integration/browser-short/latency-analysis.json。边缘marker只用于实验测量，没有改变SoulX推理。

最新独立同步短测记录190对源sample对应音视频帧的school WebRTC实际消费时刻：video−audio P50 0.079ms、P95 20.220ms、最大21.537ms。证据streaming/integration/school-final/browser-sync-consumption-analysis.json。sink消费不是浏览器听到声音的时刻，不能外推为完整端到端唇音同步验收。

浏览器MediaRecorder WebM可播放并保留，但FFmpeg发现Opus尾包解析告警和部分可变帧率时间戳告警。首次录音与源PCM整体相关系数仅0.288；录制包有时长空洞，直接拼接WAV不保留全部录制PTS，因此先前−1210ms估计不能作为实际AV偏差。后续需按原始录制PTS填充音频空洞并分段对齐，或做浏览器音频播放时钟/画面sample marker对照。这部分没有验收，不启动一小时测试。

早期FirstLocalDisplay只是Python调度tick，FirstEncoderInput不是已编码输出。初版姿态恢复编译导致15.18秒首帧的失败证据保留；预热修复后短测正常。Mac扬声器关闭及HTML audio muted不改变源PCM/媒体时间戳，静音浏览器RTP totalAudioEnergy为0不能解释为TTS生成静音。
