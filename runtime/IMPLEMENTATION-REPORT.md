# AstraLive Runtime 实施报告

日期：2026-10-06

## 已实现

1. FastAPI Skeleton：严格实现六个 Internal Runtime API 路由，`202` 接受响应、结构化错误响应和健康检查。
2. SessionManager 与生命周期：进程内创建、准备、启动、讲话、打断、停止；每个 Session 使用 `asyncio.Lock`，Go 仍拥有业务状态。
3. Speech Priority Queue：高优先级先执行，同优先级 FIFO；支持 `NONE`、`INTERRUPT_LOWER_PRIORITY`、`FORCE`。
4. generation_id Interrupt：打断时递增 generation、取消当前任务、清理 Mock Avatar/Media 缓冲，并在音频进入 Avatar/Media 前检查 generation。
5. MockLLMProvider、MockTTSProvider、MockAvatarEngine、MockMediaOutput：四个 Mock 开关全为 `true` 时无 CUDA/PyTorch 依赖。
6. EventPublisher：统一 `schemaVersion=1.0` Envelope、traceId 透传、唯一 eventId；Redis Stream `dh.runtime.events.v1`，失败重试与结构化错误日志；未设置 Redis 时使用内存发布器。
7. ToolClient：实现商品、库存、价格三个 Go Internal Tool API GET 方法，并校验 Tool Result 基本结构。
8. OpenAI 兼容的流式 LLM Adapter；LLM 失败时发 `RUNTIME_WARNING` 并使用输入文本 fallback。句子缓冲按标点、长度或等待时间将流式 token 送往 TTS。

## 验证

`PYTHONPATH=runtime python3 -m unittest discover -s runtime/tests -v`：8 项通过。测试覆盖创建/启动/停止、优先级与 FIFO、强制打断、低优先级不打断、旧 generation 丢弃、Mock 流、fallback、Session 清理、Redis Envelope 序列化和 Internal API 主要响应形状。

复用 `school-linux` 已运行的 `redis-server` 容器，在空 DB 15 上通过 SSH 隧道调用实际 `RedisEventPublisher`。验证了 `dh.runtime.events.v1` 写入与完整 Envelope 读回；测试事件与空 Stream 已删除，DB 15 恢复为 0 个 key。Runtime 不需要 PostgreSQL，因此没有创建数据库或容器。

## 初版报告时的集成边界（以下 WebRTC 与 Tool 缺口已由下节迁移处理）

- MockMediaOutput 是测试用音频接收器，不产生 WebRTC 浏览器预览。v1.1 已冻结 SDP/ICE 信令端点，见下节。
- 真实 TTS、轻量 Avatar、真实 Media Adapter、GPU 验证未实现。设置相应 Mock 开关为 `false` 会明确报错，Provider 接口保留。
- 已验证真实 Redis 写入和读回，但未运行 Go 消费端的跨服务联调。
- 初版 ToolClient 未接入编排；v1.1 由 Session Context 提供商品 ID，见下节。
- 完整 OpenAPI/JSON Schema 自动校验、指标采集及真实服务长时运行尚未验证。

## Contract v1.1 Migration（2026-10-06）

- `CreateRuntimeSessionRequest.context` 与 `RuntimeUtteranceRequest.source` 现在为必填；Session 保存 `roomId`、`systemPrompt`、可选 `activeProductId` 和 `knowledgeBaseId` 的快照。支持标准化 `PLATFORM_EVENT` 的可选 `platformContext`。缺失必填字段返回 422。
- LLM 请求使用 Session 的 `systemPrompt`，随后附加安全/事实约束和 Tool Facts。Runtime 只从 Session Context 取商品 ID；按问题调用 `get_product`、`get_product_stock`、`get_product_price`。Tool 返回不匹配或失败时发 `RUNTIME_WARNING` 并用自然降级话术；无 activeProductId 时普通聊天仍可用，商品动态事实不给猜测值。Runtime 不查询 LiveRoom 数据库。
- 新增 `POST /internal/v1/sessions/{sessionId}/webrtc/offer`，调用已有 `WebRTCMediaOutput.create_answer`。等待 Runtime ICE gathering 完成后返回完整 SDP；协商失败映射 `WEBRTC_FAILED`。Peer 属于 Session 的 MediaOutput，在 stop、disconnect、失败及 Runtime cleanup 时释放。Go/Redis 仍只传控制和事件，媒体由 Runtime Peer 直连 Browser。
- 保留现有优先级队列、同优先级 FIFO、`NONE`、`INTERRUPT_LOWER_PRIORITY`、`FORCE` 和 generation_id 丢弃机制；Mock 与真实 Provider 共用这套 Session 编排。未扩展 MuseTalk。

