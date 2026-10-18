# Agent 3 — conservative COMMENT answer streaming handoff

交付阶段：可执行的隔离 Go 纯域模块 + CPU/Mock 验证，等待 Agent4 集成。正式 wire 编译、Agent2 真实 Authority/PG 和生产 Runtime/Guardian 接线尚未完成。Durable LIVE 保持关闭。

## 固定版本与所有权

- 安全同步基线：`e98d8cf53d1aa5518f9c908785b7a5feae5117f8`，在原 `AstraLive-agent-3` / `feat/v05-turn-manager` 上 fast-forward；原实现为 `ed2ebb235cb89e4b10b8a6f9670c6a1be00b1511`。
- 已测实现提交：`0db4b8eb49f7ae7c37818c8bd047f676cd3ba7be`。随后仅追加本交接说明；最终交付 HEAD 记录于增量 PR 描述。
- 冻结输入：`c7fd46209d3cbc6f58541dba8b4e1c85609c823e`，22文件 digest `3c0c317ed00f6fa4d2cf15ef3f61fc002d4bb22bf02d53ee9f1b407458bb28b1`，逐文件原字节不变。
- Agent4 正式 wire 依赖 SHA：**尚未提供**；没有复制 DTO、生成器、Schema 或正式序列化器。
- Agent2 真实 v2 Authority 依赖 SHA：**尚未提供**；没有 SQL/迁移/Outbox/Lease/Recovery 改动。
- 仅新增 `backend/internal/contentplan/answerstream/{language,scanner,artifact,stream_test}.go`、`backend/internal/turnmanager/answerstream/{coordinator,coordinator_test}.go` 以及 Agent3 文档/证据。既有业务入口、Scheduler、Runtime、Guardian 和 GPU 文件未改。
- 本轮增量 PR 面向 `integration/v05-durable-live`。旧 PR5 的 main 目标仅保留历史交付，不据其差异合并本轮内容。

## 已实现的纯域能力

`Language` 用可信商品投影的完整断言编译有限前缀语法，再逐字符识别实际流。正则只约束可支持的句法形态；实际生成文本还必须精确匹配可信词汇，标点/长度/LLM声称complete都不能授权。`Rule` 只能来自经过当前商品Tool核验的投影，不能从LLM抽取一句话后自行声称它受信。

支持完整价格/小数/单位、S/M/L/XL/XXL/2XL等尺码、库存/可用性、型号、重量、限定材质、已由Tool核验的比较关系、否定转折，以及用户尺码偏好if/then。未知改写、推广/配送等未支持关系、悬空条件、破碎否定、截断数字单位均拒绝。比较关系须本身由可信源核验，不能从LLM或旧商品名称推断。材质模板不附加未经证明的舒适/功效描述。

保留既有FactAnswerResolver的几个完整带空格文案，包括明确说明“币种信息暂不可用”的价格句。不得将现有Tool缺失的币种默认成CNY；只有可信投影有元/CNY依据时才能登记“元”的规则。只有两个固定非商品口播句允许空事实依赖。`AllowedTexts()` 可交给既有单个DeepSeek请求的提示词装配；不逐单元调用LLM。

`Scanner.Next(ctx)` 在完整生产式被识别时立即返回，不等provider EOF；一次只拉一个<=64字符slice，窗口满时不读取。关闭后不能继续消费已缓冲的下一句。`Builder` 对同值/同版本的完整依赖重新观察，生成实际正文Hash、稳定ArtifactId、前驱链、最终正文Hash和manifestHash；拒绝缺失/额外/变化/过期依赖和超长文本。正文不trim、不NFC、不添加分隔符。

`Encoding` 是Agent4唯一正式编码器的适配点：将不可直接JSON序列化的内部 `Draft` 映射至正式AnswerArtifact，Schema/语义验证后返回仅排除artifactHash的完整canonical bytes。Builder对这些bytes计算Artifact Hash并保留副本。测试编码器明确基于冻结fixture；它没有成为生产DTO或执行路径。

## Coordinator接线顺序与权限

外层先沿用原 Scheduler / SelectionAdapter / Manager 的去重、merged sources、TTL、公平预算和自然边界选择，完成同一COMMENT的Accept与可信Registration。向Builder提供已有Turn/Attempt/Utterance/Generation和完整command requestHash；后续单元不分配新身份、不再次AdmitTurn。

