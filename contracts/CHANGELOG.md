# Contract Changelog

## Personal media v0.3.1 — additive contract freeze (2026-10-09)

- 补齐独立 AvatarProfile、VoiceProfile、AssetStorage 三项共享契约及统一交付索引 `PERSONAL-ASSETS-HANDOFF.md`。
- 冻结私有上传/规范化/预览、异步 Job 与 Worker claim/输出校验、Provider 能力差异、租户及用户隔离、原子会话版本快照。
- 增加 `personal-assets/schema.json`、生成 TypeScript 类型、Go DTO/接口及严格参数/真实 readiness 校验；现有 v1.1 和 user-config v0.3.0 wire 不变。
- 新 HTTP 路由明确标记 CONTRACT_ONLY；契约与迁移设计完成不代表上传服务或真实模型端到端验收完成。

## v1.1.0 — Cross-module migration (2026-10-06)

- **CCR-001 resolved:** Control OpenAPI requestBody/response component 符号统一为不与 schema 冲突的 `*Body` / `*Result`；Route 与已有 JSON wire format 不变，可直接输入 oapi-codegen。
- **CCR-002 COMMENT path resolved:** 保留公共 dev Platform Event 路由；Go 按 `roomId` 找 LIVE/DEGRADED Session，将 COMMENT 标准化为优先级 80、`INTERRUPT_LOWER_PRIORITY` 的 `PLATFORM_EVENT` Utterance，经现有 Runtime Speak 路由发送；无活动 Session 返回 `409 SESSION_NOT_RUNNING`。
- 增加 LiveRoom 可选 `activeProductId` 与必传 Runtime Session Context 快照，包含 `roomId`、`systemPrompt` 和可选商品、知识库 ID；Runtime 不查询 LiveRoom 数据库。
- **CCR-004 resolved:** Runtime 从 Session Context 获得商品 ID，动态商品事实从已有 Go Tool API 查询；缺少上下文或 Tool 失败时不猜测事实，失败发布 `RUNTIME_WARNING`。Tool Result wire format 不变。
- **CCR-003 resolved:** 增加 Public/Runtime WebRTC offer/answer 路由，采用 non-trickle ICE，仅 Go 转发 SDP，Browser 与 Runtime 直传媒体。
- SSE heartbeat 明确为显式 `event: heartbeat` 与 UTC `timestamp`，不进入业务 Event Timeline。
- Mock Runtime 必须与 Real Runtime 的 Priority Queue、FIFO、抢占策略及两个 FSM 保持语义一致；Integration Acceptance 不得以不一致 Mock 证明 Real Runtime。
- Knowledge document/index Worker 与高级 Avatar preprocessing 标记 **v0.2 deferred**，不阻塞 v0.1 核心链路验收。
- **CCR-005** 保留为历史实现符合性审计记录，本版不更改其 wire format。

兼容性：Public 现有路由与既有成功载荷保持兼容；内部 Create Session 的 `context`、Speak 的 `source` 为新增必填字段，旧 Go/Runtime 实现需同步升级。新增 WebRTC 路由与 LiveRoom 字段是扩展。Runtime Event `schemaVersion` 保持 `1.0`。

## v1.0.0 — Contract Frozen (2026-10-06)

- 冻结已在 `CONTRACTS.md` 定义的 React ↔ Go 与 Go ↔ Python Runtime 路由、HTTP 状态、核心 DTO、状态枚举、错误码和幂等请求头。
- 冻结 Runtime Event、开发用 `COMMENT` Platform Event 与 SpeechPlan 的 JSON Schema，附带可校验示例。
- 将 KnowledgeBase 路径参数统一为现有 ID 命名规则 `knowledgeBaseId`；明确商品 Tool API 属于 Go，而非 Python Runtime。
- 明确 `SESSION_READY` → Go `READY`、Go 发送 Start 前进入 `STARTING`、`SESSION_STARTED` → Go `LIVE`，保持现有 FSM 转换不变。
- 将 Runtime Health 的 `activeSessions`、`providers` 与 Runtime 要求对齐；开发用 Platform Event 以 `CONTRACTS.md` 的完整请求为准。
- WebRTC SDP/ICE 信令、Avatar 完整状态枚举、KnowledgeBase 创建字段/查询路由/文档内容格式、Dashboard 聚合查询路由、非 `COMMENT` 平台事件 payload 尚无上游定义，须经 CCR 后扩展；本版不虚构这些字段或枚举。

校验：两份 OpenAPI 3.0.3 文件通过 `openapi-spec-validator`；三份 Draft 2020-12 JSON Schema 通过 `jsonschema` 元 Schema 校验，示例通过实例校验。
