# Content Planner — Agent 3 / durable-live-1

基线 main `7fe5d24810e2df348c58dd7748e97ffbe5cff384`，已含契约交付 `ae28144d15afcf0e5f5ea8fa425fc42d27fc047b`。实现为 `backend/internal/contentplan/`，没有网络、SQL、LLM或媒体副作用。

`Build(Input, Config, now)` 消费 BroadcastRun、可信 ProductSnapshot、预分配 planId、递增 revision、可信 Statement、主播风格和目标总时长，返回冻结的 PlanBundle。默认模板只引用商品名称、描述、尺码，不自行补价格、SKU库存、优惠或配送承诺。`natural`使用配置的合句目标；`concise`将合句目标限制为2秒。目标总时长只在完整段边界裁剪计划；可信内容不足时返回更短计划，不重复已确认内容凑时长。后续如接 DeepSeek，只允许在计划生成阶段生成并核验完整文本，播放阶段不逐段调用LLM。

计划保存前生成一次 planId；修改商品、内容、风格或长度必须分配新 planId/revision。segmentId为域、planId、sequence、精确文本的JSON tuple SHA256；相同计划重建稳定，跨计划隔离。textHash严格按UTF-8原文计算；不做NFC、空白或标点归一。初始幂等键为`segment:<segmentId>:initial`。sequence从1开始；segmentOrder完整有序；utteranceId由Agent2 Claim后绑定。

所有wire字段由 `contract/generate.py` 机械生成，源为唯一冻结Schema，包含Schema hash；20个operation的全部请求/响应示例做无损round-trip。该Go包提供字段形状，不能替代Agent2入口的Schema、角色、跨字段和事务校验。未新增另一套共享协议，Agent4可将其替换为统一生成包的alias。

动态断言在可信输入声明 FactDependency；规划阶段检查来源、商品、有效期。关键词规则仅是额外防误用检查，不声称通用事实识别。未声明价格/库存/促销/配送断言拒绝；当前Tool无权威SKU库存、优惠和配送数据，这三类即使声明依赖也拒绝。SIZE_OPTIONS只表示可选尺码，不能推导尺码库存。

播放前Facts适配器重新查询当前商品版本与原断言valueHash；变化必须新建计划。动态事实有效期最多2秒。Manager预检与Runtime effect-start二次核验均必需。Claim请求没有附加事实字段，Agent2/4必须在事务外取事实、在短事务内CAS重检并把新鲜且同值的依赖绑定进不可变命令，不能使用计划创建时已过期的时间戳直接播放。实现细节及接线缺口见[交接](AGENT-3-HANDOFF.md)。
