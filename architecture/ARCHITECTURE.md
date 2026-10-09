# AstraLive — Architecture

> Contract 基线：**v1.1.0**；路径仍为 `/api/v1/**`、`/internal/v1/**`。

> 文档等级：P0 / 全局架构约束  
> 适用对象：Lead Agent、Backend Agent、Runtime Agent、Frontend Agent、Integration Agent  
> 原则：如本文件与模块内部实现冲突，先检查 `contracts/CONTRACTS.md`；契约优先于实现。

## 1. 项目定义

AstraLive 是一个面向个人开发者与后续小规模商用演进的 AI 数字人实时直播 MVP。

MVP 的目标不是训练数字人基础模型，而是完成一条稳定、可替换、可测试的实时链路：

```text
用户/模拟弹幕
  ↓
Go Control Plane
  ↓
Python AI Runtime
  ↓
LLM / Tool / RAG
  ↓
Streaming TTS
  ↓
Avatar Engine
  ↓
WebRTC Preview
  ↓
React 控制台
```

后续可以扩展 RTMP、直播伴侣、SRS、多直播间、多 GPU、多平台适配，但这些都不是 MVP 的前置条件。

---

## 2. MVP 范围

### 2.1 必须完成

1. Avatar 元数据管理。
2. Voice 元数据管理。
3. Product 基础管理；KnowledgeBase 仅保留非阻塞元数据结构。
4. LiveRoom 配置。
5. LiveSession 创建、启动、停止。
6. Runtime Session 创建与销毁。
7. 手动输入文本让数字人讲话。
8. 支持讲话队列。
9. 支持 Interrupt。
10. 支持 Mock Platform Event。
11. 支持 LLM Provider 抽象。
12. 支持 TTS Provider 抽象。
13. 支持 Avatar Engine 抽象。
14. 浏览器 WebRTC 预览。
15. Runtime Event → Redis Stream → Go → SSE → React。
16. RTX 2060 环境下至少完成单路开发验证。
17. Mock 模式不依赖 GPU，可在任意开发机完成接口与联调测试。
18. 完整日志、错误码、Trace ID。
19. Docker Compose 启动基础设施。
20. 集成测试覆盖核心链路。

v0.1 的核心验收链路为 Session、Speak、Interrupt、Mock COMMENT、Product Tool、Browser WebRTC 和事件同步。Knowledge document/index Worker 与高级 Avatar preprocessing 归入 **v0.2 deferred**，不得成为上述核心链路的前置条件；未执行的 Job 不得宣称完成。

### 2.2 MVP 明确不做

- 多租户计费
- 支付系统
- Spring Cloud / Kubernetes
- Kafka / Pulsar
- 多 GPU 调度
- 真实抖音逆向协议
- 3D 数字人
- 自研 TTS / LLM / Avatar 基础模型
- 复杂权限系统
- 多平台同时开播
- 商用级自动扩缩容
- BI 大屏
- 高可用数据库集群

---

## 3. 技术栈

### 3.1 Frontend

- React
- Vite
- TypeScript 7
- Bun
- TanStack Query
- Zustand
- Tailwind CSS
- shadcn/ui
- Zod
- WebRTC Browser APIs
- EventSource（SSE）

### 3.2 Control Plane

- Go
- `net/http`
- `chi`
- OpenAPI
- `oapi-codegen`
- PostgreSQL
- `pgx`
- `sqlc`
- Redis
- MinIO SDK
- `slog`
- OpenTelemetry
- Prometheus

### 3.3 AI Runtime

- Python
- FastAPI
- Pydantic
- asyncio
- PyTorch / CUDA
- LLM Provider Adapter
- TTS Provider Adapter
- Avatar Engine Adapter
- FFmpeg
- WebRTC
- 第一阶段 Avatar 可优先使用轻量方案，后续切 MuseTalk / LiveTalking。

### 3.4 Infrastructure

- Docker Compose
- PostgreSQL
- Redis
- MinIO
- 后续可增加 SRS
- NVIDIA Container Toolkit（GPU 主机）

---

## 4. 核心架构

