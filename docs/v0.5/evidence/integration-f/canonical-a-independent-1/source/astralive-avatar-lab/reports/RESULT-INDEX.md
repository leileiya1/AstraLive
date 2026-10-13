最新：2026-10-09 新实例重试 `BLOCKED — LATENCY`，见 [SOULX-LIVE-RETRY-2026-10-09.md](SOULX-LIVE-RETRY-2026-10-09.md)。阶段C未完成，Worker已停止。

# 实验结果索引

设备：RTX 4090 D 24GB。以下模型视频来自本次实际 GPU 推理；A/B是对应输出的副本，四段拼接是离线预览，不计为额外推理。输入目录另有官方源视频，环境报告另有CPU编码测试片，均不冒充模型结果。主目录 `astralive-avatar-lab`；云端 `/root/autodl-tmp/astralive-avatar-lab`；备份 `school-linux:~/AstraLive/experiments/real-avatar/results/rtx4090d-2026-10-08/`。

## MuseTalk 1.5

| 实验 | 实际 MP4 | 时长 |
|---|---|---:|
| 官方 Normal | [baseline.mp4](../outputs/musetalk/baseline.mp4) | 22.48 秒 |
| 中文短句 | [musetalk-short.mp4](../outputs/musetalk/musetalk-short.mp4) | 10 秒 |
| 中文中句 | [musetalk-medium.mp4](../outputs/musetalk/musetalk-medium.mp4) | 30 秒 |
| 中文长句 | [musetalk-long.mp4](../outputs/musetalk/musetalk-long.mp4) | 60 秒 |
| 连续 Audio A | [continuous-1.mp4](../outputs/musetalk/continuous-1.mp4) | 10 秒 |
| 连续 Audio B | [continuous-2.mp4](../outputs/musetalk/continuous-2.mp4) | 10 秒 |
| 连续 Audio C | [continuous-3.mp4](../outputs/musetalk/continuous-3.mp4) | 10 秒 |
| 第一次静音待机 | [idle-silence-1.mp4](../outputs/musetalk/idle-silence-1.mp4) | 10 秒 |
| 第一次转为说话 | [talking-after-idle-1.mp4](../outputs/musetalk/talking-after-idle-1.mp4) | 10 秒 |
| 第二次静音待机 | [idle-silence-2.mp4](../outputs/musetalk/idle-silence-2.mp4) | 10 秒 |
| 第二次转为说话 | [talking-after-idle-2.mp4](../outputs/musetalk/talking-after-idle-2.mp4) | 10 秒 |
| 同源官方 Girl 图片 | [musetalk-same-source.mp4](../outputs/musetalk/musetalk-same-source.mp4) | 10 秒 |
| 四段待机/说话拼接预览 | [idle-talking-sequence.mp4](../outputs/musetalk/idle-talking-sequence.mp4) | 约40秒；仅离线预览 |

600 秒持续推理没有以完整播放文件代替 GPU 工作；证据为 [musetalk.json](../benchmarks/musetalk.json)、[逐秒消费记录](../benchmarks/musetalk-soak-timeline.csv)、[GPU 采样](../benchmarks/gpu-metrics.csv)。完整媒体验证见 media-quality-check.json。

## SoulX Lite

| 实验 | 实际 MP4 | 时长 |
|---|---|---:|
| 官方 Streaming 示例 | [baseline.mp4](../outputs/soulx/baseline.mp4) | 65.92秒 |
| 中文短句 | [soulx-short.mp4](../outputs/soulx/soulx-short.mp4) | 10秒 |
| 中文中句 | [soulx-medium.mp4](../outputs/soulx/soulx-medium.mp4) | 30秒 |
| 中文长句 | [soulx-long.mp4](../outputs/soulx/soulx-long.mp4) | 60秒 |
| 600秒真实推理：0–10秒 | [soulx-soak-start.mp4](../outputs/soulx/soulx-soak-start.mp4) | 10秒 |
| 600秒真实推理：295–305秒 | [soulx-soak-middle.mp4](../outputs/soulx/soulx-soak-middle.mp4) | 10秒 |
| 600秒真实推理：590–600秒 | [soulx-soak-end.mp4](../outputs/soulx/soulx-soak-end.mp4) | 10秒 |

[SoulX实测](SOULX-REAL-TEST.md)、[soulx.json](../benchmarks/soulx.json)、[逐秒消费记录](../benchmarks/soulx-soak-timeline.csv)。同进程600.319秒真实生成15,000帧，零丢帧/超40ms迟到。

## 同源A/B与人工选择

[A-short.mp4](../outputs/comparison/A-short.mp4)、[B-short.mp4](../outputs/comparison/B-short.mp4)，均10秒、相同图片/中文音频。用户已选择B“最自然好看”，并接受SoulX的60秒与600秒末段。最终Verdict：READY — SOULX LITE ONLY；不填写Agent主观数值评分。

[模型比较](MODEL-QUALITY-COMPARISON.md)、[最终建议与十三项回答](FINAL-RECOMMENDATION.md)、[人工反馈记录](visual-acceptance.json)。

## 解释与边界

- [环境审计](GPU-ENVIRONMENT-AUDIT.md)、[依赖与修复](GPU-DEPENDENCY-REPORT.md)。
- [MuseTalk 实测](MUSETALK-REAL-TEST.md)、[Worker 接口设计](GPU-WORKER-DESIGN.md)。
- 用户已接受SoulX短片、60秒片与600秒末段的自然度；未填写数值评分，MuseTalk其他动态细节仍待人工评价。封装 25 FPS 不代表推理速度。
- Sun 来源为官方示例，但未证实是真人拍摄；素材仅研究使用。不同人物不能用于公平审美优劣评分。
- 接入生产、真实流式 TTS 首帧、网络 A/V 同步、FORCE 和故障降级尚未验收。正式服务未修改。
