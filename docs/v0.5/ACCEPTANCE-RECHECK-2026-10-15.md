# 2026-10-15：F 本地复核与下一轮真实验收准备

此文是本轮当前状态；较早报告中的“用户暂缓一小时”已由最新指令取代。
**顺序仍是本地完整回归→通知用户开 GPU→确认云端可用→最新代码短检查→单次连续一小时。**
本轮本地阶段没有连接 SSH、GPU、真实 LLM/TTS 网络 provider 或启动真实直播。用户确认已开机后，F重新建立独立SSH隧道，cached doctor通过；重启前Worker实际UNREACHABLE，正在从已验证缓存启动。此阶段尚未启动新Golden，后续实际结果另行追加，不能把健康检查当验收通过。
旧失败文件不修改，软件通过不升级为真实 GPU 通过。

## 固定源码、独立修复与所有权

| 内容 | 实现/交付 SHA | F 正常合并 SHA | 所有权与结果 |
| --- | --- | --- | --- |
| 既有 bridge `[]` 构造修复 | `ee22e1e9f1c1dbc58c7505e3cd5a238d979f9aaa` | `fb9b75d27f21e176afb4d5fdb32f202fc708ce6a` | C `model.go`；新 SQL/document/COMMIT/READY 保持 `[]`，不重写旧 `null` |
| A 独立持久化复核 | `1850e15531089a88dfe36bb3ef47cecdd7f59f77` | `7516b7f` | A 只交自己的报告/证据，没有修改生产文件 |
| B 分阶段延迟工具/分析 | `b55355b1e6847f252acd08654f2aa7dda66f7d66` | `e055f25` | B 新增后处理工具、测试和自己的报告；不改 Timeline、原 oracle 或 F harness |
| 本轮新发现的 Stop cleanup caller-cancel 竞态 | `9bb51971e305183c7aa373526619736196ac838b` | `9d09708b6788868c885c3bfc8bafa1234566ec1e` | C 仅 `soulx_staging.py` 17行及10项 TCP 测试；A 固定 pin 只读 ACK，F 审查/合并/全回归 |
| F 私有 wire 观测工具 | `c009d89` | 独立 F commit | 新增 integration 工具/测试/README，不改生产协议或 oracle；6项本地测试 PASS |

本轮实际冲突文件：无。C 的首个 cleanup 调用固定 complete/reason/controlID，同 Stage 后续调用 shield 同一个在途任务，双重 caller cancellation 不丢精确 ACK；10/15秒 exchange deadline、拒绝/UNKNOWN/nonreuse 语义不变。缺 ACK/错 ACK/外来身份仍 fail closed。原 StageCancel/StageRelease 两项旧源码失败和修复后日志由 C 持久保存，不能用代码通过掩盖原失败。

共享 `runtime/app/session.py`、Go service/Scheduler、Runtime main 等文件没有并行写入。A 负责 SQL/outbox/inbox/recovery；B 负责 Timeline/sinks、延迟证据；C 负责 narration/Runtime stage 生命周期；F 统一审查、集成与报告。后续若发现跨域问题，先固定 owner 和 pin，其他 owner 只读审查后由 F 合并，禁止各自改共享文件。

## 当前证据门槛

