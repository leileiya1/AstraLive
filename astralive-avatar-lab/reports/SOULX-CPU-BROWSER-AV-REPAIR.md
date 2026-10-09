# SoulX 浏览器音画同步 CPU 修复报告

日期：2026-10-09。范围：用户明确要求 GPU 暂不续租，先完成 CPU 浏览器定位与修复。本轮没有连接、启动或重建租赁 GPU。

CPU 浏览器修复验证通过。历史完整 3610.8471 秒测试的最终 Verdict 仍为 **BLOCKED — AV SYNC / MEDIA / WORKER**；不能用本轮短时合成媒体实验替代真实 SoulX 一小时验收。

## 已确认的原因与证据

剩余异常包含真实的浏览器音频输出停顿，并非只有 Canvas/MediaRecorder 拼接误差。上一小时测试中，Mac 系统默认音频输出从内置扬声器切换到蓝牙设备：

- 10:13:57.562657 +0800：CoreAudio 默认输出切换至蓝牙。
- 10:13:57.598826：内置扬声器 StopIO。
- 10:13:57.618054 → 10:13:59.110188：Chrome helper 的蓝牙音频 StartIO，耗时 **1492.134ms**。
- 同一 Mac 上 Browser stats 的 epoch timestamp 对齐到约 T+828.38/829.38；每秒仍收到 50/45 个音频包、视频继续解码约 25FPS，但实际音频播放时长只推进 0.4/0.03 秒。之后播放估计最大偏差 1611ms，音频录像 PTS 空洞 1.567 秒，视频逐步追赶约 20 秒。
- 原验收三个高置信度 >250ms 录像窗口位于视频 PTS 846.924、855.759、857.36 秒，分别 325.1875、315.875、276.875ms，均在该音频输出停顿后的时钟追赶阶段。对应 school 消费差只有 19.568/20.563/20.010ms。

时间比较使用同一 Mac 的浏览器 timestamp 与 CoreAudio 日志；没有直接相减 school/GPU/Mac 的未经校准 Wall Clock。原始上游 source sample、消费 PTS 与历史 RTMP P95 40.0625ms 保持原样。

08:39:00.331988 的原始 436 秒失败期间也有一次默认输出转蓝牙。Chrome helper 的蓝牙 StartIO 持续约 **711.103ms**，与此前 AudioContext 时钟亏欠约 584ms、录像约 600ms 的机制相符。但旧 browser 数据缺少精确 Mac wall anchor，因此该次事件的逐窗口关联是佐证，不能宣称已精确证明两个 source sample 的因果时间关系。

音频输出驱动停顿时，网络与视频解码继续；音频渲染随后恢复，浏览器接收、播放与录制时钟经历积压/追赶。不能通过为音频统一增加 600ms 延迟修复该问题，也没有证据要求更换 SoulX 模型路线。后者是依据上下游对比与 CPU 重现作出的工程判断，仍需真实链路复验。

安全证据：`streaming/integration/soulx-cpu-av-repair-20261009/coreaudio-route-change-redacted.json`、`coreaudio-original-route-redacted.json`、`native-audio-gap-timeline.json`、`native-video-gap-timeline.json`。完整系统日志只保存在开发机，备份只含去除设备 MAC/哈希的相关事件。

## 独立 CPU 重现与失败尝试

真实 Chrome 154 与 aiortc 1.15，CPU 发送带唯一 source sample 标记的实时音视频：16k PCM、48k Opus、90k video RTP、25FPS。数据不是提前录好的 SoulX 输出；不含 LLM/TTS/GPU 业务验收。

仅暂停**本实验 Chrome 子进程**的 AudioService 1.6 秒，随后 SIGCONT；未改变系统默认音频输出、未暂停用户 Chrome、未注入网络/GPU故障。

| CPU 实验 | 原生轨道录像 P95 / Max | 结果 |
|---|---:|---|
| 未修复，音频服务暂停 | 309.43 / 807ms | 重现异常，保留 1.599 秒 PTS 空洞 |
| 恢复后仅重新绑定媒体元素 | 约 778 / 1018ms | 无效，不能清除接收播放积压 |
| 音频设备尚未恢复时立即新建 Peer | 517.63 / 517.63ms | 无效，新连接也处于输出停顿 |
| 等实际音频推进后再新建 Peer，实验控制器 | 45.88 / 45.88ms | 新连接恢复，原故障段仍保留 |
| 最终固定输出，120 秒 | **59.06 / 92.63ms** | 246 个可信窗口，无音频 PTS 空洞 |
| 实际产品预览 Hook，故障后新连接 | **25.63 / 49.63ms** | 35 个可信窗口，无新 PTS 空洞 |

