# SoulX Lite 最后一次音画同步专项验收 — 2026-10-09

音画同步专项结论：**PASS，用户决定按当前音画效果验收并结束，不再重跑。**

按最初“真实 LLM 全业务成功”的完整门槛，Verdict 保留为 **BLOCKED — AV SYNC / MEDIA / WORKER**。实际阻塞项是后约5分钟的 LLM 鉴权失败，不是音画同步或 GPU Worker 崩溃。不能把专项通过写成所有商用发布条件已通过。

## 本次连续测试

- Session `session_547dd29bbc9a0d079db15cc4643214b7`，同一 Chrome Peer/Worker epoch，ready 后连续 **3600.781 秒**，191业务循环、63次正式FORCE。
- 真正链路：Go Backend → DeepSeek（后期部分失败降级）→ XiaoYa真实TTS →16k PCM → RTX4090D SoulX Lite实时增量推理 → school-linux Fanout → Mac Chrome原生WebRTC及实验RTMP。
- 没有重复90秒/5分钟Session，没有重跑第二小时，没有使用预生成MP4或重复音频冒充实时推理。原436秒失败及上一轮155.06ms证据完整保留。
- Python3.12.3、Torch2.8.0+cu128、CUDA12.8、FlashAttention2.8.3。新实例数据盘为空，仅恢复缺失依赖/权重；既有Torch/CUDA复用，7个权重文件依照既有Manifest逐一SHA256通过。
- Worker PID2892、epoch `0dad0b4e1e38442c854c1c449db61ab6`；模型只加载1次。Runtime3832328/Backend3832332/BrowserDriver58252，均脱离临时SSH生命周期。

## 同步结果和测量边界

| 路径 | 正式窗口数 | Median / P95 / Max 绝对偏差 ms | 可信 >250ms |
|---|---:|---|---:|
| Chrome原生播放时间估计 | 3600 | 5 / 30 / 65 | 0 |
| 原生收到AV tracks的浏览器录像 | 3386 | 16.81 / **44.00** / 79.75 | 0 |
| Canvas + 原生audio track诊断录像 | 3410 | 18.81 / 49.00 / 79.00 | 0 |
| RTMP接收录像 | 444 | 39.94 / **40.00** / 44.06 | 0 |

包括正式计时前准备片段，浏览器原生录像最大120.625ms、P95仍44ms；RTMP全录像P95约40ms。三份录像完整解码分析，audio PTS gap为0；无再次出现可信500–600ms偏差，无持续累积漂移。

同步使用相同job/source sample与嵌入的视频sequence标记；480ms精确源PCM参考，按独立的消费/配对cadence重建underflow窗口。阈值沿用correlation>=0.7，所有3588/3584/3586测量窗口及未可信窗口保留在cadence-aware-sync.json，未删除离群点。RTMP可信窗口数低于浏览器，不能声称每一个播放时刻都有独立高置信锚点。原生播放是Chrome receiver estimatedPlayoutTimestamp差值和播放健康/设备固定证据；不是物理扬声器回录。跨主机只使用已测RTT13ms的校准映射，不直接相减Wall Clock。

此前paired轮浏览器正式录像P95 **155.0625ms**、max325.1875ms；本轮44/79.75ms。此前RTMPP9540.0625ms，本轮40ms。原600ms根因强证据指向Mac CoreAudio设备切换/音频服务启动阻塞；原436秒资料缺少精确墙钟锚点，不能声称每一个原始600ms样本均已逐一证明。CPU设备阻塞复现、实际输出路由日志及本轮固定设备对照支持修复有效，未给音频添加固定600ms延迟。

## 六个同Session检查点

| 检查点 | 实际时长 | 原生估计 P95 ms | 浏览器录像 P95 ms | RTMP P95 ms | 音画Gate |
|---|---:|---:|---:|---:|---|
| 90s | 90.004s | 33.00 | 105.62 | 40.00 | PASS |
| 5m | 300.003s | 45.00 | 70.66 | 40.00 | PASS |
| 15m | 900.003s | 32.00 | 47.56 | 40.00 | PASS |
| 30m | 1800.004s | 31.00 | 45.00 | 40.00 | PASS |
| 45m | 2700.003s | 30.00 | 44.00 | 40.00 | PASS |
| 60m | 3600.781s | 30.00 | 44.00 | 40.00 | PASS |

