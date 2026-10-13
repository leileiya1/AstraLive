# 2026-10-09 最新状态

`BLOCKED — LATENCY`。公开 COMMENT→真实LLM/TTS→驻留SoulX→school→Chrome、FORCE、断连降级与双Sink短测已执行。阶段C同一Session仅达到90/300秒检查点，约7分钟终止；不能宣布完整集成接受。默认生产Lightweight和Frozen Contract保持原状。

完整证据与边界见 [本次重试报告](SOULX-LIVE-RETRY-2026-10-09.md)。

---

以下是此前收尾记录；涉及旧实例与尚未执行事项，以本次重试报告为准。

# AstraLive 真人实验集成收尾

最终状态：`SOULX STREAMING WORKER READY`。

阶段A增量PCM 10/30/60秒与阶段B单连接600秒15000帧已完成。用户2026-10-09选择费用优先：完成短测、备份清理并停止Worker，不执行一小时验收。不能宣布REAL AVATAR INTEGRATION ACCEPTED。

正式v0.1与Frozen Public Contract未更改。17个runtime/app源文件对照基线SHA全部一致。所有新Runtime代码在experiments/real-avatar/soulx-streaming-runtime；归档副本streaming/runtime-experiment。AVATAR_PROVIDER默认LIGHTWEIGHT_AVATAR，仅SOULX_LITE_REMOTE启用隔离Provider。

内部optional stream_audio hook解决逐chunk await无法积累960ms音频的问题：LLM sentence→有界native TTS callback→状态化16k重采样→2秒PCM预取→Worker；原WebRTC drain/interrupt/主时钟代码不覆盖。4帧消费信用由真实peer消费计数确认。语句间沿用同一job；EOF固定最多639样本显式补零；取消先fence后等待native TTS安全边界。

原Runtime测试25项通过，新增预取6/重采样2/异步链路3通过。真实LLM/TTS独立链路274帧通过。真实浏览器通过冻结Runtime端点提交PLATFORM_EVENT+COMMENT，完成说话/待机/连续对话/FORCE。断GPU隧道后同一Session继续完成回答及后续回答，切换LIGHTWEIGHT，未自动重播过期job。源码实际降级机制已执行；不是通过mock声明成功。

首次浏览器突发TTS触发credit耗尽后不刷新而卡在48帧；已修复Health有序快照刷新并加CPU回归，原失败日志保存。后续自然source句间间隔可造成sink空队列的静音/重复帧，应明确记录；不能把这种重复帧说成GPU连续推理。

边界与后续门禁：
- 浏览器媒体录制存在Opus尾包/时间戳告警，完整端到端唇音同步尚未验收；school对应sample消费190对最大差21.537ms只证明sink时间对齐。
- FORCE之后浏览器旧marker最后显示281.2ms，需要最终显示代际门禁，不能声称旧浏览器画面零残留。
- Go Public COMMENT→Session全链路未执行。隔离Backend仅启动在18180、独立SQL schema soulx_streaming_lab_20261009和Redis DB12；尚未创建公开业务Session，已关闭。不得把直接Runtime COMMENT短测说成公开API验收。
- WebRTC+RTMP双Sink尚未执行；生产RTMP stream key不读取/不修改，未连真实平台。
- 阶段C90秒/5/15/30/60分钟同一Session测试未执行，不能累计这些独立短测代替1小时。
- OOM/crash/stall/health timeout真实故障矩阵仍未执行。

GPU Worker PID93769、临时Runtime/Backend已停止；GPU显存0MiB、无compute进程。剩余归档/校验在本地与school-linux完成。租赁实例未由Agent释放，用户可在云平台关机停止计费。

必要证据/清理说明见STREAMING-BACKUP-AND-CLEANUP.md。