| 门槛 | 状态 | 实际边界 |
| --- | --- | --- |
| 已发布 `aab062f` 完整本地软件/数据库回归 | PASS | Go/race/owned PG migrations/auth/ownership/faults/Redis-off/contracts；Runtime304 passed+12 skipped；前端40/build。独立源归档，不访问真实 GPU |
| 实际合并 `9d09708` 完整软件回归 | PASS | Go/race/ownedPG故障/恢复/鉴权/Redis-off/contracts exit0，Runtime314 passed+12 skipped，前端40/build；随后才请求用户开启GPU。106项integration证据工具/拒绝测试PASS |
| A 独立 SQL/race/故障/恢复/鉴权复核 | PASS | 19顶层+5子项实际 owned PG 测试，无 skip；包含实际 Backend/CPU Runtime SIGKILL、PG stop/start、Redis不接入。不是 GPU/直播故障恢复 |
| 新 bridge `factIds=[]` 跨 Go→PG→生产 Runtime READY | PASS | 实际 PG 测试在普通 Go 与 race 各执行一次；CPU fixture PCM/avatar/sink 明确标记；旧 `null` 拒绝、不改历史行 |
| 最新 bridge 空数组真实 SoulX 完整片段 | NOT TESTED | 需要新源码中至少一个非空文本、已完成 RESUME_BRIDGE，逐层核对 factIds；LLM 全选无 bridge 时不能称该项已验证 |
| 新 cleanup 取消竞态的软件重现/负向守卫 | PASS | C10项实际 loopback TCP；原相同 ACK 旧代码2项 FAIL。含双取消、重入、固定首参数、原10/15秒超时、late/foreign/wrong-prefix/RX failure、UNKNOWN不可升级 |
| 旧 source88 单次一小时整体验收 | FAIL | 连续3600.1805秒/25答复与25正确下一段/140必需事实元数据覆盖是已观察组件；最终 Stop卡在STOPPING，4个桥段SQL `null`；不可算整体通过 |
| 旧 source8f 正常 Stop 组件 | PASS | 新鲜 Worker epoch、独立一问题60.147秒：ENDED/SEALED/binding释放；原整体 artifact仍因 bridge差异 FAIL；有 UNKNOWN 尾段 |
| 最新源码正常 Stop 真实组件与资源释放 | NOT TESTED | 尚未新 GPU 运行；HTTP202只是接受，不能代替终态或物理释放 |
| 最新源码单 Session/同 Chrome peer 连续一小时 | NOT TESTED | 尚未启动；必须所有检查点、完整新源数据和正常 Stop，禁止拼接旧时长 |
| 旧真实 Chrome/本地 RTMP packet PTS/DTS 单调 | PASS | 各自录制时钟域0回退；不是完整 A/V质量通过 |
| 完整语音/口型同步、人工自然度、实际设备可听 | NOT TESTED | 旧 speech-prefix/条码偏移只有录制级条件组件；Chrome有1行UNRESOLVED及Stop删失尾，不是全段phoneme lip-sync |
| 条件响应延迟估计达到5/8秒目标 | FAIL | 旧25次 P50/P95=9.374/12.093秒；跨 Go/DB/Chrome 时钟假设未独立校准 |
| 正式 busy-comment→观众端首相关AV SLA | NOT TESTED | busy分类、设备时钟/录制呈现校准未完成；禁止把条件估计当正式可听SLA |
| 无 Redis 的 PG-only 本地可靠命令/恢复 | PASS | 实际PG/实际进程故障软件测试；旧hour亦以unreachable Redis URL跑PG路径，不等于真实Redis进程kill/rejoin |
| 最新真实直播完整故障矩阵 | NOT TESTED | Backend/Runtime/GPU/Redis/FFmpeg kill、PG outage、网络/ACK/Stop-FORCE/product-switch，尚未全部在新真实媒体链路执行 |
| Linux本地GPU、跨主机GPU、Linux/macOS UDS真实媒体、Windows | NOT TESTED | 旧实际环境是macOS控制面+远程Linux GPU+TCP；不能泛化为其他主机/UDS验收 |
| QUIC直播 | NOT TESTED | 可选、最后；不是 Continuity 发布依赖 |

本轮本地门证据目录：`evidence/integration-f/acceptance-recheck-20261015/`；A/B/C 原 owner 报告另见相邻文档。12项 Runtime skip 必须原样记录，不能写“全平台全链路通过”。

## Stop 与 UNKNOWN：一小时前先冻结报告口径

