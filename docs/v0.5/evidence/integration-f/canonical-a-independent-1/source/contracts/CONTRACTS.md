# AstraLive — Contracts

> Contract Version: **v1.1.0** (2026-10-06). v1.0.0 见 `CHANGELOG.md`。

> 文档等级：P0 / 最高优先级接口契约  
> 本文件是所有 Agent 的共同边界。  
> 当模块实现与本文件冲突时：修改实现，不得擅自修改契约。

## 1. Contract-First 原则

AstraLive 的所有跨模块交互必须先定义契约，再实现代码。

机器可读契约以本目录的 OpenAPI 和 JSON Schema 为准；本文件定义其语义与状态转换。

```text
contracts/
├── control-api.openapi.yaml
├── runtime-api.openapi.yaml
├── events/
│   ├── runtime-event.schema.json
│   ├── platform-event.schema.json
│   └── speech-plan.schema.json
└── examples/
```

本 MD 定义语义、命名与行为规则。

---

## 2. 统一命名

ID 字段统一：

- `avatarId`
- `voiceId`
- `productId`
- `knowledgeBaseId`
- `roomId`
- `sessionId`
- `utteranceId`
- `jobId`
- `eventId`
- `commandId`
- `operationId`
- `traceId`
- `requestId`

类型全部为 `string`。

推荐 ULID：

```text
avatar_01...
session_01...
utt_01...
evt_01...
```

---

## 3. 时间格式

所有跨服务时间：

```text
ISO-8601 UTC
```

示例：

```json
{
  "createdAt": "2026-10-06T05:21:32.138Z"
}
```

禁止 Unix 秒、毫秒与字符串时间混用。

---

## 4. API Version

Contract 文档与两份 OpenAPI 的 `info.version` 为 `1.1.0`。公共和内部路径仍使用 `/v1/`；Runtime Event 的 `schemaVersion` 仍为 `1.0`，本次不改变 Event wire format。

公共 API：

```text
/api/v1/**
```

内部 Runtime API：

```text
/internal/v1/**
```

Event：

```json
{
  "schemaVersion": "1.0"
}
```

兼容增加字段：
- 1.0 → 1.1

Breaking Change：
- 1.x → 2.0

---

## 5. HTTP 响应

### 5.1 同步成功

```json
{
  "code": "OK",
  "message": "success",
  "data": {},
  "requestId": "req_01",
  "timestamp": "2026-10-06T05:30:22Z"
}
```

### 5.2 错误

```json
{
  "code": "SESSION_NOT_READY",
  "message": "Live session is not ready",
  "details": {},
  "requestId": "req_01",
  "timestamp": "2026-10-06T05:30:22Z"
}
```

### 5.3 HTTP Status

- `200` 成功查询/动作完成
- `201` 创建成功
- `202` 异步任务已接受
- `400` 参数错误
- `401` 未认证
- `403` 无权限
- `404` 资源不存在
- `409` 状态冲突
- `422` 语义校验失败
- `429` 过载/限流
- `500` 内部错误
- `503` Runtime/GPU 不可用

禁止所有请求都返回 200。

---

## 6. 核心错误码

必须至少包含：

```text
INVALID_ARGUMENT
RESOURCE_NOT_FOUND
CONFLICT
SESSION_NOT_FOUND
SESSION_NOT_READY
SESSION_ALREADY_RUNNING
SESSION_NOT_RUNNING
AVATAR_NOT_FOUND
AVATAR_NOT_READY
VOICE_NOT_FOUND
ROOM_NOT_FOUND
PRODUCT_NOT_FOUND
RUNTIME_UNAVAILABLE
RUNTIME_OVERLOADED
GPU_OUT_OF_MEMORY
LLM_FAILED
TTS_FAILED
AVATAR_RENDER_FAILED
MEDIA_OUTPUT_FAILED
WEBRTC_FAILED
INTERRUPT_FAILED
EVENT_PUBLISH_FAILED
INTERNAL_ERROR
```

---

# 7. Public Control API

## 7.1 Avatar

### POST `/api/v1/avatars`

Request:

```json
{
  "name": "主播一号",
  "engine": "MOCK"
}
```

Response `201`:

```json
{
  "code": "OK",
  "message": "success",
  "data": {
    "avatarId": "avatar_01",
    "name": "主播一号",
    "engine": "MOCK",
    "status": "CREATED"
  },
  "requestId": "req_01",
  "timestamp": "2026-10-06T05:30:22Z"
}
```

### GET `/api/v1/avatars`

### GET `/api/v1/avatars/{avatarId}`

