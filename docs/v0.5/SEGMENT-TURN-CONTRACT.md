# durable-live-1 Segment / Turn 合约

Agent 3 在新增 `backend/internal/contentplan/`、`backend/internal/turnmanager/` 实现策略；复用 `interaction.Scheduler` 选评/去重/TTL/限流，不新建第二个 Comment Scheduler。持久化仅通过 Agent 2 的 `backend/internal/durablelive/` seam，所有字段以独立机器 Schema 为准。编译 DTO 可由 Schema生成或在最终集成时加入无实现的 `backend/internal/livecontract/`；不能各自手写不一致 DTO。

## 计划与分段

ContentPlan 对应固定 runId/productId/productSnapshotVersion/revision。snapshot 保存无凭据的商品identity、名称、描述、规格及事实来源版本；productSnapshotVersion=规范 snapshot JSON 的 sha256。revision在run内递增，新 revision 必须新 planId。segmentOrder 是segmentId有序完整列表，与 sequence1..N 一致；禁止隐式 SQL created_at 顺序。

每段一个自然语义，目标预计2–4秒。采用句子/完整从句及语义解析；数字、129.90元、满199减20、500毫升、尺码列表、否定范围、条件和结论必须保持完整。超过目标需在生成/改写阶段重新规划，不能在TTS PCM、字节或固定音频秒数上截断。预计超过6秒的不可分段不允许自动脚本准入，返回 SEGMENT_TOO_LONG 要求replan；短于2秒的完整语义允许。duration只是估计，真实速度另测，不保证边界延迟上限。

Segment 内容不可变。修正文本/事实必须新 segmentId、新 textHash、新幂等键和新 plan revision；已投递attempt保留原值。idempotencyKey=`segment:<segmentId>:initial`；获授权的新执行attempt用独立键，不把传输重试当新执行。Segment.state=READY/ACTIVE/COMPLETED/INTERRUPTED/UNKNOWN/INVALIDATED；checkpointState 独立保留证据阶段。READY→ACTIVE由claim；ACTIVE→COMPLETED/INTERRUPTED/UNKNOWN依证据；READY→INVALIDATED依商品/版本变化；UNKNOWN仅经对账到COMPLETED/INTERRUPTED或保持；终态不复活。旧文本永不直接改写成新商品内容。

价格、币种、库存/可售性、促销门槛/有效期、配送承诺、SKU库存等有时效的断言必须在开始播放前重新校验。初版现有Tool只提供整体price/stock/product.sizes；SKU库存/促销/配送无权威Tool时不得宣称。每个段必须声明 factDependencies（未知依赖一律按需重新核验），远程取事实在事务外，结果附productId/version/validatedAt/expiresAt。dynamic事实最多缓存2秒，Runtime副作用前再次检查时间和当前商品版本；超过2秒或排队过期拒绝 NO_EFFECT，不带旧值开始播放。变化则废弃未派发段并新建plan revision；已经讲话的事实不能撤回，记录发生时间，不承诺外部库存不再变化。把缺失数据转成明确不可查询答复需新内容身份。

SCRIPT_TEXT 执行必须直接合成已冻结 content，textHash一致，不经旧 `_process` 的LLM回答重写。COMMENT_QUESTION 可调用现有事实路由/LLM/TTS，实际回答文本与hash在合成前写attempt journal；评论输入hash不冒充生成回答hash。Runtime的新执行wrapper由最终集成Agent接线。

## 自然边界与仲裁

一个 run 同时最多一个具有准入权的媒体 Turn；Runtime最多投递一个业务段。允许提前准备下一段文本，不能提前commit下一段媒体或将完整长稿作为一个Utterance灌入队列。边界=当前段 COMPLETED（本地全required drain+事务提交），或 INTERRUPTED 且输出屏障已证实；TTS完成、enqueue完成、HTTP202均不是让出条件。

优先级：Stop > 显式OPERATOR/FORCE > SYSTEM emergency > 已由Scheduler选中的有效COMMENT > SCRIPT。普通COMMENT始终在边界换权，不自动FORCE。COMMENT通常priority40..80，SCRIPT20，OPERATOR100，SYSTEM emergency95；优先级不赋予授权。现有legacy v1的priority/interrupt行为不变。

到边界最多连续回答2个选中评论，或评论话轮累计已用本地执行时间达到8秒，随后在SCRIPT就绪时至少播放1段；预算是下一话轮准入约束，不强行截断当前回答。脚本段完成后重置预算。OPERATOR override直到显式Resume；Stop/紧急SYSTEM可随时打断，但下一段必须等fence确认。评论有效期沿用 ingress receivedAt+Scheduler配置TTL，不在恢复时重置；过期READY/WAITING进入INTERRUPTED(EXPIRED)。UNKNOWN attempt保留slot直到屏障已证实，不得把UNKNOWN当空闲。

Scheduler Selection → durable Turn 持久接纳成功后才算 delivered；收到同selection重试返回同turn。合并评论必须保留每条稳定身份 `(platform, platformRoomId, sourceEventId)`，唯一范围tenant+owner+run；sourceCommentTraceId仅correlation，不能单独防跨Session重答。没有sourceEventId的输入首次持久 ingress 分配 receiptId，重试必须携带它；无稳定重放身份不承诺跨重启去重。未选中候选仍是有界内存、重启可丢失；P0保证范围是已持久接纳的话轮，不承诺保留所有弹幕。

YieldAtSegmentBoundary 只持久登记让出请求；边界未达返回 WAITING，不能推进cursor。boundaryId=已提交 COMPLETED/INTERRUPTED checkpointId，重复返回同结果；非法/过期plan或已被消费边界返回BOUNDARY_CONFLICT。SCRIPT游标是当前plan连续已完成sequence的最大前缀，不能以最高完成编号跳过未知段。评论不推进script cursor。切plan时保留历史cursor；暂停后先 RestoreContentPlan 再 Resume，不凭Python队列猜进度。

## Agent 2 / 3 调用顺序

RestoreContentPlan(一致性只读快照) → Agent 3选择候选 → ClaimNextTurn(Agent 2原子校验并占slot) → DispatchTurn(返回已持久intent，不等待HTTP) → Agent 2 dispatcher执行 → ConfirmCheckpoint(Agent 2收证据) → YieldAtSegmentBoundary(Agent 3调度下一话轮)。ClaimNextTurn收到candidateTurnId，策略由Agent 3决定，存储层验证资格并CAS；冲突返回409，Agent 3刷新后重选，不能绕过已有slot。完整操作请求/响应、revision、errors均在protocol.json，不需自行猜签名。