所有失败尝试、原始录像与每个相关性窗口均保存；没有修改 `.7` 的原有可信相关性阈值。120 秒固定输出实验：原生元素 captureStream 亦为 59.06/92.63ms；Canvas+原生音轨为 50.81/87.63ms。

实际产品 Hook 实验持续 70 秒。第一次与第二次 offer 都使用 `cpu-persistent-source-session`，源时钟连续，没有创建、Start 或 Stop 新业务 Session。故障请求 T=16.692 秒，检测并进入 recovering T=17.4998 秒，音频恢复后开始新协商 T=18.7615，connected T=20.1598。恢复时间约 3.47 秒，包含人为音频停顿和重新协商。旧连接录像保留 1.605 秒空洞，故障整段**不标为稳定播放 PASS**。

第二连接独立 getStats 覆盖约 51.20 秒：原生播放估计 242 个有效样本，median/P95/max = **11/33/38ms**；最终视频解码 1283 帧，音视频丢包 0、视频掉帧 0。固定输出 120 秒的播放估计为 9/30.25/76ms。`estimatedPlayoutTimestamp` 是浏览器估计，并非物理扬声器回录传感器；分别报告录像与播放估计，不能互换。

恢复录像共 107 个可测窗口，其中 35 个达到原 `.7` 可信阈值，其他 72 个全部保留。末尾一个低置信度候选给出 617.19ms，但 correlation 仅 .077（竞争峰 .070）；该 source window 需要音频至 51.482 秒，而录像音频在 51.359 秒结束，完整参考不可用。它没有唯一同步锚点，不能认定真实失步。该样本没有删除；结合完整文件边界、无新 PTS 空洞及独立播放估计 max38ms记录局限。其他低置信度样本也未冒充可信验收样本。

初次产品 Hook 实验确实建立第二 Peer，但 Recorder 在旧轨道自然结束后漏等 onstop，导致监控卡住；保存为 `final-product-hook-fault-recovery`。修正事件等待后重新进行 70 秒 CPU 实验，最终有效证据为 `final-product-hook-fault-recovery-fixed-recorder`。不能将前一实验当作恢复通过证据。

## 实际修复

1. `frontend/src/lib/previewAudioHealth.ts`：统一原生播放健康检测与具体音频输出选择。检测依赖 `media-playout.totalSamplesDuration`；收到 RTP 不能冒充实际音频播放。健康音视频接收但播放持续停顿 ≥600ms 时报告故障；连续两个实际播放推进采样后才允许重建连接。计数器重置重新初始化时钟。
2. `frontend/src/hooks/useLivePreview.ts`：每250ms检查未静音且正在播放的预览。等输出恢复后，只重新协商同一 Session 的 WebRTC 预览；关闭旧 Peer，拒绝旧异步 ontrack，清理监听与定时器。8秒未恢复显示错误，自动恢复最多每分钟两次，避免反复重连。支持手动重新连接预览。没有调用业务 Stop/Start。
3. `frontend/src/features/live-console/LiveConsole.tsx`：支持的浏览器提供用户主动“音频输出”选择；预览失败提供重新连接入口。没有修改操作系统默认音频输出，没有自动打开麦克风。
4. `streaming/browser_audio_health.js` 由上述 TypeScript 生成，避免测试 Harness 与产品分别维护不同算法；构建入口 `build_browser_audio_tools.py`。
5. `browser_audio_policy.py`、`cpu_cdp.py`：隔离测试 profile，只授予 `speaker-selection`；CDP连接保持至结束，因为提前断开会撤销临时权限。等待页面 origin 提交和权限 barrier。最终120秒实验确认麦克风权限仍为 `prompt`，没有麦克风采集。
6. `browser_final_acceptance.py/html`：正式计时前固定**具体内置输出 deviceId**，拒绝 `default`/`communications` 别名及未授权/不可用输出；250ms监视真实音频播放停顿。正式一小时中发生该故障将走正常Stop并保存失败，**不会用自动重连伪装同一连接稳定一小时**。Recorder 从开始时持有 onstop Promise，避免自然结束后无限等待。强制显式配置续租后的GPU目标/证据目录及school监控路径，拒绝覆盖历史录像。
7. `cpu_browser_sync.py/html`、`cpu_product_preview.tsx/html`、`analyze_cpu_browser_sync.py`：真实 Chrome、可重复故障、实际 Hook 适配与全窗口分析；不启动业务付费服务。

