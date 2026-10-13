# AstraLive — AI Runtime Requirements

> Owner：Runtime Agent  
> 允许修改：`runtime/**`  
> 必须先阅读：Architecture 与 Contracts。

## 1. 角色

AI Runtime 是实时执行引擎。

负责：

```text
Runtime Session
LLM
Tool/RAG
Speech Planning
Sentence Buffer
Streaming TTS
Audio Queue
Avatar Engine
Media Output
Interrupt
Runtime Events
```

不负责：
- 业务数据库
- LiveRoom CRUD
- Product 持久化
- 前端 API
- LiveSession 最终业务状态

---

## 2. 技术栈

```text
Python
FastAPI
Pydantic
asyncio
httpx
redis.asyncio
PyTorch
FFmpeg
WebRTC library
```

Provider：

```text
LLMProvider
TTSProvider
AvatarEngine
MediaOutput
ToolClient
EventPublisher
```

---

## 3. 目录

```text
runtime/
├── AI-RUNTIME.md
├── app/
│   ├── main.py
│   ├── config.py
│   ├── api/
│   ├── session/
│   ├── orchestrator/
│   ├── llm/
│   ├── tts/
│   ├── avatar/
│   ├── media/
│   ├── tools/
│   ├── events/
│   └── common/
└── tests/
```

---

## 4. SessionManager

必须提供：

```text
create_session
start_session
speak
interrupt
stop_session
get_session
```

每个 Runtime Session 至少包含：

```text
session_id
state
generation_id
speech_queue
current_utterance
avatar_engine
tts_provider
media_output
tasks
```

并发安全必须明确。

---

## 5. Runtime State

Runtime 内部状态允许：

```text
CREATED
PREPARING
READY
LIVE
STOPPING
ENDED
FAILED
```

但跨服务必须发 Contracts 定义的事件。

Go 才是最终 Session 状态源。

---

## 6. Runtime API

严格实现：

```text
POST /internal/v1/sessions
POST /internal/v1/sessions/{id}/start
POST /internal/v1/sessions/{id}/utterances
POST /internal/v1/sessions/{id}/interrupt
POST /internal/v1/sessions/{id}/stop
GET  /internal/v1/health
```

长任务返回 `202 Accepted`。

---

## 7. LLMProvider

接口语义：

```python
class LLMProvider(Protocol):
    async def stream(self, request: LLMRequest) -> AsyncIterator[str]:
        ...
```

至少实现：
- `MockLLMProvider`
- 一个真实 Provider 或兼容 OpenAI 风格的 Provider Adapter

Runtime 业务不得直接 import 某厂商 SDK 到 orchestrator。

---

## 8. SpeechPlan

LLM 输出必须规范化成：

```text
action
text
priority
emotion?
gesture?
interrupt?
uiAction?
```

LLM 解析失败：
- 可重试一次。
- 再失败使用纯文本 fallback。
- 发 `RUNTIME_WARNING`。

---

## 9. ToolClient

动态事实走 Go Internal Tool API。

必须支持：

```text
get_product
get_product_stock
get_product_price
```

禁止 Runtime 直接读取 PostgreSQL。

---

## 10. TTSProvider

接口：

```python
class TTSProvider(Protocol):
    async def synthesize_stream(
        self,
        text: str,
        voice: VoiceConfig,
        ctx: GenerationContext,
    ) -> AsyncIterator[AudioChunk]:
        ...
```

至少实现：
- `MockTTSProvider`
- 一个真实 TTS Provider Adapter

`AudioChunk` 必须有：
- generation_id
- sequence
- pcm bytes 或明确编码格式
- sample_rate
- channels

---

## 11. Sentence Buffer

LLM 不允许等完整答案才送 TTS。

流程：

```text
LLM Tokens
↓
Text Buffer
↓
Sentence Boundary
↓
TTS
```

切分触发：
- `。！？!?`
- 逗号 + 最小字符阈值
- 最大等待时间
- 最大 buffer 长度

目标是缩短 TTFS。

---

## 12. AvatarEngine

接口：

