# AstraLive Go Control Plane 实现报告

日期：2026-10-06

## 实现范围

- `backend/**` 内完成 Go 服务骨架、环境变量配置、结构化日志、健康检查、Prometheus 指标与 Docker 构建/Compose 文件。
- PostgreSQL 迁移建立 `avatars`、`voices`、`products`、`knowledge_bases`、`knowledge_documents`、`live_rooms`、`live_sessions`、`utterances`、`jobs`、`runtime_events`、`idempotency_keys`。业务 CRUD 通过 sqlc 生成的 pgx 查询层访问。
- 从冻结 OpenAPI 生成 Control/Runtime 类型；公共请求按内嵌 OpenAPI 校验必填字段、枚举与结构，统一输出 Envelope、错误码和 UTC 时间。
- 实现 Avatar、Voice、Product、LiveRoom、LiveSession、Job、KnowledgeBase 基础路由，Session/Utterance FSM、Runtime HTTP Client、Redis Stream consumer group、eventId 去重、成功后 ACK、失败重试与 DLQ、SSE 快照/最近事件/实时事件/心跳、指定异步接口的 Idempotency-Key、带 Bearer token 的内部 Product Tool API。
- 原 `backend/cmd/mock-runtime` 已在 ISSUE-004 中移除；仓库唯一标准 Contract Mock 为 `integration/mock_runtime`。

## 验证

1. `go test ./...` 通过；含 FSM、非法 Start/Stop、Runtime 错误映射/超时、事件结构、SSE、Product Tool 鉴权与库存、冻结 OpenAPI 输入/输出，以及在 `DATABASE_URL` 可用时运行的 PostgreSQL 事件去重和状态更新测试。
2. 使用 `school-linux` 的**现有** `postgres` 和 `redis-server` 容器：新建独立数据库/角色 `astralive_backend`，使用原本为空的 Redis DB 14。经 SSH 隧道运行 Backend 与 Mock Runtime，`python3 tests/smoke.py` 通过：Migration、资源 CRUD、Session `CREATED→PREPARING→READY→STARTING→LIVE→STOPPING→ENDED`、讲话事件到 SSE、Interrupt、Start/Stop/Utterance 幂等重放及 body 冲突、内部商品库存/价格查询。
3. `/health/ready`、`/metrics` 返回成功；缺少 Product 必填字段与非法 Utterance 枚举均返回 `422 INVALID_ARGUMENT`。
4. 在 `school-linux` 使用本地交叉编译的 Linux 二进制构建了临时运行镜像 `astralive-backend:localtest`，容器内部 `/health/ready` 返回 `{"status":"UP"}`；测试容器已停止。标准多阶段 Dockerfile 的远端构建遇到 Docker 镜像代理 `docker.m.daocloud.io` 的 EOF，未验证该 Dockerfile 在该主机上完成拉取与 Compose 启动。

## v1.0 实现时的冻结契约限制（历史记录，见下方 v1.1 Migration）

- [CCR-001](CCR-001.md)：当时 OpenAPI component 同名，直接生成失败；v1.1 Contract 已修复，本次迁移已删除私有改名副本。
- [CCR-002](CCR-002.md)：当时 COMMENT 输入协议未定义；v1.1 已冻结并完成 Backend 投递路径。Knowledge 文档载荷及高级 Job 执行仍为 v0.2 deferred。
- 当时公共 WebRTC 信令缺失；v1.1 已实现 Backend SDP 转发。浏览器媒体预览和一小时连续运行仍未验收。

## 操作与清理

- 运行说明见 [README.md](README.md)。本地集成凭据在 `backend/.env.integration`，权限 `600`，被 `.gitignore` 排除；报告不记录密钥。
- 临时本地 Backend、Mock Runtime、SSH 隧道和远端测试容器已停止。`school-linux` 上新建的独立 PostgreSQL 数据库/角色及原 Redis DB 14 保留供后续联调；原有容器未改动。

