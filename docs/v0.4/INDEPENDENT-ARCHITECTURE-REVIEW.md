# AstraLive v0.4 — 独立架构审查

审查者：Agent C。日期：2026-10-11。执行 `git fetch origin` 后，本地 HEAD 与远程 main 均为 `59d96c8818a4512651a2f945ced71278929c9e12`，与给定基线一致。工作分支：`audit/v04-interaction-gate`。没有修改、合并或强推 main。

**ARCHITECTURE REVIEW: PASS** — 修复后的单 Backend / 单 Runtime、已认证单操作员 MVP 源码与自动化范围。本轮真实五场景、正常分路径延迟和用户真人评审在限定范围内通过；繁忙期等待、长期可靠性和官方平台观众端仍有门槛。这个 PASS 不覆盖分布式、多用户 SaaS、崩溃恢复 SLA 或商业发布。

## 依据与范围

逐项检查了用户指定的 A/B 设计与验收文件、Frozen v1.1 Contract、Session Binding 的 Go/Python 实现、平台 Normalize/Mock Replay、Scheduler、Service/HTTP 调度桥、Runtime 分句/事实路由/TTS、InteractionPanel、Worker adapter/client 及 validated 接收/消费机制。执行了独立测试，复算已提交 JSON，核对私有原始浏览器 JSON 与可用 RTMP 观测尾部；没有把 A/B 报告中的 PASS 当作当前结论。

证据入口：[checks.json](evidence/independent/checks.json)、[源码修复前失败](evidence/independent/regression-before.log)、[权限失败](evidence/independent/ownership-before.log)、[延迟复算](evidence/independent/latency-recomputed.json)、[原始证据核验](evidence/independent/original-evidence-audit.json)。先执行真实独立 SQL/Redis + Fake/CPU 回归；用户明确授权空闲短测后，使用服务器已有缓存启动 Worker 软件，执行真实 DeepSeek/XiaoYa/RTX3080、Chrome 与本地 RTMP。没有启动/关停云实例、下载权重或中断其他 Session。详见互动和延迟报告。

## 源码确认的功能

| 模块 | 确认的真实实现 | 边界 |
| --- | --- | --- |
| 认证/资源权限 | Cookie 的 DB 哈希 Session、精确 Origin、tenant+user 资源 owner、授权先于 v1.1 幂等检查；内部 role token 分离 | 单操作员登录；A/B 信任身份测试不等于 SaaS 注册 |
| 配置/Provider Binding | immutable capture、版本/有效期、匹配 Worker/Avatar ACL、严格初始 readiness、安全公开摘要与私有凭据 resolve、Stop/release | DeepSeek + XiaoYa preset + SoulX；没有通用热切换 |
| Scheduler | trusted Mapping、Normalize 的稳定 source identity、限长、去重、合并、TTL、排名、容量/速率限制；只有 Selection 才进入 dispatcher | candidate/cache 是单进程内存；未选中候选在进程重启后丢失 |
| Go Session 调度 | 共用 Service 命令锁，投递前检查 live/busy/product/owner；Receipt 唯一键；原 Speak/Stop/FSM 接口 | 命令锁跨所有 Session，共享慢请求会造成其他 Room 等待 |
| Answer Router | 真实 Tool 事实 Fast Path 与真实 LLM streaming 分支；缺失数据明确 unavailable | `Product.sizes` 不等于 SKU 库存；关键词分类不等于通用语义理解 |
| 增量/背压 | 分句 queue=8、token slice≤64、常规分句约120字符、不可分片240字符显式失败；native PCM queue=8、每片≤40ms | upstream 单个 token/SSE line、native engine 内部分配仍不是总 RSS 硬上限 |
| 媒体/Worker | sample timeline、PTS、Generation Fence、session/epoch 验证、消费 credit、FORCE、未来语句边界恢复 | credit 表示真实 peer 消费或 FFmpeg pipe 完成写入，不是观众扬声器/平台播放 |
| UI | Mock 来源、候选/失败/合并指标、操作员接管与手动恢复、不足20样本隐藏分位数 | PRODUCT_EXPLAINING 依赖已有讲话；没有完整自动脚本场控 |

Legacy `/api/v1/dev/platform-events` 按 Frozen Contract 直接创建 priority80 / INTERRUPT_LOWER_PRIORITY Utterance，开发环境保留。它不是新 Scheduler 的 Adapter 入口，不能把这个兼容例外描述成所有 COMMENT 均受 Selection 控制。

## 发现、复现和最小修复