```python
class AvatarEngine(Protocol):
    async def prepare(self, config: AvatarConfig) -> None: ...
    async def start(self) -> None: ...
    async def push_audio(self, chunk: AudioChunk) -> None: ...
    async def interrupt(self, generation_id: int) -> None: ...
    async def stop(self) -> None: ...
```

至少：
- `MockAvatarEngine`
- `Wav2LipAvatarEngine` 或其他轻量开发实现
- 后续 MuseTalk Adapter

Orchestrator 禁止直接依赖具体 Avatar 实现。

---

## 13. RTX 2060 策略

开发环境优先：

```text
AVATAR_ENGINE=mock
```

接口联调完成后：

```text
AVATAR_ENGINE=lightweight
```

最终高质量实时验证：

```text
AVATAR_ENGINE=musetalk
```

MVP 目标是接口与工程架构稳定，不以 RTX 2060 达到 1080p 高质量实时为验收标准。

---

## 14. Interrupt

核心设计：

```text
generation_id
```

规则：

1. Session 初始 generation = 1。
2. 当前 utterance 的所有异步任务绑定 generation。
3. Interrupt：
   - generation += 1
   - cancel 当前 LLM task
   - cancel TTS task
   - 清理旧 audio queue
   - Avatar interrupt
   - 丢弃 generation 较旧的视频/音频产物
4. 发布 `UTTERANCE_INTERRUPTED`。
5. 新 utterance 可以进入队列。

---

## 15. Speech Queue

要求：
- Priority Queue
- FIFO within same priority
- 支持 interruptPolicy
- 同一 Session 同一时刻最多一个 PLAYING utterance

逻辑：

```text
FORCE
→ interrupt

INTERRUPT_LOWER_PRIORITY
→ new.priority > current.priority 才 interrupt

NONE
→ 排队
```

---

## 16. Runtime Event

通过 Redis Stream：

```text
dh.runtime.events.v1
```

EventPublisher 必须：
- 统一 Envelope
- eventId 唯一
- traceId 透传
- 失败重试
- 发布失败写结构化错误日志

---

## 17. Media

MVP：
- WebRTC Preview。

媒体链路必须留在 Runtime / Media 层。

禁止：
- PCM → Redis
- Video Frame → Go
- Frame → PostgreSQL

---

## 18. Audio Master Clock

建议：
- Audio 是 Master Clock。
- Video 跟随 Audio PTS。
- GPU 追不上时优先丢 Video Frame，而不是阻塞 Audio。

默认目标：
- 25 FPS。

---

## 19. Mock Mode

必须支持完整 Mock：

```text
MOCK_LLM=true
MOCK_TTS=true
MOCK_AVATAR=true
MOCK_MEDIA=true
```

Mock 模式：
- 不需要 CUDA。
- 可以在 Mac / CI 启动。
- 可模拟事件时序。
- 可测试 interrupt。

---

## 20. Health

`GET /internal/v1/health`

至少返回：
- status
- runtimeVersion
- gpu.available
- activeSessions
- providers

---

## 21. Metrics

最低：

```text
active_runtime_sessions
speech_queue_size
llm_ttft_ms
tts_first_chunk_ms
avatar_first_frame_ms
event_to_speech_ms
audio_queue_ms
video_queue_ms
render_fps
interrupt_count
runtime_errors_total
```

---

## 22. 日志

关键字段：

```text
traceId
sessionId
utteranceId
generationId
provider
latencyMs
```

---

## 23. Runtime 测试

至少：
- Create/Start/Stop Session
- Priority Queue
- FORCE Interrupt
- Lower Priority 不打断
- Generation 丢弃旧 chunk
- Mock LLM Streaming
- Mock TTS Streaming
- Runtime Event Schema
- Runtime API Contract
- Provider Failure Fallback
- Session cleanup

---

## 24. 完成标准

1. Mock 模式可运行。
2. Internal API 符合 Contracts。
3. Redis Event 符合 Schema。
4. Speak/Interrupt/Stop 正常。
5. 真实 Provider 可插拔。
6. Runtime 不访问业务数据库。
7. 无 GPU 环境 CI 可测试。
8. GPU 环境可切换真实 Avatar。