不修改冻结契约或原严格 oracle。ARCH §3、§4.2–4.3 与 CCR-BC-002 §11.6 允许：Stop/control凭自身fence/cleanup完成；已提交媒体未获全部required sink证明则保留UNKNOWN/nonreusable，不推进事实、不授权恢复或重播。原 `real_golden_audit.py:bindings()` 对所有 commit 强制 COMPLETED，因此安全 UNKNOWN 尾段仍可能报 `NONCOMPLETED_COMMITTED_ATTEMPT`/`UNPROVEN_PLAY_STATE`。这是当前严格全量完成门槛，不能悄悄删尾段豁免。

下一轮必须同时报告：

1. 正常 Stop 控制组件：认证/ownership下公开Stop接受，精确run/producer控制cleanup证明，Session ENDED、run SEALED、narration STOPPED/stickyStop、匹配binding released。
2. 物理资源组件：同identity/controlID的实际 StageReleased，native_safe_boundary=true、retained_artifact_bytes=0；Worker active stage/queue、采样资源、owned本地Runtime/FFmpeg/PG退出状态。观测 ACK 不是 Runtime 接受、SQL完成或观众可听证明，三者分别关联。
3. 若有尾段：列完整command/attempt/epochs/generations、commit区间、各sink连续watermark和未证区间，UNKNOWN/nonreuse、无completionHash/事实推进/新admit/盲重播。缺项仍标未知。
4. 原完整 artifact oracle 及所有失败码原样保留；Stop组件PASS不得覆盖全量FAIL。不能宣称 exactly-once audible speech。

## 下一轮真实一小时执行方案（待GPU开启）

- 本地最后修复/全回归完成后由F通知用户开GPU。确认开机后才连接；校验缓存安装、模型/asset hash、版本、GPU/Worker健康和新鲜epoch。旧UNKNOWN使staging退役时，显式operator restart后新授权Session，不重用旧任务；管理端Ready不等于可admit。
- 固定最终源码完整SHA、940语句/140必需事实原hour fixture及种子5012、音色/语速、profile `staging-segment-8s-gpu1g-1`、全部flags。fixture/真实TTS及native adapter相对source88未变，既有本地TTS预检为5823.52 padded秒/max7.56秒；它是旧预检，不包装为新跑。若任何TTS/model/fixture变化必须重新预检。
- 先以最新源码/新鲜epoch跑短真实功能检查，包括至少一已完成非空 bridge `[]` 与正常Stop；失败先保留、修复、独立commit和回归。短检查后若Worker正常取消后退役，显式重新启动再跑全新一小时。
- 单Session、同Chrome peer持续≥3600秒，90/300/900/1800/2700/3600秒六检查点；25个固定种子评论，逐个selected/rejected原因、回答相关性、正确下一Beat/segment和音画证据。评论输入是fixture replay，LLM/TTS/GPU/Chrome/RTMP实际链路不替代为mock。Go gate是生产HTTP组件的测试进程+真实独立Python/PG，不误称为production Backend executable重启验收。
- PG-only路径独立认证/租约、每command/attempt/ACK/receipt/descriptor/installed/全部required sink证据，完成事实不重不漏、bridge文档/SQL/READY/COMMIT版本一致。事实自动覆盖仅元数据；原始文本、声音与人工自然度分别报告。
- 同步保存真实Chrome WebM与本地RTMP FLV，关闭后ffprobe逐流PTS/DTS及独立音频相关/条码匹配、丢失/删失/拒绝项；区分server/sink/browser/recording/audio-device时钟，不从track.recv推导观众已听到。浏览器播放/卡顿/设备切换另列实测范围。
- 资源采样明确是否含Chrome/PG/全host，GPU缓存常驻显存不要求归零；比较baseline/peak/退出后阶段保留量、queue/active stage与native释放。可选F wire observer增加一个仅loopback hop，必须记录拓扑；仅保存白名单validated控制元数据，不保存token/音视频payload。不能将其性能变化叫生产优化。
- 正常Stop和完整收尾后封存原始结果/日志/录制/hash/source/env/fixture/feature flags；临时服务只清理本轮拥有的PID、PG与隧道。若失败，不挪用旧成功组件，不续接原计时。大录像保持本地完整原件及hash/位置，Git存有界压缩证据与短预览；发布前按实际私密输入扫描，输出仅scan PASS/FAIL。