| 编号/级别 | 修复前行为 | 最小修复与证据 |
| --- | --- | --- |
| C-01 **P0** 权限缓存 | Controller 创建后撤销 Room owner，Session owner 仍有效；Ensure 复用缓存，dispatcher 仍请求 Runtime | 缓存复用与最终 Dispatch 都重新检查 Room owner。[ownership-before.log](evidence/independent/ownership-before.log) 证明未授权请求到达 Fake Runtime；新 `cached_controller_rechecks_room_ownership` 回归通过 |
| C-02 **P1** 选中后 TTL | Tick 在 TTL 内选中，等待 Service 命令锁跨过 TTL 后仍创建 Utterance | 获锁后以本机 ReceivedAt+TTL 创建 deadline，先拒绝已到期请求，后续 SQL/HTTP 也受 deadline 约束。失败测试显示修复前1个 Utterance/1次 Runtime；修复后0/0 |
| C-03 **P1** 错误合并/尺码遗漏 | 单 XL 与多 XL/XXL 合并；2XL 与整体库存合并；价格+库存、材质+库存、名称+价格等丢失后一个问题；Runtime 未识别2XL | 识别完整有边界的尺码列表/数字码；多个事实或复杂咨询保留完整问题 key；Runtime 支持2XL等显式标签，避免嵌入型号误识别。保留简单同类问题合并。[compound-before.log](evidence/independent/compound-before.log)、Python 失败证据与新增回归 |
| C-04 **P1** Replay 取消竞态 | Receive 在锁外检查取消，等待锁后仍追加候选；Adapter.Stop 仅 cancel，返回时 sink.Receive 可能未结束 | Receive 获锁后再次检查 ctx；Mock delivery mutex 使 Stop 先 cancel 再等待在途投递结束。[replay-before.log](evidence/independent/replay-before.log) 与可控阻塞 sink 回归 |
| C-05 **P1** 中文朗读内容改写 | `尺码有 XL、XXL，型号 S，长度 20 M，容量 5 L` 的后半句字母也被转换 | 仅转换明确尺码标签和实际连续尺码列表，列表遇到其他描述就结束。[pronunciation-before.log](evidence/independent/pronunciation-before.log)；129.90元/500毫升/英文单位/型号保留测试通过。真人读音/听感由用户确认通过 |
| C-07 **P1** 空闲评论轮询等待 | 原轮询和自动口播最小间隔都用2秒，空闲评论额外等待接近2秒 | 独立 `INTERACTION_POLL_MS=100`；自动口播最小间隔仍2秒；无候选且无需恢复模式时跳过空闲SQL。新候选/手动恢复通过单槽非阻塞通知立即唤醒；100ms定时器只负责忙状态/间隔兜底。小时定时器下500ms admission 回归修复前失败、修复后通过；Tick频率回归保证1.9秒内仍仅1次自动口播。见 poll-latency-before/final.log、wake-before/after.log |
| C-09 **P1** 首个完整短分句等待 | 已有完整中文价格分句，但不足20字符的逗号不分句，继续等待后半问答 | 仅首个中文逗号短分句达到8字符即可启动TTS；后续/ASCII逗号规则不变，数字分隔符保护不变，有界queue/取消保持。first-clause-before.log 复现等待Timeout，159项Runtime回归148PASS/11SKIP。真实收益独立复测，不改变首次关联音画统计定义 |
| C-08 **P1** 每次问答关闭连接 | 每次 DeepSeek streaming 新建/关闭 HTTP transport，重复连接开销 | Session 独享单连接、有界池、60秒keepalive，Stop/准备失败/close关闭；旧通用Provider路径仍按请求关闭。`llm-pool-before.log` 证明回答一次就关闭；两次回答复用及Stop关闭回归通过。池复用不保证供应商首token达标 |
| C-06 **P2** UI观测范围措辞 | 面板仍硬编码“浏览器/RTMP完整同步回复延迟尚未测量”，容易与历史20样本档案混淆 | 改为“此面板不展示…”：准确表明当前UI数据范围，未把Go选中延迟伪装成观众回复延迟；既有前端回归更新并通过 |

修复集中于调度/权限与文本识别，没有重构 SoulX/TTS/Session 媒体系统。未修改 Frozen Contract、生成 DTO、GPU binary protocol、validated 文件、PCM/PTS、消费 credit、FORCE 或绑定版本规则。修复前日志中，权限测试后的 Stop 数量断言失败是未授权请求增加总调用数导致的连带失败，不是又发现 Stop 会创建新任务。

## Receipt 与崩溃语义

`PRIMARY KEY(session_id,trace_id)` 加 `ON CONFLICT DO NOTHING`，任何已存在的 RESERVED/ACCEPTED/FAILED 都拒绝再次自动投递。新 SQL 回归分别覆盖三状态，另覆盖“Fake Runtime 已收到请求，但 Backend HTTP acknowledgement 超时”：仅1次请求，Receipt FAILED，第二次投递被拒绝。没有引入自动重试。