### POST `/api/v1/avatars/{avatarId}/prepare`

异步，返回 `202`：

```json
{
  "code": "OK",
  "message": "accepted",
  "data": {
    "jobId": "job_01",
    "status": "PENDING"
  },
  "requestId": "req_01",
  "timestamp": "2026-10-06T05:30:22Z"
}
```

### DELETE `/api/v1/avatars/{avatarId}`

---

## 7.2 Voice

### POST `/api/v1/voices`

Request:

```json
{
  "name": "女主播01",
  "provider": "MOCK",
  "providerVoiceId": "mock-female-01"
}
```

### GET `/api/v1/voices`

### GET `/api/v1/voices/{voiceId}`

### DELETE `/api/v1/voices/{voiceId}`

---

## 7.3 Product

### POST `/api/v1/products`

```json
{
  "name": "纯棉卫衣",
  "description": "320g 纯棉面料",
  "price": 129.0,
  "currency": "CNY",
  "stock": 27,
  "sizes": ["M", "L", "XL"]
}
```

### PUT `/api/v1/products/{productId}`

### GET `/api/v1/products`

### GET `/api/v1/products/{productId}`

---

## 7.4 KnowledgeBase

KnowledgeBase 元数据保留；文档上传与索引执行协议为 **v0.2 deferred**，以下既有路径仅作为扩展占位，不计入 v0.1 核心链路验收。

### POST `/api/v1/knowledge-bases`

### POST `/api/v1/knowledge-bases/{knowledgeBaseId}/documents`

### POST `/api/v1/knowledge-bases/{knowledgeBaseId}/index`

返回 `202` + `jobId`。

### GET `/api/v1/jobs/{jobId}`

---

## 7.5 LiveRoom

### POST `/api/v1/live-rooms`

```json
{
  "name": "服装直播间",
  "avatarId": "avatar_01",
  "voiceId": "voice_01",
  "activeProductId": "product_01",
  "knowledgeBaseId": "kb_01",
  "systemPrompt": "你是一名简洁、自然的服装主播。"
}
```

### PUT `/api/v1/live-rooms/{roomId}`

### GET `/api/v1/live-rooms`

### GET `/api/v1/live-rooms/{roomId}`

---

## 7.6 LiveSession

### POST `/api/v1/live-sessions`

```json
{
  "roomId": "room_01"
}
```

Response `201`:

```json
{
  "code": "OK",
  "message": "success",
  "data": {
    "sessionId": "session_01",
    "status": "CREATED"
  },
  "requestId": "req_01",
  "timestamp": "2026-10-06T05:30:22Z"
}
```

### POST `/api/v1/live-sessions/{sessionId}/start`

必须支持：

```http
Idempotency-Key: <client-generated-value>
```

Response `202`:

```json
{
  "code": "OK",
  "message": "accepted",
  "data": {
    "operationId": "op_01",
    "sessionId": "session_01",
    "status": "PREPARING"
  },
  "requestId": "req_01",
  "timestamp": "2026-10-06T05:30:22Z"
}
```

### POST `/api/v1/live-sessions/{sessionId}/stop`

异步，返回 `202`。

### GET `/api/v1/live-sessions/{sessionId}`

### GET `/api/v1/live-sessions/{sessionId}/events`

SSE。

### POST `/api/v1/live-sessions/{sessionId}/webrtc/offer`

MVP 使用 non-trickle ICE。Browser 必须在本地 ICE gathering 完成后提交完整 SDP offer；Go 校验当前 Session 属于可预览的 `LIVE`/`DEGRADED` 状态，将原样 SDP 转发至 Runtime。Runtime 在 ICE gathering 完成后返回完整 SDP answer，Go 包装成公共成功 Envelope。请求和响应分别为：

```json
{"type":"offer","sdp":"..."}
```

```json
{"code":"OK","message":"success","data":{"type":"answer","sdp":"..."},"requestId":"req_01","timestamp":"2026-10-06T05:30:22Z"}
```

不存在的 Session 返回 `404 SESSION_NOT_FOUND`；非可预览状态返回 `409 SESSION_NOT_RUNNING`；SDP 或 Peer 协商失败使用 `WEBRTC_FAILED`（`500`/`503`）。本版不提供 trickle ICE candidate API、WebSocket signaling 或额外的 ICE 配置 DTO。部署必须确保 SDP 中的 Runtime ICE candidate 对 Browser 可达。

---

## 7.7 Utterance

### POST `/api/v1/live-sessions/{sessionId}/utterances`