60分钟检查点的在线CPU录像审计与Stop存在Harness并发结束竞争：`gateBusy`直接返回使driver先结束。此点**依据同一Session在3600.781秒保存的finalStats、最后30秒周期监控及完整录像离线恢复**，标记`recoveredOfflineFromSameContinuousSession=true`，没有拼接时长/新建Session。前五点为在线自动Gate。后续Harness已修复为等待同一个pending gate Promise；没有用修改后的Harness重跑或改写本次原始结果。

## GPU有效生成、首帧和资源

- GPU实际生成72168帧，纯模型计算FPS94.61（含CUDA同步、排除之后CPU RGBreadback），特征+推理87.16FPS。
- 真正发布并在school消费的新GPU帧66467，整个正式小时平均 **18.46新帧/s**；浏览器认证唯一新源帧66307、18.41/s。
- 浏览器解码 **25.00FPS**，不可与新GPU帧率混淆。20947次已认证GPU保持帧、2585缓存Idle展示单独统计。164条未能通过消费事件认证的原始marker展示记录保留，不计入GPU新帧统计。
- FirstPCM→school首GPU帧 median/P95/max641.17/839.85/1227.76ms；→Chrome原生回调1036.39/1234.94/1611.71ms。这是流式首帧延迟，不是音画偏差，也不包括LLM首token前等待。
- Runtime RSS起始81.23MiB/峰值776.77MiB/末765.73MiB，采样CPU峰45.3%。VRAM allocated峰4.33GiB、reserved峰5.34GiB，GPU采样util峰98%、温度峰58℃。
- Runtime队列有界，未出现无界增长；FFmpeg reconnect0、writeFailure0，独立进程持续运行。Idle真实视觉抽查人物连续、无黑帧/身份跳变；没有开展新模型评比，也没有额外量化自然度评分。

## FORCE、安全和丢包

63次正式FORCE、模型加载1次、Worker取消与旧计算结果拒绝有记录；Canvas新到达旧代际展示泄漏0，真实轻量Avatar展示0、Avatar degradation0。学校拒绝旧Worker帧497（全连接范围），不是异常包被隐去。

原生解码器中请求FORCE后仍可见旧的在途画面，最长551.4ms；该指标包含请求到Backend切换及解码缓冲，**不是音画偏差**，不应宣称整个系统零旧画面。RTMP已编码/传输中缓冲同样不能仅凭Canvas回调证明零残留；本轮未单独给每个RTMP FORCE做像素级切换上界验收，保留此限制。

