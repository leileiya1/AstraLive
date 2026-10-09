# 2026-10-09 最新状态

`BLOCKED — LATENCY`。新增公开 Go FORCE 与实验 canvas 显示代际门禁；回调旧 generation 泄漏计数0。人工缓存画面、任意 RTMP解码器不能据此宣称全面零残留。断GPU隧道后当前及后续回答真实降级；完整OOM/crash/stall矩阵未执行。

完整证据与边界见 [本次重试报告](SOULX-LIVE-RETRY-2026-10-09.md)。

---

以下是此前收尾记录；涉及旧实例与尚未执行事项，以本次重试报告为准。

# FORCE与代际可靠性

5项CPU adapter检查PASS；预取/重采样/异步链路11项PASS。真实GPU：generation1000第三块Start23102437.045242、Cancel23102437.069790、旧Output23102437.294866，安全边界完成后拒绝24帧并清理640 queued样本。新1001收到/解码150帧，IDR/PTS正确；FORCE→新首帧1.373940秒；Worker取消后旧任务发布0帧，人物只加载一次。

证据：streaming/network/controls，streaming/evidence/worker-events-stage-b.jsonl。pose来自实际远端消费的9帧，编码出队不算实际发布动作历史。generation单调、不重用；远端解码/出队检查epoch和job；接收Credit按顺序确认。

隔离Runtime中真实PLATFORM_EVENT/COMMENT经过LLM/TTS、浏览器正常播放后进行FORCE，新商业generation正常完成、Worker不重载模型。真实GPU零音频Idle、Idle→Talking、Talking→Idle也跑过；GPU_INFERENCE、CACHED_IDLE、LIGHTWEIGHT_AVATAR分别记录，既有sink空队列重复上一帧不计为推理吞吐。

边界：浏览器FORCE请求后仍出现4次旧marker显示，最后一次距请求281.2ms。Worker不发布新旧混淆的帧，不能因此声称浏览器旧画面完全零残留。已发RTP/解码播放缓冲需要浏览器代际显示门禁或认证控制消息与RTP时间戳映射；目前只证明school/Worker fence，尚未验证浏览器最终严格代际门禁。这是完整集成验收的未完成项。

浏览器自然动作短片保留；静态截图/像素变化不是人工自然度评分，当前流式动态效果未替代前期用户对模型视频的验收。