## Contract v1.1 Migration（2026-10-06）

### 修改内容

- OpenAPI 类型直接从冻结的 `contracts/control-api.openapi.yaml` 和 `contracts/runtime-api.openapi.yaml` 生成；删除 Backend 私有改名版。请求校验使用与 Control Contract 字节一致的嵌入副本。更新 CCR-001 之后的生成类型引用。
- 增量 migration `000002_live_room_active_product.sql` 为 `live_rooms` 增加可空且关联 Product 的 `active_product_id`；更新 sqlc 查询和生成模型，以及 LiveRoom 创建、更新、读取 DTO。创建 Runtime Session 时从 LiveRoom 生成包含必填 `roomId`、`systemPrompt` 和可选 `activeProductId`、`knowledgeBaseId` 的 Context 快照。
- Runtime Speak 命令发送 `source`。普通控制台请求沿用其 `source=OPERATOR`；dev COMMENT 查找该 Room 当前 `LIVE`/`DEGRADED` Session，创建 `priority=80`、`interruptPolicy=INTERRUPT_LOWER_PRIORITY`、`source=PLATFORM_EVENT` 的 Utterance，附标准化 `platformContext` 并经既有 Runtime Speak API 投递；无活动 Session 返回 `409 SESSION_NOT_RUNNING`。
- 公共 WebRTC offer 路由仅接受 `LIVE`/`DEGRADED` Session，将完整 SDP 送至 Runtime 内部 offer 路由并将 answer 包装成公共 Envelope；Go 仅处理 SDP。SSE 心跳改为显式 `event: heartbeat` 和 UTC ISO-8601 `timestamp` JSON。
- 保留并补测三个内部 Product Tool GET 路由。

### 测试结果

- 在 `backend/` 运行 `go test ./...`：**PASS**。新增测试覆盖 Runtime Create Context 和 Speak source、COMMENT 409/202 及 Runtime 投递字段、WebRTC 状态门禁/SDP 转发与公共 answer、显式 UTC heartbeat、Product Tool 三条路由。
- 重新运行 OpenAPI 和 sqlc 生成命令成功；`generated/openapi/control.openapi.yaml` 与冻结 Control OpenAPI 字节一致。
- 本轮没有提供 `DATABASE_URL`，需要真实 PostgreSQL 的既有集成测试按原有条件跳过；未运行跨服务浏览器/WebRTC 媒体验收。

### 未完成问题

- 原 Backend Go Mock 已移除；`integration/mock_runtime` 是仓库唯一标准 Contract Mock，其 Mock 媒体模式不能完成浏览器预览验收。真实 Runtime 的 SDP/ICE 可达性、音视频以及端到端长时运行仍需联调验证。
- Knowledge document/index 和高级 Avatar prepare 按 v1.1 Contract 属于 v0.2 deferred。原报告的 CCR-001/002 限制是迁移前历史记录，不再代表本次已冻结的 COMMENT 和代码生成路径。

## ISSUE-004：统一 Mock Runtime（2026-10-06）

- `backend/cmd/mock-runtime` deprecated/removed。仓库唯一 Contract Mock：`integration/mock_runtime`；Backend 不再维护第二套 Mock 行为。
- Backend Dockerfile 只构建 `/server`；`backend/compose.yaml` 不再启动旧 Go Mock，须通过 `AI_RUNTIME_URL` 连接已启动且容器可达的 Runtime。标准 Mock 栈由项目根目录 `scripts/integration-test.sh mock` 启动；本地脚本为 `scripts/run-local-v11.sh mock`。
- Backend 单元测试使用现有 RuntimeClient HTTP stub 和 `fakeRuntime`，不依赖已移除的 Go Mock 命令。
- 在 `backend/` 运行 `go test ./...`：**PASS**。搜索 `backend/**` 后，仅历史报告保留旧命令名称以记录废弃事实；README、Compose、Dockerfile 和测试入口均不再使用它。
