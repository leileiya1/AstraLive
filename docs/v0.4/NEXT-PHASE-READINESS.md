# AstraLive v0.4 — 下一阶段准备度

独立审查基线：fetch后main `59d96c8818a4512651a2f945ced71278929c9e12`。交付分支：`audit/v04-interaction-gate`。本轮源码审查、失败复现、局部修复、独立SQL/Redis集成、Go/race/vet、Runtime/GPU CPU、前端与Frozen Contract回归均已完成。完整资料见其他三份独立报告及 [checks.json](evidence/independent/checks.json)。

| 最终门槛 | 状态 | 适用范围 |
| --- | --- | --- |
| **ARCHITECTURE REVIEW** | **PASS** | 修复后的单实例、单操作员MVP源码和自动化；无未修复的新P0发现；并非商业可靠性认证 |
| **INTERACTION INTEGRATION** | **BLOCKED** | formal CPU集成PASS，原20条真实JSON复算；当前真实忙主播/随机到达场景未独立复跑 |
| **END-TO-END LATENCY** | **BLOCKED** | 总体P50误差上界3193.64ms、clock/audio证据限制；已有LLM六样本子门槛FAIL |
| **MEDIA REGRESSION** | **BLOCKED** | CPU媒体/PTS/fence/credit回归PASS；当前真实GPU/Chrome/RTMP与新版尺码朗读主观复验未执行 |
| **NEXT PHASE READY** | **CONDITIONAL** | 可进入受限设计和CPU开发准备；不建议宣布v0.4完整真实验收或商业发布已通过 |

## 现在可作为基础的能力

A提供的 immutable Provider/商品Context、真实Go Session生命周期、owner授权、安全摘要、媒体Fence/PTS/credit；B提供的 trusted Adapter Mapping、Normalize、有限候选、选择与Dispatcher桥、事实Fast Path、LLM/TTS增量背压、trace和手动override/resume。新审查补齐了Room缓存授权、晚TTL、复合问题/2XL、Replay quiescence和尺码朗读误改单位。

独立总计：Go58顶层/87含子测试通过、1skip；Runtime145通过/11skip（156 total）；GPU CPU21通过；Contract/guard/marker7通过；前端40通过与build成功。这些是真实执行的自动化，不是真实vendor inference。P0权限失败到修复的证据与最小变更都在分支上可审阅。

当前GPU服务器只读preflight显示17087/17088未监听，GPU1MiB/0%，不存在可直接短测的READY Worker。虽然用户授权空闲时短测，本轮没有启动、恢复或中断Worker/实例，也没有重新下载模型。新增真实门槛保持BLOCKED，不能引用A/B先前“留下READY”的描述当作现在状态。

## 自动口播场控：有基础，尚不能承诺完整产品

可以开始设计受控AUTO_SCRIPT队列、有限文本段、商品快照与模式切换、Operator interrupt后可见恢复操作，并先做CPU/Fake验收。完整自主直播尚缺：脚本进度/断点、被抢占后的续讲策略、当前商品切换事务边界、busy评论公平性/expiry UX、故障/重启对账及长时媒体回归。

PRODUCT_EXPLAINING只是Scheduler模式，不生成脚本、不自动续讲，也不负责长期直播节奏。默认评论不抢占已有讲话，已能避免无限FORCE；其代价是随机wall load已出现6–15秒等待与明显丢弃/合并。不能为了自动场控把这些数值隐藏或强制所有弹幕打断。

建议把下一阶段限定为设计与一个可独立测试的受控功能；先关闭下面的真实互动/听感门槛，再扩大自动自主行为。本轮没有开发新的自动场控系统。

## 第一个官方平台Adapter：可接入准备，真实上线有条件

现有统一Adapter/Event/Sink/Capabilities/Mapping足以承接一个官方、已授权的transport。实际选型、官方API权限/协议、Room账号授权、source identity与reconnect/replay语义、token生命周期、敏感内容留存、可靠取消、input限长/速率与队列pressure需先定义和验证。

持久Receipt只保护已保留的automatic trace；没有跨实例调度和完整crash恢复。新Adapter不能默认网络重复、重连历史消息或进程重启都获得永久exactly-once，更不能把多Backend的同一商品/Session忙态当作由本机mutex保证。上线前须做room/session/user映射、断网重放/重复、Stop与取消、expired backlog及真实观众端测试。

因此：**具备启动官方Adapter设计与隔离CPU实现的条件；不具备宣布第一个真实平台已验收上线的条件。** 不做私有协议逆向或淘宝正式Adapter，不扩大SaaS/计费/多GPU范围。

## 进入下一版本前的门槛

| 门槛 | 当前证据 | 关闭方法 |
| --- | --- | --- |
| 当前真实五场景 | BLOCKED；授权有，但现有Worker未运行 | 另行安排可用空闲READY Worker及隔离业务入口，再做一次有界短测；不干扰共享Session |
| LLM延迟 | 已有n6 ChromeP50/P95=3973.84/6668.99ms，乐观下界仍FAIL | 降低跨主机控制/Tool往返，严格observer/clock与独立分层随机样本；不得动统计目标或旧PCM/PTS |
| 中文内容/唇形 | 字符串回归PASS，新TTS文字修复后真实听感未测试 | XL/XXL/2XL、129.90元、500毫升、型号/英单位/长句，真人或指定评审有据记录 |
| 重启与歧义任务 | SQL receipt at-most-once保护PASS，RESERVED丢失/orphan仍可能 | 定义保守对账、未知结果/操作员恢复策略；避免无限重试和重复口播 |
| 持续互动与资源 | 短随机wall及虚拟1000-event PASS；全栈长时NOT TESTED | 分别记录真实LLM/TTS请求、native RSS/GPU memory/CPU、expiry/drop、正常Stop与清理 |
| 平台观众端 | 本地RTMP decode历史证据；官方平台NOT TESTED | 使用官方权限/测试直播间、真正观众端观测，不复用pipe或本地decoder作为观众证明 |
| 全新环境启动 | 最初Go空DB并发初始化失败；初始化后回归PASS | test runner明确先migrate；另验安装/启动并发/恢复，不把单实例业务测试称为任意Linux安装 |

已知native无callback hang、Session生命周期内的`seen_utterances`增长、DB retention/幂等过期行维护、共享命令锁带来的跨Room延迟，也应纳入生产长时门槛。它们没有被短期稳定或本次PASS掩盖。

建议：完成P0/P1修复审阅后保留本次交付；下一版本开发可有条件开始，当前v0.4完整真实验收与商业发布暂不建议通过。所有Agent C一次性SQL/Redis服务及转发已清理，merchant数据/现有GPU权重与实例未变更。GitHub CLI认证失效时，以独立分支Commit SHA交付，不直接操作main。