未改模型、权重、采样、24帧分块、960ms窗口、GPU算法、正式Runtime/WebRTC/RTMP核心、Frozen Public Contract 或生产Avatar默认Provider。

## 验证与运行方式

最终验证：Frontend 27/27，浏览器健康/输出选择 12/12，现有 Runtime 真 aiortc WebRTC 集成 4/4；TypeScript、Vite生产构建、Python编译检查通过。Runtime集成覆盖连续输出的重新连接、陈旧Peer、HTTP协商与Stop；这是CPU集成证据，不能说本轮验证了真实Go/LLM/TTS/SoulX业务恢复。

```sh
python3 astralive-avatar-lab/streaming/build_browser_audio_tools.py
node astralive-avatar-lab/streaming/test_browser_audio_health.js
RUN_WEBRTC_INTEGRATION=1 PYTHONPATH=runtime runtime/.venv/bin/python -m unittest runtime.tests.test_webrtc_media_integration
runtime/.venv/bin/python astralive-avatar-lab/streaming/cpu_browser_sync.py --name NEW_UNIQUE_CASE --duration 70 --pin --fault --product-hook
runtime/.venv/bin/python astralive-avatar-lab/streaming/analyze_cpu_browser_sync.py NEW_UNIQUE_CASE
```

下一次正式驱动需要显式 `SOULX_GPU_SSH_TARGET`、`SOULX_GPU_SSH_PORT`、`SOULX_GPU_EVIDENCE_DIR`、`SOULX_SCHOOL_MONITOR_PATH`（绝对路径），以及独立 `SOULX_FINAL_RUN_DIR`。本轮仅编译检查该完整验收脚本，未运行它、未联系租赁GPU。重新租赁后仍须按全链路ready再计时、同一次3600秒及六检查点完成真实复验。

## 限制与成果

- 固定内置/有线音频设备可以避免跟随系统默认输出跳转；物理设备故障、蓝牙固有传输延迟与断连不能靠软件保证“零停顿”。恢复会损失一段本地预览，已量化，不能包装成稳定播放。
- `selectAudioOutput` 浏览器支持不同，不支持时不显示选择入口；自动健康检测也要求浏览器提供真实 playout 统计。验收环境会明确拒绝不可用的固定输出，生产跨浏览器覆盖尚未验证。
- 没有进行真实蓝牙拔插复验，避免影响用户音频设备；历史系统日志、默认设备选择单元测试与隔离 AudioService 故障验证了机制与恢复，不能扩展成所有蓝牙驱动均通过。
- 本轮没有新的RTMP录像；历史P95 40.06ms结果保留。GPU/真实LLM/TTS/Generation/FORCE/完整一小时指标没有重新测量。
- 源代码已修改并通过本地构建，未切换生产服务或生产默认Provider。
- 所有实验Chrome与CPU驱动已退出，`cleanup.json` 显示无所属残留进程。GPU无需为CPU分析保持运行；本轮没有续租、删除或关闭任何云实例。

新证据目录 `streaming/integration/soulx-cpu-av-repair-20261009/`，最终机器可读摘要 `final-summary.json`。与旧433文件SHA包分开备份；新包不包含Chrome profile、系统原始日志、设备标识、密钥或敏感环境变量。

技术依据：[W3C Audio Output Devices API](https://w3c.github.io/mediacapture-output/)（具体sink与默认设备语义）、[W3C WebRTC Stats](https://www.w3.org/TR/webrtc-stats/#dom-rtcinboundrtpstreamstats-estimatedplayouttimestamp)（播放估计含义）、[Chromium WebRTC audio renderer](https://chromium.googlesource.com/chromium/src/+/0b85fca82f6d5506a9cc9cfcaa1d746aa9b4ef66/third_party/blink/renderer/modules/webrtc/webrtc_audio_renderer.cc)（音频渲染回调路径）。根因结论由本项目同机日志与重现实验支持，不是仅凭文档推测。