| 域方法/适配点 | Agent4/2后续映射义务 |
| --- | --- |
| `Source` | 复用既有DeepSeek流，一个provider任务；输入是原始decoded token slices，不先经legacy `sentence_stream()` 的逗号/长度fallback处理。Source必须遵守取消，Close须取消/唤醒读取；raw SSE frame须在解码前限制16KiB |
| `Facts.Observe` | 可信Product Tool预读；核验当前snapshot，返回完全相同kind/product/sourceVersion/valueHash的当前观察，不能伪造时间戳或替换事实；远程工作不占SQL事务 |
| `Executor.Check` | 可信当前Stop/epoch/Session/Binding/事实/期限预检；通过新的append-only同值FactObservation续期，不改旧Artifact，不以原Grant expiry中断已消费正常长句 |
| `PrepareNext` → `Executor.Prepare` | `JournalPrepareAnswer`，同一描述符和稳定key；预检后由Backend事务复核。CAS冲突在适配器内部读取当前revision后重试相同描述符；丢Prepare ACK可返回 `ErrPrepareUncertain`，域模块只重试同一Artifact |
| `StartNext` → `Executor.Start` | 首次 `AcquireOutputPermit` + 唯一 `JournalStart`；后续 `JournalStartAnswerSegment` 只在可信前驱drain之后。只能接受首次true授权响应，ticket留在受限适配器中 |
| `Executor.ConsumeOnce` | 原Receiver Consume/Backend latch/Guardian fsync首ACK/Runtime once-TTS完整链；不能把enqueue当消费成功，不能从query/retry恢复true响应。未知或丢ACK直接终止域协调器，保持权威UNKNOWN |
| `Drain` → `Executor.ConfirmDrain` | 真正 `ReceiverFinishUnit` 所绑定的Observer required ranges + Backend `JournalConfirmAnswerSegment` 已确认；无运行时自报的done布尔值入口 |
| provider EOF → `Executor.Seal` | 正式 `JournalSealAnswer`，精确顺序的manifest及无分隔符拼接的实际正文Hash；EOF只约束结束，不约束首句 |
| `Complete` → CONTROL `Completion.Commit` | 再由权威状态验证seal+全部连续required drain+无unknown tail，走现有CONTROL `ConfirmCheckpoint` 业务提交；COMMENT子单元不会直接推进商品Segment cursor或释放全局Slot |

`PrepareNext`一个owner，`Drain`可以并行，因此支持Prepare-before-Drain和Drain-before-late-Prepare。一个活动单元加一个lookahead、同一单元一次START/Consume尝试；32并发Start也不能复制效果。正常Drain只记单元状态。全局完成后原Manager读取权威投影，再仲裁下一未完成SCRIPT；本模块没有商品cursor、第二个Scheduler或Avatar队列。

Source是纯域接口，没有增加Token IPC/HTTP协议。现有DeepSeek执行位于Python；实际同进程/跨组件装配由Agent4统一决定，不能假定DTO交付等于Token流已接线。若需要Python纯语义模块，先由Agent4登记其路径；本轮未复制Python实现或修改共享Runtime入口。

## 资源上限与取消

| 资源 | 上限/策略 |
| --- | --- |
| 同一COMMENT的LLM任务 | 1，调用者装配；本模块不创建LLM请求/worker |
| 新Token队列 | 0，pull backpressure；若复用旧prefetch仍须<=8且每slice<=64字符 |
| Scanner pending / assembler | <=64 / <=240 Unicode字符，完整语义不能按上限裁剪 |
| 原始provider event frame | <=16KiB，须由Agent4流适配器在SSE/JSON解码前执行；本轮未改providers.py |
| 可信规则 | <=64商品规则+2固定非商品句，总字数<=8192；前缀冲突/重复拒绝 |
| 播放窗口 / pending Prepare | 1 active+1 lookahead / 1 |
| 单元与审计 | <=32单元，实际正文总和<=2000字符；估计单元时长<=6秒，过长拒绝，不强切 |
| 描述符 | 每canonical body<=64KiB，最多32份（<=2MiB body）；无音频缓存，外层request仍须独立<=256KiB |

调用者必须使用原command/TTL/Binding允许的有界context，并在Stop/epoch/商品切换/Binding失效时取消原provider及调用 `Stop()` / `Unknown()`，同时执行既有Backend/Guardian Stop编排。域Stop不可逆，关闭Source、不等外部RPC/Tool/Observer；在途回调返回后重新检查本地状态。没有内存Resume或自动fallback新AnswerId。原始异步PCM/GPU work必须在提交时捕获execution/Artifact/hash/ranges，不能从当前slot重新归属迟到Unit1；真实输出侧门由Agent4/5实现和验收。

重启只能由Agent2恢复合法持久状态。新建域对象没有执行权；其Adapter必须拒绝已STARTED/消耗/UNKNOWN任务。已确认前缀不重播，UNKNOWN不盲重播，不因队列空/流错误跳过商品段。CONTROL完成ACK丢失也进入歧义处理，不用本地重复Commit猜测成功。

## 验证与剩余门槛

见[完整测试报告](AGENT-3-STREAMING-TEST-REPORT.md)和[原始证据](agent-3-evidence/)。20个新增顶层域测试通过；含原模块与Scheduler共6包race通过、137契约、11Journal、两个validator和冻结fixture实际AnswerArtifact Hash检查通过。既有可选v1导出测试1 SKIP，最终0 FAIL。

正式DTO/Authority依赖固定SHA、正式wire编译、真实PG、真实Tool及身份装配、跨进程IPC/fsync/Guardian、Runtime实际once-TTS/媒体lineage、required-range drain、真实DeepSeek/TTS/GPU/Chrome/WebRTC/RTMP/观众及忙/闲首句SLA均待后续独立验收。新增检查和往返成本不可忽略；CPU阻塞EOF测试不代表首句秒数或SLA达标。

回滚只需不装配这两个新增包；没有默认入口或数据迁移。不要通过修改LIVE开关、冻结规范、Generation Fence、PCM/PTS/Credit或媒体协议使Mock交付变为生产可运行。
