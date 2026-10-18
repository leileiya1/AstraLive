# Agent 3 Handoff — Segmented Speech & Turn Manager

Agent 3 ACK **durable-live-1**。开发基线main完整SHA：`7fe5d24810e2df348c58dd7748e97ffbe5cff384`；已用merge-base确认包含Agent1交付 `ae28144d15afcf0e5f5ea8fa425fc42d27fc047b`。独立worktree：`/Users/sapiece/innovationProject/AstraLive-agent-3`；分支`feat/v05-turn-manager`。最终提交SHA见PR/head（避免文档自引用SHA循环）。

已交付可编译Content Planner、完整语句分段、稳定身份/hash、独立Turn策略/执行器、Scheduler Dispatcher适配、可信检查点透传、基于持久状态的续讲/公平预算、exact-text辅助模块、场控展示组件、CPU Fake场景和独立Schema验证。Fake仅测试使用；没有生产数据库、内存数据库fallback、收费GPU、默认启用或main合并。

Agent2当时尚未提供可消费实现，因此按用户要求通过`turnmanager.Durable`冻结接口+schema-generated DTO与严格Fake验证。Agent4先整合Agent2，再接本模块。没有改`backend/internal/app/**`、`httpapi/**`、`interaction/scheduler.go`、任何DB迁移、既有Runtime Session/Binding/媒体或冻结契约文件。

Agent4按以下顺序接线：

1. Agent2实现Durable的11个冻结operation，入口验证scope/角色与Schema；生成类型如不一致，用唯一Schema生成包alias或无损JSON适配。禁止手动变更wire。
2. 实现进程内PolicyReader：Agent2授权repo读取已选WAITING/READY评论、active Turn、公平历史和已批准gap映射；返回同run revision。RestoreSnapshot本身没有这些列表，不能把未知列表当空列表。跨进程如确需新wire读取操作，先CCR；本PR没有偷偷新增RPC。
3. Facts适配器在事务外复用Product Tool，校验snapshotVersion和依赖valueHash。Claim和Runtime effect-start必须独立再查；把新鲜同值的FactDependency写入原Schema允许的不可变command payload。Manager的预检结果不是跨队列无限期授权。
4. 独立feature flag默认false，单Session只运行legacy或durable路径。应用[Scheduler补丁](agent-3/scheduler-members.patch)，使用SelectionAdapter+PreservedSources；SelectionOnly仅允许该durable准入dispatcher使用。不要让原`interactionDispatcher.speak`同时运行。Gate从授权缓存/投影取值，不在Scheduler mutex内等SQL。最终Turn Manager的slot决定物理发言。
5. 可信ingress先分配可重放source/receipt身份；外部平台原始ID若不满足冻结ID字符/128长度限制，须在Agent2 ingress保存稳定映射，不能直接灌入Schema或恢复时临时重编码；选择成功持久Admit后才确认delivered。合并全部source必须保留，缺失直接拒绝。事件无平台sourceId时只能用已持久首次receipt，不能在恢复时重新分配。
6. 绑定Agent2 checkpoint/journal事件到Manager.Confirm/Run wake。COMPLETED必须CONTROL+完整证据链且事务提交；重复/旧epoch处理由Agent2负责。Manager绝不从TTS成功制造完成。Outbox202丢失不重新发媒体。
7. Runtime新wrapper先journal/fence/permit，再`exact_script_text`，然后原TTS→SoulX→媒体路径。SCRIPT_TEXT绕过旧LLM改写；COMMENT_QUESTION复用旧FactAnswerResolver/Streaming LLM。还需Agent2/4的journal、输出guardian、当前段全required drain接线，本辅助模块不替代它们。
8. FORCE入口先关闭自动准入并通过Agent2持久暂停；随后沿旧优先级/中断路径，证明输出隔离。明确Resume写恢复意图，等新fence激活再清override。切商品先暂停/封存旧计划，新snapshot/plan/Binding；Stop提交tombstone后不再恢复。
9. 应用[LiveConsole展示补丁](agent-3/live-console-panel.patch)，由既有登录/owner/session授权后的服务投影注入TurnManagerView与人工恢复回调。组件没有虚构HTTP路由、角色token或Runtime队列控制。未知段按钮只打开证据/决策界面，不直接恢复。
10. 接Metrics到真实媒体观察器，分别跑忙主播、低负载、Chrome、本地RTMP与官方平台。完成真实数据库/故障恢复及媒体验收前保持默认关闭。