```json
{
  "text": "欢迎大家进入直播间。",
  "priority": 100,
  "interruptPolicy": "FORCE",
  "source": "OPERATOR"
}
```

Response `202`:

```json
{
  "code": "OK",
  "message": "accepted",
  "data": {
    "utteranceId": "utt_01",
    "status": "QUEUED"
  },
  "requestId": "req_01",
  "timestamp": "2026-10-06T05:30:22Z"
}
```

`interruptPolicy`：

```text
NONE
INTERRUPT_LOWER_PRIORITY
FORCE
```

`source`：

```text
OPERATOR
PLATFORM_EVENT
AUTO_SCRIPT
SYSTEM
```

---

## 7.8 Interrupt

### POST `/api/v1/live-sessions/{sessionId}/interrupt`

```json
{
  "reason": "OPERATOR_INTERRUPT"
}
```

Response `202`。

---

## 7.9 Dev Platform Event

仅开发环境：

### POST `/api/v1/dev/platform-events`

```json
{
  "eventType": "COMMENT",
  "roomId": "room_01",
  "user": {
    "externalId": "mock-user-01",
    "nickname": "测试用户"
  },
  "payload": {
    "text": "有 XL 吗？"
  }
}
```

Go 根据 `roomId` 寻找当前 `LIVE` 或 `DEGRADED` Session。没有活动 Session 时返回 `409 SESSION_NOT_RUNNING`，不投递至 Runtime。找到后 Go 为 COMMENT 创建普通 Utterance，取 `text=payload.text`、`source=PLATFORM_EVENT`、`priority=80`、`interruptPolicy=INTERRUPT_LOWER_PRIORITY`，生成 `utteranceId`、`commandId` 和 `traceId`，沿用现有 `POST /internal/v1/sessions/{sessionId}/utterances`。成功接受返回 `202` 与普通 Utterance 的 `QUEUED` Envelope。可附带仅包含 `eventType=COMMENT` 和通用 `user.externalId`/`nickname` 的 `platformContext`；Runtime 不解析具体平台原始格式。

---

# 8. Internal Runtime API

所有 `/internal/**` 只能由 Go 调用。

## 8.1 Create Runtime Session

### POST `/internal/v1/sessions`

```json
{
  "commandId": "cmd_01",
  "traceId": "trace_01",
  "sessionId": "session_01",
  "avatar": {
    "avatarId": "avatar_01",
    "engine": "MOCK"
  },
  "voice": {
    "voiceId": "voice_01",
    "provider": "MOCK"
  },
  "config": {
    "fps": 25,
    "preview": {
      "type": "WEBRTC"
    }
  },
  "context": {
    "roomId": "room_01",
    "systemPrompt": "你是一名简洁自然的服装主播。",
    "activeProductId": "product_01",
    "knowledgeBaseId": "kb_01"
  }
}
```

`context.roomId` 与 `context.systemPrompt` 必填；`activeProductId`、`knowledgeBaseId` 可选。Go 在创建 Runtime Session 时从 LiveRoom 生成 Context 快照并随命令发送；Runtime 在该 Session 生命周期内使用快照，不直接查询 LiveRoom 数据库。`activeProductId` 的后续 LiveRoom 更新不会暗中改变已创建的 Runtime Session。

Response `202`:

```json
{
  "accepted": true,
  "operationId": "op_runtime_01"
}
```

## 8.2 Start

### POST `/internal/v1/sessions/{sessionId}/start`

Response `202`。

## 8.3 Speak

### POST `/internal/v1/sessions/{sessionId}/utterances`

```json
{
  "commandId": "cmd_02",
  "traceId": "trace_02",
  "utteranceId": "utt_01",
  "text": "欢迎进入直播间。",
  "priority": 100,
  "interruptPolicy": "FORCE",
  "source": "OPERATOR",
  "voice": {
    "voiceId": "voice_01"
  }
}
```

`source` 必填，允许 `OPERATOR`、`PLATFORM_EVENT`、`AUTO_SCRIPT`、`SYSTEM`。平台 COMMENT 可选带入：

```json
{"platformContext":{"eventType":"COMMENT","user":{"externalId":"mock-user-01","nickname":"测试用户"}}}
```

`platformContext` 是 Utterance 的可选字段，只表达标准化事件来源；`text` 始终在 Utterance 顶层。

## 8.4 Interrupt

### POST `/internal/v1/sessions/{sessionId}/interrupt`

```json
{
  "commandId": "cmd_03",
  "traceId": "trace_03",
  "reason": "OPERATOR_INTERRUPT"
}
```

## 8.5 Stop

