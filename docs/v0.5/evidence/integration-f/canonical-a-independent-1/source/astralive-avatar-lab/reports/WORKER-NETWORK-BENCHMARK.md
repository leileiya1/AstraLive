# 2026-10-09 最新状态

`BLOCKED — LATENCY`。新增私有 SSH relay 传输与实际 WebRTC＋RTMP双 Sink。编码P95 5.618ms，音频队列最大2000ms、视频960ms。600秒旧B RTT仍只属于旧测试。本次完整网络分解未补齐；因浏览器音画偏差停止长测。

完整证据与边界见 [本次重试报告](SOULX-LIVE-RETRY-2026-10-09.md)。

---

以下是此前收尾记录；涉及旧实例与尚未执行事项，以本次重试报告为准。

# 私有链路实测

阶段B：GPU Worker→Mac私有SSH中继→school-linux，单连接/单generation2000连续600秒媒体（墙钟601.681秒）。15000接收/解码/消费帧，平均有效媒体吞吐25FPS；消费者最大迟到1.177ms；150005535编码字节约2.000Mbps；正常GenerationComplete、消费线程全退出、Worker连接清理。未见OOM/queue drop或持续积压。

H264无B帧、GOP25、4帧在途信用，音频sample-derived PTS。编码P95 5.491ms，解码P95 0.358ms；nonce Health RTT P95 104.384ms。无跨机器裸monotonic相减的单向时延宣传。queue轨迹/每帧PTS见streaming/network/ten-minute/events.jsonl。

完整接收视频已封装为worker-ten-minute.mp4，FFmpeg完整解码与ffprobe记录保存。school-linux保留完整143MB MP4，Mac只保留10秒末段、全部原始时间戳/性能日志及媒体校验，删除本地重复H264/完整MP4/配套WAV；清单见STREAMING-CLEANUP-MANIFEST.json。完整片路径：~/AstraLive/experiments/real-avatar/soulx-streaming/network/ten-minute/worker-ten-minute.mp4。MP4后期合并音轨不等同实时浏览器AV验收。

10秒250帧、错token拒绝和推理中FORCE也完成。增强权重/健康版本只重测了真实LLM/TTS及浏览器短链路，没有再次跑600秒。首帧样本量不足P95评估。

真实断开私有GPU隧道的浏览器试验中，当前任务及后续回答完成，画面marker从GPU切换到LIGHTWEIGHT；同一WebRTC继续收到音视频。OOM/进程crash/health超时/推理stall未逐项真实注入，不能声称全故障验收。