| 故障窗口 | 当前行为/风险 |
| --- | --- |
| RESERVED 后、Runtime 前崩溃 | 保留 reservation，重启不再投递；回复可能永久丢失 |
| 创建 Utterance 后、Runtime 命令前崩溃 | 可能留下 QUEUED orphan；busy gate 会阻塞后续自动选择，需要可靠对账或操作员 Stop/新 Session |
| Runtime 已接收，Backend 超时 | Backend 可能 FAILED，而 Runtime 仍口播；后续 Runtime FSM 事件可能无法推进该 FAILED 行；投递结果有歧义 |
| Receipt 更新使用的 ctx 已取消 | 行可能继续 RESERVED，而不是得到 FAILED；唯一键仍阻止重复自动投递 |
| Backend 重启 | 候选/模式/最近评论/Replay 状态不恢复；持久化 receipt 只保护相同已保留 trace 的自动任务 |
| 双 Backend / 双 Runtime | Go mutex/limiter/busy 检查及 Worker admission 不具有跨实例协调；本轮没有测试或接受 |

这是带丢失风险的自动任务 at-most-once 策略，不是 exactly-once，也不是完整重启恢复。不同 source IDs、不同 Session 或超过短期内存去重窗口的输入，不能依赖该策略获得无限期语义去重。对账/恢复与全输入 durable identity 需另行设计；本轮不以可能重复口播的无限重试掩盖问题。

## 安全复验

独立 formal CPU 测试使用真实 SQL/bcrypt/加密、可信测试 A/B 身份、CSRF、控制 HTTP、Redis→SQL→SSE：匿名401、其他用户404、hostile Origin403、大量 Mock users 输入422、Legacy202/Stop后409、binding不变、Stop后删除私有 capture。新 Room 撤销测试覆盖 Controller 缓存与最终投递。既有 Runtime token role/production gate、公开 profile secret 投影、SSRF/Worker ACL 回归全部执行。

`h.Env == production` 时不注册 v1.1 dev 和 v0.4 Mock/Replay 写入口；Interaction 读取/模式仍需 ProductAuth + owner。评论内容不进入 Prometheus 标签：interaction 仅 outcome enum，HTTP 使用路由模板。公开 Provider 摘要白名单不包含 API Key/Runtime token/物理端口。不能由这些 CPU 检查推出线上代理配置/全日志/所有异常输入绝对安全。

全栈资源边界仍有限制：Scheduler 队列/缓存有上限，Runtime 的 `seen_utterances` 保留 Session 内完整输入直到 Stop；native 无 callback 的挂起不可由 Python 安全强杀；SQL receipts/idempotency 的长期 retention/清理与 body 慢上传防护需要生产运维门槛。短负载没有证明长期内存不会增长。

## A/B 回归结论与剩余问题

Agent A 的 binding/权限/版本/Stop、Worker admission 与媒体 CPU 回归通过；Agent B 的 formal 调度、去重/合并/TTL、Replay、事实/增量/背压回归通过。发现并修复的是合并基线中的实际缺口，而不是重写 A/B 功能。新真实正常回复、忙主播、随机输入/突发、商品切换、FORCE、Replay取消和headless RTMP均完成。没有观测到绑定漂移或新的媒体Fence回归；用户确认录像与六组音频的读音/音画同步/唇形均通过，原始答复保存在 human-review.json；最新性能复测录像另列。

仍未满足：忙主播默认不抢占，真实等待约17–19秒；短时正常分路径指标不构成持续服务SLA；完整 crash/orphan 对账、长期真实混合负载、真实平台观众端和商业安装恢复仍未验收。跨主机clock现在保存原始request/response bracket，复算严格上下界；音频为顺序任务结束后首个 analyser peak，仍不是带trace编码的物理扬声器观测。初次空DB并发 migration/legacy 缺表失败保留，初始化一次性schema后全量通过。

商品切换审查最初直接伪造含新商品的Selection，绕过真实Scheduler固定商品快照，错误地产生失败；改为真实链路fixture后，现有Gate会清旧候选并要求新Session，无需修复。手动小时定时器导致的中间fixture失败也保留。不可把 `product-switch-before.log` 当成真实生产缺陷或宣称已修复此项。
结论与下一步见 [INTERACTION-REVALIDATION](INTERACTION-REVALIDATION.md)、[LATENCY-REVALIDATION](LATENCY-REVALIDATION.md)、[NEXT-PHASE-READINESS](NEXT-PHASE-READINESS.md)。

剩余P2观测口径：Scheduler.SelectedAt沿用Tick入口的now，gate SQL耗时被归入selected→speakable，不是精确的选择决策完成时刻。立即唤醒组约0.03–0.07ms只表示Tick入口等待；端到端comment receipt→关联音画与clock上下界不受此stage归属影响。本轮未改此历史指标定义。

连接池的最后检查发现关闭连接被取消可能跳过release，保存pool-release-before.log并用finally保证正常Stop和失败清理都释放；159项Runtime回归通过。该取消分支是最终真实测试之后的CPU-only局部回归，正常Stop已在10个真实Session验证，没有为测试取消而中断共享Worker。