连接全程connected；最终接收729739包、累计丢22包（audio5/video17），约 **0.0030%**，正式时段丢包增量18。Chrome解码掉帧0、freezeCount0、pauseCount0；音频concealedSamples12402/174430080，约0.0071%，不是宣称零音频损失。少量丢包未造成本轮同步失败或长音频中断；本项目验收关注实际播放质量，零丢包不是强制门槛。指标定义参见[W3C WebRTC Stats](https://www.w3.org/TR/webrtc-stats/)。

## LLM鉴权缺口与用户决定

Redis全量事件1576条：257 queued/generating/synthesizing/rendering/playing、193 completed、64 interrupted（含准备阶段）；28个LLM_FAILED/HTTPStatusError。首个warning为08:03:04.513Z、最后08:07:43.756Z，发生在末约5分钟；不能把整小时都说成未用真实LLM。

正常完成事件可能来自既有输入文本降级，因此`UTTERANCE_COMPLETED`不足以证明真实LLM成功。停止后同一旧Key在school与Mac均返回**401 authentication_error**；本机与运行时Key相同、没有被backend.env覆盖。用户提供的新Key独立CPU请求HTTP200，有真实回复与usage记录，安全存放于本机0600实验私有文件，不入报告/备份。

401不是并发超限的证据；官方将并发超限对应为429，不能推断被高并发封号、余额不足或永久冻结。失效时间/原因需要账号侧证据。参见[DeepSeek错误码](https://api-docs.deepseek.com/quick_start/error_codes/)及[并发说明](https://api-docs.deepseek.com/quick_start/rate_limit/)。

本轮遗漏是Harness没有将LLM_FAILED warning作为立即停止Gate，末5分钟未及时停止。已在实验Harness增加真实streaming LLM CPU预检、每条业务事件保留、关键warning立即阻塞；10条ready基线及5条业务Gate检查通过，最终JS语法检查通过，中间错误稿保留。新Key尚未完成新的真实全链路小时；用户明确选择不重跑并接受音画同步专项结果。本报告不虚报完整原始商业全链路PASS。

## 修改与回归

保持此前Mac输出设备固定、播放健康检测、前端WebRTC恢复和实验RTMP配对时钟；不修改SoulX网络、权重、24帧/960ms窗口、神经采样参数、冻结协议或正式默认Provider。

本轮实验文件：`worker_final.py`、`start_final_stack.py`、`final_host_monitor.py`、`final_rtmp_reader.py`、`final_gpu_monitor.py`、`browser_final_acceptance.py/.html`、`checkpoint_av_gate.py`、`final_metrics.py`、`runtime-experiment/app/events.py`（恢复此前已验证实验配置）。收尾补强：`preflight_llm.py`、`final_player_gate.js`。

正式开始前：31流式/代际/降级/PTS回归、5GPU Adapter、Runtime79测试中7skip、Frontend27、BrowserHealth12、PlayerGate10均PASS；实际配对FFmpeg30帧max0.375ms。初始Mac缺Torch/导入路径错误保留并在正确环境重测；未修改断言。未在主Soak主动断GPU。此前真实Lightweight fallback复验78秒、Session正常ENDED证据沿用，未重复故障实验。

计时前另有Redis stream部署配置错误导致PREPARING无法开始：消费旧stream中的真实READY事件后，通过正式API正常Stop，再恢复已验证的events.py配置；没有伪造READY事件或将准备耗时计入小时，准备失败证据单独保留。

## Stop、备份、关机与部署复用

公开API正常LIVE→STOPPING→ENDED；Runtime activeSessions0、会话队列移除，Worker `ConnectionCleaned.sender_stopped=true`，FFmpeg publisher/reader退出。确认后清理仅本次Runtime/Backend/测试MediaMTX；无剩余受控进程。Worker SIGTERM后显存0MiB。清理没有替代正式Stop。

已按用户明确授权调用AutoDL官方`/usr/bin/shutdown`，SSH由远端关闭，后续连接不可用；没有删除实例。未登录控制台查询电源/账单状态，需用户确认显示“已关机”。官方[关机方法](https://www.autodl.com/docs/save_money/)与[计费说明](https://api.autodl.com/docs/price/)分别说明CLI关机与开关机算力计费；磁盘等额外费用按实例配置另算。

证据：`streaming/integration/soulx-final-one-hour-pinned-20261009/`；Mac备份：`backups/soulx-final-one-hour-pinned-20261009/`；school备份：`~/AstraLive/experiments/real-avatar/results/soulx-final-one-hour-pinned-20261009/`。包含报告、原始JSON/日志、三份完整录像、版本锁、Worker实现、权重SHA清单；排除SSH私钥、APIKey、private目录、Chrome profile，并对备份文本中的实验Stream Key脱敏。最终校验receipt为`backup-verification.json`。

同一实例关机/开机复用数据盘权重和venv，不必每次安装下载；新空机器首次必须预置权重。用预装镜像/持久模型目录实现一次配置、日常一条命令启动，详见`SOULX-DEPLOYMENT-REUSE.md`。没有自动创建额外收费实例/镜像构建任务，没有要求把模型权重备份到Mac。

## 最终结论

用户要求的**音画同步专项通过**，本次停止且不重跑。原始完整商业全链路门槛保留鉴权失败缺口，严格Verdict为**BLOCKED — AV SYNC / MEDIA / WORKER**（BUSINESS/LLM凭据问题）。专项通过不等同正式平台上线批准；没有切换正式默认Avatar Provider。