```text
┌───────────────────────────────────────────────┐
│ React Admin                                   │
│                                               │
│ Room / Avatar / Voice / Product / Live Console│
└─────────────────────┬─────────────────────────┘
                      │ REST + SSE
                      ▼
┌───────────────────────────────────────────────┐
│ Go Control Plane                              │
│                                               │
│ System of Record                              │
│ Session FSM / Job / Utterance / Metadata      │
└───────────┬───────────────────┬───────────────┘
            │                   │
            │ Internal REST     │ Redis Events
            ▼                   ▲
┌───────────────────────────────────────────────┐
│ Python AI Runtime                             │
│                                               │
│ SessionManager                                │
│ LLM → TTS → Avatar → Media                    │
└─────────────────────┬─────────────────────────┘
                      │
                      │ WebRTC
                      ▼
                 Browser Preview
```

---

## 5. 三种通信类型

### 5.1 Control Command：REST

用于：
- 创建资源
- 创建 Session
- Start
- Stop
- Speak
- Interrupt
- 查询状态

原则：
- REST 不传大媒体流。
- Runtime 长任务不得阻塞 HTTP 请求。
- 长任务返回 `202 Accepted`。

### 5.2 State/Event：Redis Streams + SSE

Runtime → Go：
- Redis Streams

Go → Frontend：
- SSE
- 显式 `event: heartbeat` 与 UTC `timestamp` 用于连接保活，不写入业务 Event Timeline

原则：
- Event 表示“已经发生的事实”。
- Command 表示“请求执行动作”。
- 不允许把 Event 当成 Command 使用。

### 5.3 Media：WebRTC / RTMP

MVP：
- Python Runtime → Browser 使用 WebRTC。
- Browser → Go → Runtime 仅交换完整 SDP offer/answer；采用 non-trickle ICE，不使用 WebSocket signaling。Browser ↔ Runtime 直传媒体，Go、Redis、PostgreSQL 不承载 Audio/Video。Runtime ICE candidate 必须从 Browser 可达。

后续：
- Runtime → SRS → WebRTC / RTMP。

原则：
- PCM、RGB Frame、H264 Frame 不经过 Go。
- 不把音视频数据写入 PostgreSQL / Redis。

---

## 6. 数据所有权

### 6.1 Go 拥有

Go 是 System of Record。

Go 将 `POST /api/v1/dev/platform-events` 的 COMMENT 按 `roomId` 路由至当前 LIVE/DEGRADED Session，标准化为普通 PLATFORM_EVENT Utterance。Runtime 不接收平台专有 payload。

Go 拥有：
- Avatar Metadata
- Voice Metadata
- Product
- KnowledgeBase Metadata
- LiveRoom
- LiveSession
- Utterance
- Job
- Event Persistence
- Runtime Worker Metadata（后续）

### 6.2 Python 拥有

Python 只拥有运行时内存状态：
- Session Runtime
- Speech Queue
- Audio Queue
- Video Queue
- Generation Token
- LLM Stream
- TTS Stream
- Avatar Runtime State
- WebRTC Peer State

Runtime 从 Session Context 获取当前商品 ID；库存、价格等动态事实须通过 Go Product Tool 查询。缺少商品或 Tool 失败时提供 unavailable context，并发布所需 warning，不生成猜测值。

Runtime 重启后这些状态允许丢失，由 Go 负责判断并重建或结束 Session。

### 6.3 禁止

Python 不允许：
- 直接写 PostgreSQL 业务表
- 直接查询 LiveRoom 业务表；Go 创建 Runtime Session 时提供 `roomId`、`systemPrompt` 与可选 `activeProductId`、`knowledgeBaseId` 的 Context 快照
- 修改 LiveSession 业务状态
- 创建前端业务资源

React 不允许：
- 访问数据库
- 访问 Redis
- 直接控制 TTS / Avatar
- 直接调用内部 Runtime Control API

---

## 7. 核心状态机

### 7.1 LiveSession

```text
CREATED
  ↓
PREPARING
  ↓
READY
  ↓
STARTING
  ↓
LIVE
  ↓
STOPPING
  ↓
ENDED
```

异常：
- `FAILED`
- `DEGRADED`

状态由 Go 最终确认。

Python 只发送事实事件，例如：
- `SESSION_PREPARING`
- `SESSION_READY`
- `SESSION_STARTED`
- `SESSION_FAILED`

### 7.2 Utterance