验证：`PYTHONPATH=runtime runtime/.venv/bin/python -m unittest discover -s runtime/tests -v`：23 项，14 通过、9 项真实模式按默认配置跳过。`RUN_WEBRTC_INTEGRATION=1 PYTHONPATH=runtime runtime/.venv/bin/python -m unittest discover -s runtime/tests -p test_webrtc_media_integration.py -v`：2 项通过，涵盖 HTTP non-trickle offer/answer、完整 ICE candidate、Session stop 清理及本地 Peer 音视频收流。迁移测试还覆盖 Context/source 422、Context 保存、systemPrompt、PLATFORM_EVENT、Tool 有/无商品及失败 warning、WebRTC 错误、Priority/FIFO 与三种抢占策略。

限制：上述 WebRTC 验证使用本机 aiortc Peer，未进行 Go 转发或真实浏览器跨主机连接；Runtime ICE candidate 的跨主机可达性仍需部署环境验证。全 Mock 的 `MockMediaOutput` 不生成 WebRTC Peer，若选择 WebRTC 预览须配置 `MOCK_MEDIA=false` 并安装媒体依赖；该组合仍不需要 GPU。`integration/` 下两个独立 Mock Runtime 不在本次允许修改的 `runtime/**` 范围内，其队列语义仍需所属模块迁移，不能用它们作为本次 Real Runtime 行为一致性的证据。

## Product Variant Fact Safety Patch

- 尺码词（S、M、L、XL、XXL、XXXL、数字码及“尺码”）触发 `get_product(activeProductId)`，读取并校验 `Product.sizes`；普通总库存问题走 `get_product_stock()`，价格问题走 `get_product_price()`。单纯“有 XL 吗？”不再误作库存查询。
- 尺码问题的 LLM Fact Context 明确列出所问尺码是否由 `Product.sizes` 提供、商品总库存及 `per_size_stock: unavailable`；禁止把总库存解释成 XL 等单尺码库存。`XL 还有库存吗？` 同时查询 Product 和 aggregate stock，但不产生单尺码库存事实。Tool API 和 Contract 未更改。
- Runtime Unit Tests：`PYTHONPATH=runtime runtime/.venv/bin/python -m unittest discover -s runtime/tests -v`，24 项运行，15 项通过、9 项需显式开启的真实模式测试跳过。新增测试覆盖“有 XL 吗？”、“有 XXXL 吗？”、“库存还有多少？”、“XL 还有库存吗？”及其他尺码路由。

## ISSUE-003 Product Fact Safety Final Patch（Runtime 侧已修复候选，等待 Integration 验证）

- 新增独立 `FactAnswerResolver`：Tool 查询后以结构化结果生成确定性口播；尺码存在性、商品整体库存、具体尺码库存边界以及单独价格问题直接送 TTS。普通聊天和无法确定性处理的复合问题继续走 LLM + Fact Context。
- 对可选尺码的库存提问，只说明商品整体是否还有库存，并明确没有该尺码单独库存数据；未提供的尺码直接回答没有该尺码。整体库存数量只用于商品整体库存回答，不绑定到具体尺码。价格 Tool 没有币种字段，回答只陈述返回的数值并说明币种信息不可用。
- 使用固定返回错误内容 `XL 有 27 件。` 的 Fake LLM 和 CapturingTTS 检查实际送入 TTS 的文本，覆盖 XL、XXXL、整体库存、XL 库存及价格；这些确定性问题未调用 Fake LLM，普通聊天仍调用 LLM。
- Runtime 全部 Unit Tests：`PYTHONPATH=runtime runtime/.venv/bin/python -m unittest discover -s runtime/tests -v`，25 项运行，16 项通过、9 项需显式开启的真实模式测试跳过。Integration 尚未验证。
