# SoulX 自动降级根因与最小修复 — 2026-10-09

根因确认：Worker 客户端用音频模型窗口的入队时间判断视频推进停顿。这个时间在真实播放背压期间自然变旧，即使 GPU 正在生成、发布、解码，仍会被判为 `expected video progress stalled`。这不是 GPU OOM、模型崩溃或依赖不兼容。

## 同主机证据

原失败 job `1791508457078970` 已收到 187 帧，下一窗口要求相对源样本 122880。GPU PCM admission 至 Cancel 相隔 **6.07832874s**，而最后一帧 publication 至 Cancel 仅 **2.919976525s**。school-linux 最后一帧 decoded 至首次 Lightweight frame 仅 **2.060910546s**。所有差值只使用同一主机 monotonic 时钟，不跨主机相减。时间记录及离线复现见 `degradation-root-cause.json`、`regression-before.log`。

旧代码的 5s 判据是 `now - audio_horizon_admission`，因此正常有界背压会触发误报。新代码只有在当前所需源窗口已就绪且一次等待持续没有新视频解码时才开始计时，保留原 **5s** 停顿阈值，未扩大队列或固定推迟音频。

## 连带问题

1. 已降级 pipeline 仍执行 BeginGeneration，但不给 GPU 提供 PCM。修复为走 Lightweight 时不打开真实 GPU job。
2. 旧 stream_audio 的 finally 无条件清空 pipeline 并启动 idle，可能清掉新代际 owner。修复为只允许持有当前 pipeline 的任务清理状态；旧任务保留日志、不能改写新状态。
3. Cancel 与 Begin 未串行，旧取消 ACK 可误触新 job 的 Event。修复为同一 job lock 串行，并按 cancellation generation 接收 ACK。
4. 原 IdleDegraded 只保留异常类型，无法调查。现在保留原因、类型与 traceback；进度超时同时记录帧数、源窗口年龄和真正无进展时长。

## 修改边界

实现位于 `streaming/async_link.py`、`streaming/prefetch.py`、`streaming/runtime-experiment/app/soulx_remote.py`，部署到 school-linux 的既有隔离实验目录。`repair.diff` 和 `repair-files.json` 保存版本与 SHA256。正式 Runtime core、Frozen Public Contract、SoulX 权重、24 帧块、960ms 模型窗口与推理算法未修改。

回归：31 项音视频/客户端测试 PASS；Runtime discovery 79 项，11 项环境性跳过，其余 PASS；GPU Adapter 5 项 PASS；浏览器 readiness 10 项 PASS。原断线 fallback 测试保持完整 PCM；准备阶段真实 Worker unavailable 验证了 Session 保留、真实COMMENT→PCM→降级SpeechEOF、WebRTC音视频消费及 API Stop ENDED；该准备Harness没有捕获单条UTTERANCE_COMPLETED，不能称完整业务事件验收通过。准备失败未计入连续验收。

## 一小时验收结果

最终同一Session `session_ec9497702ee2986b5d2e0e0a16b4e388` 连续 **3610.847s**，52次正式FORCE，207个正式真实GPU speech job。False degradation事件0，浏览器LIGHTWEIGHT_AVATAR展示帧0；GPU Worker同一PID/epoch/cache全程未重新加载。误降级修复经完整一小时验证。

但整体商业集成仍 **BLOCKED — AV SYNC / MEDIA / WORKER**：浏览器原生轨道录像P95 155.0625ms超过150ms，3个高可信窗口>250ms；原生音频PTS空洞尚未解释。正常Stop/Cleanup已完成，没有重启第二轮一小时。详见 `SOULX-FINAL-ONE-HOUR-ACCEPTANCE.md`。

## 主Hour结束后的独立故障降级回归

GPU Worker保持关闭，独立CPU回归Session `session_e98404a4fb4728cd521b339c6ae85296`（78.024s，正式Hour计时0s）完成真实COMMENT→DeepSeek→XiaoYa→Lightweight Avatar；捕获UTTERANCE_COMPLETED。WebRTC decoded1808帧、audio packets3633，掉帧/丢包0；实验RTMP publisher ready，独立8秒接收录像可解码198视频帧、375音频帧。APIStop至ENDED、activeSessions0、RTMP publisher消失、仅此回归Runtime/Backend清理完毕。没有重启GPU或第二轮一小时。此前准备阶段完成事件缺口已补齐。证据：fallback-postcheck-summary.json及fallback-postcheck/。