```text
QUEUED
  ↓
GENERATING
  ↓
SYNTHESIZING
  ↓
RENDERING
  ↓
PLAYING
  ↓
COMPLETED
```

异常：
- `INTERRUPTED`
- `CANCELLED`
- `FAILED`

---

## 8. Interrupt 设计

每个 Runtime Session 必须维护：

```text
generation_id
```

例如当前 generation = 17。

发生 interrupt：
- generation 变成 18。
- 所有 generation < 18 的异步产物视为失效。
- LLM token、TTS chunk、Audio chunk、Video frame 均需校验 generation。
- 清理旧播放队列。
- Avatar Engine 执行 interrupt。

禁止只调用 `queue.clear()` 作为完整打断策略。

Mock 与 Real Runtime 必须共享相同的 Session/Utterance FSM、优先级队列、同优先级 FIFO 及 `NONE`、`INTERRUPT_LOWER_PRIORITY`、`FORCE` 抢占语义。Mock 收到新 Speak 不得无条件打断当前讲话；Integration Acceptance 不得以语义不同的 Mock 作为 Real Runtime 的证明。

---

## 9. Provider / Adapter 原则

必须抽象：

```text
LLMProvider
TTSProvider
AvatarEngine
MediaOutput
StorageProvider
PlatformAdapter
```

业务层只能依赖接口。

例如：

```text
AvatarEngine
  ├── MockAvatarEngine
  ├── Wav2LipAvatarEngine
  └── MuseTalkAvatarEngine
```

RTX 2060 开发阶段允许使用轻量 Avatar Provider，后续无需改 Control Plane。

---

## 10. 多 Agent 所有权

### Lead / Architect Agent
只允许修改：
- `architecture/**`
- `contracts/**`

职责：
- 维护架构
- 审核 Contract Change Request
- 解决跨模块冲突

### Backend Agent
只允许修改：
- `backend/**`

### Runtime Agent
只允许修改：
- `runtime/**`

### Frontend Agent
只允许修改：
- `frontend/**`

### Integration Agent
只允许修改：
- `integration/**`
- `infra/**`
- `tests/**`
- `scripts/**`

任何 Agent 不得为了“让自己代码能跑”而私自修改契约。

---

## 11. Contract Change Request

接口需要修改时必须提交 CCR。

模板：

```md
# CCR-001

## Reason
当前 START_SESSION 缺少 output 配置。

## Proposed Change
StartSessionRequest 增加 output.type。

## Impact
- Backend
- Runtime
- Frontend

## Breaking
NO

## Migration
无。
```

Lead Agent 合并契约后，各模块再同步实现。

---

## 12. Repo 目录

```text
AstraLive/
├── architecture/
│   └── ARCHITECTURE.md
├── contracts/
│   └── CONTRACTS.md
├── backend/
│   └── BACKEND-GO.md
├── runtime/
│   └── AI-RUNTIME.md
├── frontend/
│   └── FRONTEND.md
├── integration/
│   └── INTEGRATION-TESTING.md
├── infra/
├── tests/
└── scripts/
```

开发正式开始后，各 Agent 在对应目录内建立代码。

---

## 13. Definition of Done

任一模块完成必须满足：

1. 可编译 / 可启动。
2. 单元测试通过。
3. 不违反 Contracts。
4. 有健康检查。
5. 有结构化日志。
6. 有错误处理。
7. 无硬编码密钥。
8. 配置全部通过环境变量。
9. 有 README 或模块运行说明。
10. Integration Agent 能使用 Mock 对接。
11. Contract Test 通过。
12. 关键行为可被自动化测试。

---

## 14. MVP 最终验收

AstraLive v0.1 必须实现：

1. 创建 Avatar。
2. 创建 Voice。
3. 创建 LiveRoom。
4. 创建 LiveSession。
5. 启动 Session。
6. 浏览器出现 WebRTC Preview。
7. 输入文字，数字人说话。
8. 讲话过程中可 Interrupt。
9. Mock COMMENT 能触发 AI 回复。
10. 商品库存使用 Tool 获取，LLM 不得臆造。
11. Runtime Event 能同步到 React。
12. 系统连续运行 1 小时无致命崩溃。
13. 无 GPU 时 Mock 模式仍可完成全链路联调。