Scheduler补丁采用零行上下文以保持补丁文件本身无尾部空白，手动应用用`git apply --unidiff-zero docs/v0.5/agent-3/scheduler-members.patch`。

补丁检查：`python3 docs/v0.5/agent-3/check-patches.py`在临时CPU树应用Scheduler补丁并运行race测试，不改本工作区共享文件；LiveConsole补丁做apply检查，组件通过前端测试/类型检查。正式共享App/HTTP/Session接线必须Agent4依据Agent2最终接口完成，不提供猜测的可部署服务实现。

场景与实际命令见[验收报告](AGENT-3-ACCEPTANCE.md)；性能边界见[性能报告](INTERACTION-PERFORMANCE.md)。本交付是Agent3模块/Mock验收，不是最终直播间集成验收。真实GPU、真实DeepSeek/TTS/SoulX、Chrome/WebRTC/RTMP、官方观众、guardian/PG崩溃恢复均 **NOT TESTED**。P1音频/LLM预取未实现，避免无界缓存和并发GPU推理。

实际验收汇总：Go race 91顶层PASS/7环境SKIP（新增38顶层PASS）、vet PASS、契约17 PASS、既有Runtime CPU回归38 PASS、exact-text 6 PASS、前端43 PASS/build PASS；导出29请求+3命令Schema/hash PASS。7项Go SKIP包含PG和浏览器服务依赖，不能当真实服务验收。原始日志、初始缺NumPy失败及最终版本指纹均保存在`evidence/agent-3/`。

## durable-live-2 隔离增量交付

在基线 `e98d8cf53d1aa5518f9c908785b7a5feae5117f8` 的原Agent3分支新增保守中文语义流、实际回答Hash构建域模块及单COMMENT协调器。纯域初始提交 `0db4b8eb49f7ae7c37818c8bd047f676cd3ba7be`；最终已测实现 `90bab471ecf9cf147f5789fa9a8d40d707c0c102`，已正常merge Agent4正式wire pin `e3302f6b2bb19e0184cde3a6cbbcaf3ea4371565`。增量PR记录最终HEAD。

详见[新交接说明](implementation/AGENT-3-STREAMING-HANDOFF.md)、[测试报告](implementation/AGENT-3-STREAMING-TEST-REPORT.md)。23个新增顶层测试、7包race、137契约、11Journal、13共享wire Python测试通过；真实共享Go/Python Artifact/Prepare/Seal及Hash校验通过。真实Authority依赖SHA尚未提供，未复制DTO/SQL、未接共享入口，生产与真实媒体/SLA仍NOT TESTED。上文v1交付记录保留。


## durable-live-2 真实 PostgreSQL 域联验增量

已在原Worktree/分支正常merge integration `235258ad75f7d271a279ea89fd88ddf80e797f31`（包含Authority merge `a4a57fcc0effd5dd5ea9689b355a963b007c20f3`），完成正式DTO→真实Authority Handle→独占PG的Streaming域适配。18项新增PG顶层测试/61含子测试PASS；完整七迁移Go test/race各229顶层PASS、13明确SKIP、0FAIL；原23Streaming/137契约/11Journal/13wire及validator均通过。已知SKIP和真实/fixture边界不能省略，见 [最新交接](implementation/AGENT-3-POSTGRES-HANDOFF.md)、[完整测试报告](implementation/AGENT-3-POSTGRES-TEST-REPORT.md)。

首句在EOF前真实Prepare/START，双Unit同COMMENT且单START，两种Drain顺序、CAS/回执、ACK-loss→UNKNOWN、Stop竞争、事实/最早输出期限、Seal+drain+CONTROL均通过真实SQL验证。既有Scheduler/公平预算/业务cursor不变。Receiver/Registrar/Observer/物理来源仍是显式fixture；IPC/Guardian/Runtime once-TTS/媒体/required Sink、真实GPU与首句SLA仍NOT TESTED。没有修改Agent2 Authority、迁移、共享入口、Guardian或冻结规范；未启用LIVE，等待Agent4集成复审。
