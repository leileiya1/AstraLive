# AstraLive Real AI Phase 报告

日期：2026-10-06。仅修改 `runtime/**`；所有现有 Contract 保持原样。

## 按顺序完成的 Provider 验证

| 阶段 | 实现和测试 | 结果 |
| --- | --- | --- |
| 1. Real LLM | 加强 OpenAI 兼容 SSE 解析、结束/错误检查；DeepSeek `deepseek-flash` + Mock TTS/Avatar/Media 的 Internal API 集成测试 | 通过；不把密钥写入源码 |
| 2. Real TTS | sherpa-onnx 中文 VITS Provider；Mock LLM/Avatar/Media 的 Internal API 集成测试 | 通过；输出 22,050 Hz 单声道 PCM16 |
| 3. Streaming TTS | 真实增量回调、多块 PCM、关闭流后复用、Real LLM + Real TTS 组合测试 | 通过；本机测试句首块约 95–99 ms、总生成约 170–175 ms、3 块；此数字只代表该句和机器 |
| 4. Lightweight Avatar | 音频幅度驱动 2D 口型、RGB 帧、音频时钟 PTS、generation 丢弃；Real LLM + Real TTS + Avatar + Mock Media | 通过；测试帧可见 `.local/avatar-preview.png` |
| 5. RTX 2060 | 在 `ssh ubuntu-server` 的 RTX 2060 6 GiB 主机上运行 Real TTS + Lightweight Avatar + Mock LLM/Media | 通过；56 帧 / 2.273 秒音频 = 24.64 FPS，强制打断及清理通过。GPU 显存前后均 4 MiB，说明这条轻量路径使用 CPU，没有验证 GPU 推理吞吐 |
| 6. WebRTC Media | aiortc 音频/视频轨道；本地真实 peer 接收非静音音频与视频；组合 Real LLM + TTS + Avatar + WebRTC 集成测试 | 通过内部 SDP 交换；浏览器跨服务连接未验证，因为 Contract 缺信令路由 |
| 7. MuseTalk 评估 | 查官方 1.5 权重、硬件与推理说明 | 当前不接入；见下文 |

Mock 基线测试：16 项中 8 项通过、8 项真实模式测试按默认设置跳过。真实阶段分别显式开启对应测试；最终全部开启后 16/16 通过（最后一次测试句的 TTS 首块 72 ms、总生成 148 ms）。仓库现有 `tests.test_contracts` 两项通过。真实 Redis/Go/SSE/React 的新配置未在本阶段重跑全系统 E2E；上述“集成测试”指 Runtime API、真实 Provider 与本地 WebRTC peer 的组合验证。

## 实际限制

1. `WebRTCMediaOutput.create_answer()` 可以完成 offer/answer 并传音视频，但现有 OpenAPI 没有 SDP/ICE 路由。遵守 Contract 不变的要求，本阶段没有新增路由；前端预览仍不能据此直接接通。
2. Lightweight Avatar 是 2D 口型原型，未做真人面部重建，也没有照片级质量；`AVATAR_IMAGE_PATH` 可指定静态图，嘴部位置目前固定。
3. 当前使用的 [小雅模型](https://k2-fsa.github.io/sherpa/onnx/tts/all/Chinese/vits-piper-zh_CN-xiao_ya-medium.html) 的随包 `MODEL_CARD` 标注训练数据为非商业用途。它只适合当前开发验证，商业发布前需要换已确认许可的音色。Sherpa Provider 接口无需因此改变。
4. WebRTC 音频使用基础线性重采样，视频按 25 FPS 排队并在过载时丢旧帧；音画同步仅在本地 peer 验证了收流，尚无浏览器端口型、延迟或 1 小时长稳实测。
5. 当前 Go COMMENT→Runtime 的跨模块输入和浏览器信令仍取决于冻结 Contract；本阶段未改 Backend、Frontend、Integration 或 Contract。

## MuseTalk 决策

[MuseTalk 官方说明](https://github.com/TMElyralab/MuseTalk)给出的 30 FPS 以上数据来自 Tesla V100；其低配示例在 4 GiB RTX 3050 Ti Laptop GPU 上，8 秒视频使用 fp16 约需 5 分钟，不能据此推断 RTX 2060 可实时运行。[MuseTalk 1.5 UNet 权重](https://huggingface.co/TMElyralab/MuseTalk/blob/main/musetalkV15/unet.pth) 单文件约 3.4 GB，[配套 VAE](https://huggingface.co/stabilityai/sd-vae-ft-mse/tree/main) 还需约 335 MB，另有 Whisper、人脸检测/解析权重及环境依赖。RTX 2060 只有 6 GiB 显存，是否达到 25 FPS 必须做缓存预处理后的实测，不能从当前轻量 Avatar 的 24.64 FPS 外推。

因此保留现有 `AvatarEngine` 抽象，暂不下载 MuseTalk 权重或改动 Provider 协议。若进入 MuseTalk 小样验证，先限定单路、固定头像、短音频，分别测预处理耗时、稳定帧率、峰值显存、打断与清理；仅在 2060 上达到目标后再接入 Runtime。模型下载至少约 3.7 GB 主权重，实际总量更高，应先预留下载和环境构建时间。

## RTX 2060 CPU/GPU 头像绘制对照

2026-10-06 在 `ssh ubuntu-server` 的 RTX 2060 上执行 `runtime/tests/gpu_avatar_benchmark.py`：512×512 RGB，250 帧（对应 25 FPS 的 10 秒画面），每项预热后重复 3 次取中位数。GPU 确实通过 PyTorch CUDA 运算。Pillow 项模拟当前 `LightweightAvatarEngine` 的逐帧椭圆嘴型绘制及 RGB 导出；Torch CPU/GPU 项使用完全相同的整数椭圆掩码，其中“含 RGB 回传”包括生成 WebRTC 所需的 CPU 字节数据。

| 路径 | 250 帧耗时 | 说明 |
| --- | ---: | --- |
| 当前 Pillow 风格 CPU | 76.0 ms | 当前轻量引擎最接近的实用基线 |
| Torch CPU，含 RGB 导出 | 574.8 ms | 与下方 GPU 使用相同掩码算法 |
| RTX 2060 CUDA，仅计算 | 11.4 ms | 不含视频帧回传，不能当端到端延迟 |
| RTX 2060 CUDA，含 RGB 回传 | 90.5 ms | 比当前 Pillow CPU 基线约慢 19% |

Torch CPU/GPU 对全部 39 种不同开合值逐像素对比，结果完全一致。PyTorch 报告峰值 CUDA 张量分配约 2.8 MiB（不含 CUDA 上下文及其他显存）。这不是完整 WebRTC 链路压测；这里只比较单路头像的绘制与 RGB 导出。GPU 对相同算法不会自动改善画质，且当前小图逐帧渲染的传输开销抵消了计算收益，因此保留现有 CPU Provider。若想获得真人口型质量，需要换更强的生成模型，并单独测试 RTX 2060 的速度、显存和延迟。

## 清理

RTX 主机测试只使用 `/tmp/astralive-real-ai`，测试后已删除；未更改其现有容器。局部模型和 Python 虚拟环境保留在本机 `runtime/.local`、`runtime/.venv`，并由 `runtime/.gitignore` 排除。