复现入口：`integration/v0.5/module_gate.py`、`golden_gate.py --mode soak --soak-seconds 3600 --local-transport tcp --real-dns --source <final-SHA>`；原hour fixture、上述profile和已批准短GPU gate digest显式传入。credentials只通过0600私有文件路径，不在命令/日志中放值。F在执行时保存完整参数、实际工具hash和新output目录；此文不假设某个旧SSH连接/端口仍然存活。

## 延迟诊断、可验证优化与剩余分工

[B 分阶段报告](LATENCY-PHASE-REVIEW.md)及独立工具已以原始与gzip备份各复跑25行/0拒绝，15项拒绝测试通过。边界等待P50/P95=4.912/6.708秒，generating→READY=3.382/5.081秒；同批均值两包络占总均值88.60%。不相加边际分位数，不将native inference从包络相减后命名为TTS/网络。现无细分TTS/embedding/编码/传输/解码锚点，不能凭猜测定责。

| Owner | 任务与可交付证据 | 发布风险 |
| --- | --- | --- |
| A | 已完成本地durability/鉴权/重启/Redis-off复核；下一轮审查真实SQL终态、UNKNOWN尾段不进事实/不重播，补完整直播PG/Redis/Backend故障矩阵 | P1：真实故障矩阵未完成；不意味着现有PG-only无效 |
| B | 已完成25问阶段归因；下一轮审查真实AV/PTS/缓冲/资源、busy/时钟证据。优先设计同事实/voice/speed/prompt负载的较短自然语义段A/B，统计正确性+延迟+空窗+开销，不能把删短fixture当代码优化 | P1：响应目标未达、完整AV/卡顿/人审未完成 |
| C | 新Stop竞态修复已独立commit；下一轮核验非空bridge[]/无bridge两种恢复、最新Stop与真实资源清理，回归Stop/FORCE/product switch及worker断连 | P1：新源码真实验证未完成，不能用旧source8f短Stop代替 |
| F | 固定源码/顺序合并、审查A/B/C证据、全软件回归与一小时gate、严格oracle/组件并列、最后上线阻塞清单 | P1：全量严格oracle的UNKNOWN尾段完成门槛仍可能FAIL；不擅改契约/oracle |

READY细锚点先提出最小只读测量设计再实施；控制poll唤醒可做事务提交后通知+PG polling fallback独立对照，不能在SQL外绕过授权。边界期间提前LLM/TTS若涉及新durable preparation、未来epoch/generation授权或资源顺序，必须先CCR；本轮不抢跑GPU、不加timeout/cap/queue、不改模型。

## 上线与回滚

**尚不建议默认上线；本地门通过后适合进入真实GPU验收。** 未新发现需改共享契约的P0，不代表证明P0不存在。P1至少包括新源码hour/Stop/bridge/resource闭环、延迟目标与正式时钟/busy证据、完整live故障矩阵/UNKNOWN人工对账、真实A/V与人工自然度/host覆盖。

保持 durability=false、event_mode=legacy_redis、MediaTimeline=false、Continuity=false、local/Worker transport=tcp、fallback disabled；SoulX staging默认关闭，仅测试显式选择已批准1GiB profile，旧512MiB/原TCP/Redis保留。UDS/QUIC独立开关，QUIC不阻塞Continuity。配置仅在新run/受控Stop后切换，不能热切未知任务。

回滚先fence/Stop并封存UNKNOWN/绑定/SQL证据，不盲重播；C本轮修复可审查后 `git revert -m 1 9d09708b6788868c885c3bfc8bafa1234566ec1e`，其余按依赖反序revert。保留additive migrations、原始失败和原TCP/Redis路径，不做破坏性down migration/reset。任何回滚也需对应回归；不合并main、不force push。
