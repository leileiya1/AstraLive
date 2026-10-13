# AstraLive Python AI Runtime

## Mock 启动

```bash
cd runtime
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
MOCK_LLM=true MOCK_TTS=true MOCK_AVATAR=true MOCK_MEDIA=true uvicorn app.main:app --host 127.0.0.1 --port 8001
```

默认四个 Mock 开关均为 `true`，不会 import PyTorch 或初始化 CUDA。未设置 `REDIS_URL` 时事件保存在进程内，用于本地开发；设置 `REDIS_URL` 后使用 Redis Stream `dh.runtime.events.v1`，每条 Stream entry 的 `event` 字段是完整 JSON Envelope。运行正式跨服务链路时必须设置 `REDIS_URL`。

内部 API 仅供 Go Control Plane 调用，应在部署网络层限制 `/internal/v1/**` 的访问。Swagger 文档位于 `/docs`，接口以 `contracts/runtime-api.openapi.yaml` 为准。

可选配置：`MAX_SESSIONS`（默认 8）、`MAX_SPEECH_QUEUE`（默认 100）、`TOOL_BASE_URL`、`TOOL_TOKEN`。
Contract v1.1 要求创建 Session 时提供 `context.roomId` 和 `context.systemPrompt`，讲话请求提供 `source`。`context.activeProductId` 可选，商品动态事实仅通过 `TOOL_BASE_URL` 指向的 Go Tool API 查询；未配置或调用失败时会降级播报并发 `RUNTIME_WARNING`。

## 逐项开启真实 Provider

| 开关 | 实现 | 额外配置 |
| --- | --- | --- |
| `MOCK_LLM=false` | OpenAI 兼容 Chat Completions 流 | `LLM_BASE_URL`、`LLM_API_KEY`、`LLM_MODEL`、可选 `LLM_MAX_TOKENS` |
| `MOCK_TTS=false` | sherpa-onnx 中文 VITS 逐块 PCM | `TTS_MODEL_DIR`、可选 `TTS_SPEAKER_ID`、`TTS_NUM_THREADS` |
| `MOCK_AVATAR=false` | 2D 音频驱动口型与 RGB 帧 | 可选 `AVATAR_IMAGE_PATH`；不设置时使用内置示例脸 |
| `MOCK_MEDIA=false` | aiortc 音视频轨道 | Go 调用 `POST /internal/v1/sessions/{sessionId}/webrtc/offer` 交换完整 SDP |

## RTMP Live Output

RTMP 是独立的 `MediaOutput` Sink，可与 WebRTC 同时运行，也可通过 `WEBRTC_ENABLED=false` 单独运行。启用时 Runtime 使用 system FFmpeg、匿名管道和内存有界队列；不使用 OBS、浏览器中继、物理声卡或临时 raw 文件。

```bash
export MOCK_MEDIA=false WEBRTC_ENABLED=true RTMP_ENABLED=true
export RTMP_URL=rtmp://127.0.0.1:1935/live
export RTMP_STREAM_KEY=astralive-test
export RTMP_WIDTH=720 RTMP_HEIGHT=1280 RTMP_FPS=25
export RTMP_VIDEO_BITRATE=3000k RTMP_AUDIO_BITRATE=128k
export RTMP_AUDIO_SAMPLE_RATE=48000 RTMP_PRESET=veryfast
export RTMP_VIDEO_BUFFER_MS=400 RTMP_AUDIO_BUFFER_MS=400
```

`RTMP_URL` 与 `RTMP_STREAM_KEY` 只在内存中组合。日志仅允许出现 `rtmp://host/app/***`。输出固定为 H.264/yuv420p 与 AAC/48 kHz stereo；输入 Avatar frame 会保持宽高比并居中补黑边。无新视频时重复最后一帧，无视频时输出黑帧；无 TTS 时持续输出静音。

真实 LLM 的密钥只放在环境变量中。示例 DeepSeek 配置：`LLM_BASE_URL=https://api.deepseek.com`、`LLM_MODEL=deepseek-flash`，将自己的密钥注入 `LLM_API_KEY`。真实 TTS 及后续阶段使用：

```bash
cd runtime
python3 scripts/download_tts_model.py
pip install -r requirements-real-media.txt
export TTS_MODEL_DIR="$(pwd)/.local/vits-piper-zh_CN-xiao_ya-medium"
```

模型下载脚本会核对 SHA-256。当前小雅音色的模型卡注明训练数据仅限非商业用途，因此此音色只用于开发验证；商业发布前需替换为已确认许可的模型。Runtime 不把任何模型权重或 `.venv` 纳入源码。

完整链路可依次设置四个 `MOCK_*` 为 `false`，每次只切换一个并运行下面的相应测试。`MOCK_MEDIA=false` 提供实际 WebRTC 音视频轨道；即使其他 Provider 保持 Mock，也不需要 GPU。Browser 需先完成本地 ICE gathering，再经 Go 转发 SDP offer；Runtime 返回完整 answer。媒体由 Browser 与 Runtime 直传，部署时须保证 Runtime ICE candidate 可达。

## 测试

```bash
PYTHONPATH=runtime python3 -m unittest discover -s runtime/tests -v
```

这条测试命令在仓库根目录执行。

测试覆盖 Session 生命周期、优先队列、打断策略、旧 generation 音频丢弃、Mock 流、LLM 故障 fallback、Redis 序列化和 Internal API 主要响应形状。

真实 Provider 测试使用 `runtime/.venv/bin/python` 与 `PYTHONPATH=runtime`（从仓库根目录执行），依次打开：

```text
RUN_REAL_LLM_INTEGRATION=1       test_real_llm_integration.py
RUN_REAL_TTS_INTEGRATION=1       test_real_tts_integration.py
RUN_REAL_AVATAR_INTEGRATION=1    test_lightweight_avatar_integration.py
RUN_WEBRTC_INTEGRATION=1         test_webrtc_media_integration.py
RUN_FULL_REAL_CHAIN=1           test_full_real_chain_integration.py
```

相关测试分别需要 `LLM_*` 和/或 `TTS_MODEL_DIR`。RTX 2060 主机测试脚本为 `tests/rtx2060_smoke.py`。完整阶段结果见 `REAL-AI-REPORT.md`。

## 接口与扩展点

- `app.session.SessionManager` 管理进程内 Session；Go 保持业务状态所有权。
- `app.providers` 定义 LLM、TTS、Avatar、Media 接口及 Mock 实现。真实 Provider 通过 `create_app(..., factories=...)` 注入。
- `app.events` 定义统一事件 Envelope、内存及 Redis Publisher。
- `app.tools.ToolClient` 使用 Go Internal Tool API 获取商品、库存和价格。
- `POST /internal/v1/sessions/{sessionId}/webrtc/offer` 调用当前 Session 的 `MediaOutput.create_answer()`；MockMediaOutput 不生成 WebRTC Peer。
