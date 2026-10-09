# AstraLive — Backend Go Requirements

> Owner：Backend Agent  
> 允许修改：`backend/**`  
> 必须先阅读：`architecture/ARCHITECTURE.md`、`contracts/CONTRACTS.md`

## 1. 角色

Go Backend 是 AstraLive 的 Control Plane 和 System of Record。

它负责：
- HTTP API
- 资源管理
- PostgreSQL
- Redis Event Consumer
- LiveSession FSM
- Utterance FSM
- Runtime Client
- SSE
- Job
- Idempotency
- Trace
- 业务日志

它不负责：
- LLM 推理
- TTS
- GPU
- MuseTalk
- FFmpeg
- PCM/Video Frame
- WebRTC 媒体编码

---

## 2. 技术栈

```text
Go
net/http
chi
pgx
sqlc
go-redis
MinIO SDK
oapi-codegen
slog
OpenTelemetry
Prometheus
```

原则：
- 不使用重量 ORM。
- SQL 通过 `sqlc` 生成强类型访问层。
- API Schema 从 OpenAPI 生成。
- 配置通过环境变量。

---

## 3. 建议目录

```text
backend/
├── BACKEND-GO.md
├── cmd/
│   └── server/
│       └── main.go
├── internal/
│   ├── app/
│   ├── config/
│   ├── httpapi/
│   ├── avatar/
│   ├── voice/
│   ├── product/
│   ├── knowledge/
│   ├── room/
│   ├── session/
│   ├── utterance/
│   ├── job/
│   ├── runtime/
│   ├── eventbus/
│   ├── sse/
│   └── idempotency/
├── db/
│   ├── migrations/
│   └── queries/
├── generated/
│   └── openapi/
└── tests/
```

---

## 4. 数据库

最低表：

```text
avatars
voices
products
knowledge_bases
knowledge_documents
live_rooms
live_sessions
utterances
jobs
runtime_events
idempotency_keys
```

建议公共字段：

```text
id
created_at
updated_at
```

### live_sessions

至少：

```text
id
room_id
status
runtime_operation_id
failure_code
failure_message
created_at
updated_at
started_at
ended_at
```

### utterances

至少：

```text
id
session_id
source
text
priority
interrupt_policy
status
trace_id
failure_code
created_at
updated_at
started_at
completed_at
```

---

## 5. Repository / Service / Transport

每个业务模块建议：

```text
handler
service
repository
model
```

禁止 Handler 直接写 SQL。

例如：

```text
POST /live-sessions/{id}/start

HTTP Handler
  ↓
SessionService.Start()
  ↓
validate FSM
  ↓
Repository
  ↓
RuntimeClient.Start()
```

---

## 6. Runtime Client

必须封装：

```go
type RuntimeClient interface {
    CreateSession(ctx context.Context, req CreateRuntimeSessionRequest) (Operation, error)
    StartSession(ctx context.Context, sessionID string, req StartRuntimeSessionRequest) (Operation, error)
    Speak(ctx context.Context, sessionID string, req RuntimeUtteranceRequest) (Operation, error)
    Interrupt(ctx context.Context, sessionID string, req RuntimeInterruptRequest) (Operation, error)
    StopSession(ctx context.Context, sessionID string, req StopRuntimeSessionRequest) (Operation, error)
    Health(ctx context.Context) (RuntimeHealth, error)
}
```

业务层不能散落 HTTP 调用代码。

---

## 7. Start Session 流程

```text
POST start
↓
检查 session
↓
检查当前 FSM
↓
检查 Avatar / Voice
↓
写状态 PREPARING
↓
调用 Runtime
↓
得到 202 + operationId
↓
持久化 operationId
↓
立即返回 202
```

不要等待 Runtime Ready。

真正 Ready：

```text
Runtime Event
↓
Redis
↓
Go Consumer
↓
FSM 校验
↓
更新 READY
↓
SSE
```

---

## 8. Utterance 流程

```text
POST utterance
↓
验证 Session 可讲话
↓
创建 utterance = QUEUED
↓
生成 traceId
↓
调用 Runtime
↓
202
```

Runtime 事件驱动后续状态。

禁止 Backend 自己猜测：
- “TTS 完成了”
- “正在播放”
- “数字人说完了”

必须由 Runtime Event 驱动。

---

## 9. Runtime Event Consumer