### POST `/internal/v1/sessions/{sessionId}/stop`

## 8.6 Health

### GET `/internal/v1/health`

Response：

```json
{
  "status": "UP",
  "runtimeVersion": "0.1.0",
  "gpu": {
    "available": false
  }
}
```

Runtime Health 还必须返回 `activeSessions` 和 `providers`，与 Runtime 要求一致。

## 8.7 WebRTC Offer

### POST `/internal/v1/sessions/{sessionId}/webrtc/offer`

Go 转发 `{"type":"offer","sdp":"..."}`；Runtime 返回 `200` 与 `{"type":"answer","sdp":"..."}`。仅传 SDP 信令。Browser ↔ Runtime 直接传 Audio/Video，Go、Redis、PostgreSQL 均不传媒体。Runtime 不要求 Go 提供 trickle candidate；失败使用 `WEBRTC_FAILED`。

### Go Internal Tool API

Runtime 调用 Go 的商品工具接口，不属于 Python Runtime 服务：

```text
GET /internal/v1/tools/products/{productId}
GET /internal/v1/tools/products/{productId}/stock
GET /internal/v1/tools/products/{productId}/price
```

响应使用第 15 节的 Tool Result 结构。

---

# 9. Runtime Event Contract

Redis Stream：

```text
dh.runtime.events.v1
```

统一 Envelope：

```json
{
  "schemaVersion": "1.0",
  "eventId": "evt_01",
  "eventType": "SESSION_READY",
  "sessionId": "session_01",
  "utteranceId": null,
  "traceId": "trace_01",
  "occurredAt": "2026-10-06T05:30:22Z",
  "source": "AI_RUNTIME",
  "payload": {}
}
```

必须支持事件：

```text
SESSION_PREPARING
SESSION_READY
SESSION_STARTED
SESSION_DEGRADED
SESSION_STOPPING
SESSION_ENDED
SESSION_FAILED

UTTERANCE_QUEUED
UTTERANCE_GENERATING
UTTERANCE_SYNTHESIZING
UTTERANCE_RENDERING
UTTERANCE_PLAYING
UTTERANCE_COMPLETED
UTTERANCE_INTERRUPTED
UTTERANCE_FAILED

MEDIA_READY
MEDIA_FAILED

RUNTIME_WARNING
RUNTIME_ERROR
```

---

# 10. Frontend SSE Event

Go 可以直接复用 Runtime Event Envelope，但 `source` 可变成 `CONTROL_PLANE`。

SSE：

```text
event: utterance.playing
data: {...}
```

Heartbeat 必须是显式 SSE frame：

```text
event: heartbeat
data: {"timestamp":"2026-10-06T05:30:22Z"}

```

`timestamp` 为 ISO-8601 UTC。Frontend 可用 heartbeat 重置连接超时计时器，但不得将其加入业务 Event Timeline；它不是 Runtime Event Envelope，也不需要 `eventId`。

前端必须至少处理：

```text
session.preparing
session.ready
session.live
session.degraded
session.ended
session.failed

utterance.queued
utterance.generating
utterance.synthesizing
utterance.rendering
utterance.playing
utterance.completed
utterance.interrupted
utterance.failed

media.ready
runtime.warning
runtime.error
```

---

# 11. LiveSession FSM

允许：

```text
CREATED -> PREPARING
PREPARING -> READY
PREPARING -> FAILED
READY -> STARTING
STARTING -> LIVE
STARTING -> FAILED
LIVE -> DEGRADED
DEGRADED -> LIVE
LIVE -> STOPPING
DEGRADED -> STOPPING
STOPPING -> ENDED
任意运行态 -> FAILED（不可自动恢复时）
```

禁止非法跳跃。

Go 必须在状态更新前校验 FSM。

`SESSION_READY` 使 Go 从 `PREPARING` 进入 `READY`；Go 发送 Runtime Start 命令前进入 `STARTING`；`SESSION_STARTED` 使 Go 从 `STARTING` 进入 `LIVE`。`SESSION_PREPARING` 可确认已处于 `PREPARING` 的状态，不触发重复转换。客户端 Start 返回的 `PREPARING` 是异步启动操作的初始状态。

---

# 12. Utterance FSM

允许：

```text
QUEUED -> GENERATING
GENERATING -> SYNTHESIZING
SYNTHESIZING -> RENDERING
RENDERING -> PLAYING
PLAYING -> COMPLETED

任意未终止状态 -> INTERRUPTED
任意未终止状态 -> FAILED
QUEUED -> CANCELLED
```

---

# 13. Priority

建议：