Redis Stream：

```text
dh.runtime.events.v1
```

要求：
- Consumer Group。
- 至少一次消费。
- eventId 去重。
- 成功后 ACK。
- 失败重试。
- 超过阈值进入 dead-letter 或错误日志。

处理逻辑必须幂等。

事件处理：

```text
SESSION_READY
→ Session READY

SESSION_STARTED
→ Session LIVE

SESSION_FAILED
→ Session FAILED

UTTERANCE_PLAYING
→ Utterance PLAYING

UTTERANCE_COMPLETED
→ Utterance COMPLETED
```

---

## 10. SSE

Endpoint：

```text
GET /api/v1/live-sessions/{sessionId}/events
```

要求：
- 支持长连接。
- Client Disconnect 正常释放。
- Heartbeat。
- 至少支持最近状态快照 + 实时事件。
- 不保证历史事件无限重放。

MVP 可以：
- 从 Go 内部 Event Hub 广播。
- Runtime Event Consumer 处理后同步广播。

---

## 11. Idempotency

至少实现：

```text
start
stop
utterance
avatar prepare
knowledge index
```

请求头：

```http
Idempotency-Key: ...
```

数据库记录：

```text
key
route
request_hash
response_status
response_body
expires_at
```

相同 key + 不同 request body：
- 返回 `409 CONFLICT`。

---

## 12. Job

Job 状态：

```text
PENDING
RUNNING
COMPLETED
FAILED
CANCELLED
```

适用于：
- Avatar Prepare
- Knowledge Index

接口：

```text
GET /api/v1/jobs/{jobId}
```

---

## 13. Product Tool API

AI Runtime 不应直接访问业务数据库。

Go 提供内部 Tool Endpoint：

```text
GET /internal/v1/tools/products/{productId}
GET /internal/v1/tools/products/{productId}/stock
GET /internal/v1/tools/products/{productId}/price
```

只对 Runtime 网络开放。

---

## 14. 错误映射

Runtime Timeout：
- `503 RUNTIME_UNAVAILABLE`

Runtime 429：
- `503` 或 `429 RUNTIME_OVERLOADED`

非法状态：
- `409 SESSION_NOT_READY`
- `409 SESSION_ALREADY_RUNNING`

找不到资源：
- `404`

---

## 15. Health

```text
GET /health/live
GET /health/ready
```

Ready 至少检查：
- PostgreSQL
- Redis
- Runtime 可选（若 Runtime 强依赖）

建议：
- `live` 只检查进程活着。
- `ready` 检查服务依赖。

---

## 16. Metrics

最低：

```text
http_requests_total
http_request_duration_ms
runtime_requests_total
runtime_request_duration_ms
runtime_errors_total
redis_event_lag
sse_connections
live_session_count
utterance_count
utterance_failed_count
```

---

## 17. 日志

使用结构化 `slog`。

关键字段：

```text
requestId
traceId
sessionId
utteranceId
eventId
route
status
durationMs
```

禁止打印：
- API Key
- Token
- 用户敏感数据

---

## 18. 配置

最少：

```text
APP_ENV
HTTP_ADDR
DATABASE_URL
REDIS_URL
REDIS_RUNTIME_EVENT_STREAM
MINIO_ENDPOINT
MINIO_ACCESS_KEY
MINIO_SECRET_KEY
AI_RUNTIME_URL
INTERNAL_API_TOKEN
LOG_LEVEL
OTEL_EXPORTER_OTLP_ENDPOINT
```

---

## 19. Mock Runtime 支持

Backend 必须可通过：

```text
AI_RUNTIME_URL=http://<reachable-standard-runtime>:8000
```

运行。

Backend 测试不能依赖真实 GPU。

---

## 20. Unit Test

至少覆盖：
- Session FSM
- Utterance FSM
- Idempotency
- Runtime Error Mapping
- Event Dedup
- Event → State Update
- Start/Stop 非法状态
- Product Tool

---

## 21. 完成标准

Backend Agent 完成时必须：

1. `go test ./...` 通过。
2. OpenAPI Contract Test 通过。
3. 可以连接仓库标准 `integration/mock_runtime`。
4. Redis Event 能驱动状态更新。
5. SSE 能收到 Runtime 事件。
6. 无 GPU 依赖。
7. Docker 可启动。
8. 不修改 `contracts/**`。