```text
100 OPERATOR
95  SYSTEM_EMERGENCY
80  PRODUCT_QUESTION
75  ORDER_EVENT
60  GIFT
50  FOLLOW
40  CHAT
20  AUTO_SCRIPT
10  IDLE
```

如果新 Utterance：
- `interruptPolicy=FORCE`：直接打断。
- `INTERRUPT_LOWER_PRIORITY` 且新 priority > 当前 priority：打断。
- 否则排队。

队列总是先执行较高 priority；同 priority 按接收顺序 FIFO。`NONE` 从不抢占当前讲话，`INTERRUPT_LOWER_PRIORITY` 只在新 priority 严格大于当前 priority 时抢占，`FORCE` 抢占当前讲话。Mock Runtime 与 Real Runtime 必须遵守完全相同的 Session FSM、Utterance FSM、优先级队列及抢占语义。新 Speak 不得无条件打断当前讲话。Integration Acceptance 不得以语义不一致的 Mock 结果证明 Real Runtime 已通过。

---

# 14. SpeechPlan

LLM 不直接返回裸字符串。

统一结构：

```json
{
  "action": "SPEAK",
  "text": "有的，XL 目前还有库存。",
  "emotion": "happy",
  "gesture": "nod",
  "priority": 80,
  "interrupt": true,
  "uiAction": null
}
```

MVP 只强制：
- `action`
- `text`
- `priority`

其余字段可选。

---

# 15. Tool Contract

动态事实必须走 Tool，不允许 LLM 臆造。

最少提供：

```text
get_product(productId)
get_product_stock(productId)
get_product_price(productId)
```

Tool Result：

```json
{
  "ok": true,
  "data": {
    "productId": "product_01",
    "stock": 27
  }
}
```

Runtime 从 Session Context 读取 `activeProductId`。当 `PLATFORM_EVENT` 或其他 Utterance 需要动态商品事实时，按实际问题调用现有 Go Tool API `GET /internal/v1/tools/products/{productId}`、`/stock`、`/price` 中所需接口，将返回事实用于 LLM 上下文或 SpeechPlan。不得从自由文本推断商品 ID，也不得让 LLM 猜库存、价格等动态事实。没有 `activeProductId` 时，向 LLM 提供明确的 unavailable context；仍可回答与商品动态事实无关的问题。Tool 失败时发布 `RUNTIME_WARNING`，不虚构事实，可自然降级回复，例如“我现在暂时查不到库存”。Tool Result wire format 不变。

---

# 16. Trace

每条用户输入或 Platform Event 生成一个 `traceId`。

它必须贯穿：

```text
Frontend / Platform Event
→ Go
→ Runtime
→ LLM
→ TTS
→ Avatar
→ Runtime Event
→ Go
→ SSE
```

日志必须包含 `traceId`。

---

# 17. 幂等

至少以下接口支持 `Idempotency-Key`：

```text
POST /live-sessions/{id}/start
POST /live-sessions/{id}/stop
POST /live-sessions/{id}/utterances
POST /avatars/{id}/prepare
POST /knowledge-bases/{id}/index
```

---

# 18. Contract Test 最低要求

Backend：
- 根据 OpenAPI 验证输入输出。
- Enum 严格匹配。
- Error Code 严格匹配。

Runtime：
- Internal API Contract Test。
- Runtime Event JSON Schema Test。

Frontend：
- API Client 从 OpenAPI 生成或由单一契约生成。
- 禁止手工复制核心 DTO。

Integration：
- 提供 Mock Runtime。
- 提供 Mock Event Publisher。
- 提供 Contract Fixtures。

---

# 19. Deferred 与尚未定义的边界

Knowledge document 上传载荷、索引 Worker/Job 完成反馈、高级 Avatar preprocessing 归入 **v0.2 deferred**。已有路径保留为未来扩展占位，但 v0.1 核心验收不要求文档索引或高级 Avatar prepare 完成；不得将未执行的 Job 标为成功。KnowledgeBase 元数据和可选 `knowledgeBaseId` 仅冻结最小结构，不承诺 RAG 已可用。Mock Avatar 元数据及基础准备流程可以用于核心链路。

Avatar 完整状态枚举、KnowledgeBase 创建字段与查询路由、Dashboard 聚合查询路由、非 `COMMENT` 平台事件 payload 仍待后续 CCR。v0.1 核心验收聚焦 Session、Speak、Interrupt、COMMENT、Product Tool、Browser WebRTC 及事件链路；这些未定义边界不得由模块自行发明，也不得阻塞上述核心验收。
