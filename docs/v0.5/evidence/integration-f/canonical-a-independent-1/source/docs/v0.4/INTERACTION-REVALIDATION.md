# AstraLive v0.4 — 独立互动与媒体复验

基线 `59d96c8818a4512651a2f945ced71278929c9e12`，分支 `audit/v04-interaction-gate`，2026-10-11。

**INTERACTION INTEGRATION: PASS** — 单实例隔离环境，CPU回归及真实 A/B/C/D/E、Replay取消、商品切换、headless RTMP完成。**MEDIA REGRESSION: PASS** — 本轮有界真实音视频/Fence客观回归完成；用户明确确认录像与六组音频的读音、音画同步、自然唇形通过。该结论不覆盖官方平台观众端或一小时稳定性。

## 新执行的回归

执行环境：macOS 本地 Go/Bun/Python；school-linux 上单独建立 Agent C PostgreSQL16-alpine/Redis7-alpine，仅转发独立26404/26405端口。既有商家 DB/Redis/服务没有清空、删除或改写。CPU回归 inference 为 Fake。后续真实运行使用 DeepSeek + 已缓存 XiaoYa + SoulX RTX3080；Backend/Runtime位于school-linux，GPU独立服务器，Chrome位于本机。测试仅使用新克隆的一次性验收DB，不修改克隆源或商家业务行。命令原始日志、JSON、SHA256 索引见 [checks.json](evidence/independent/checks.json)。

Go 命令均在 `backend/` 执行，设置 `CONFIG_TEST_DATABASE_URL` 与 `DATABASE_URL` 指向新建一次性 audit DB，`INTERACTION_TEST_REDIS_URL` 指向新建一次性 Redis，`RUN_INTERACTION_CPU=1`；formal evidence 路径分别指向 independent/formal-wake-normal.json、formal-wake-final.json。没有默认回退到商家连接。

| 实际命令 | PASS | FAIL | SKIP | 证据 |
| --- | ---: | ---: | ---: | --- |
| `go test -count=1 -json ./...` | 59顶层 / 90含子测试 | 0 | 1 opt-in | [go-wake-final.jsonl](evidence/independent/go-wake-final.jsonl) |
| `go test -race -count=1 -json ./...` | 59顶层 / 90含子测试 | 0 | 1 opt-in | [go-race-wake-final.jsonl](evidence/independent/go-race-wake-final.jsonl)；无 race 报告 |
| `go vet ./...` | exit0 | 0 | 0 | [go-vet-wake-final.log](evidence/independent/go-vet-wake-final.log) |
| `PYTHONPATH=runtime runtime/.venv/bin/python -m unittest discover -s runtime/tests -v` | 148 | 0 | 11；total159 | [runtime-complete-final.log](evidence/independent/runtime-complete-final.log) |
| `gpu_worker/.venv-tests/bin/python -m unittest discover -s gpu_worker/tests -v` | 21 | 0 | 0 | [worker.log](evidence/independent/worker.log)；CPU simulation/pinned decode |
| `PYTHONPATH=runtime runtime/.venv/bin/python -m unittest tests.test_contracts tests.test_acceptance_guards tests.test_interaction_observer -v` | 7 | 0 | 0 | [contracts-complete-final.log](evidence/independent/contracts-complete-final.log) |
| `bun run build`（frontend/） | exit0 | 0 | 0 | [frontend-build.log](evidence/independent/frontend-build.log) |
| `bun run test`（frontend/） | 40 / 9files | 0 | 0 | [frontend-test.log](evidence/independent/frontend-test.log) |
| `go run ./cmd/comment-load` | 5场景 | 0 | 0 | [load-offline.json](evidence/independent/load-offline.json) |
| `go run ./cmd/comment-load -wall` | 4场景 | 0 | 0 | [load-wall.json](evidence/independent/load-wall.json) |
| `go run ./cmd/comment-load -random -seed 20261010` | 5场景 | 0 | 0 | [load-random-offline.json](evidence/independent/load-random-offline.json) |
| `go run ./cmd/comment-load -wall -random -seed 20261010 -wall-seconds 30` | 4场景 | 0 | 0 | [load-random-wall.json](evidence/independent/load-random-wall.json) |
| `python3 scripts/revalidate-interaction-latency.py --output docs/v0.4/evidence/independent/latency-recomputed.json` | 20样本一致性断言 | 0 | 0 | [latency-recomputed.json](evidence/independent/latency-recomputed.json) |
| `git diff --check` / Frozen Contract/generated/validated diff | exit0 / 无变更 | 0 | 0 | 最终 Git 检查 |

首次 Go 运行在空 DB 上 FAIL：[go-before.jsonl](evidence/independent/go-before.jsonl) 保留 migration 并发 DDL 冲突与 legacy 测试缺表。随后 SQL 测试完成初始化，修复后的完整 Go/race 使用该隔离 schema 通过。没有将第一次失败删掉或声称干净 DB bootstrap 已通过。修复前的专用失败日志是预期复现，区别于最后全量 PASS。

11项 Runtime skip 是原有 opt-in 的真实 LLM/TTS/完整真实链路/lightweight/network WebRTC gates；Go skip 为配置浏览器 harness。本轮前端是 jsdom/Fake fetch，不能替代 native Chrome。

## 调度链及并发复核

Formal CPU 通过真实 HTTP create/start→Go Session→immutable binding→Bound Runtime→Redis/SSE→Stop/release。[formal-wake-final.json](evidence/independent/formal-wake-final.json) 正常阶段11条输入、9次合并、2次 Selection、2次成功；未选中时 SQL Utterance=0。已选事实走 Fast Path，聊天走 Fake LLM streaming。故障阶段2次失败为持久 receipt 重投拒绝与注入 Runtime429，0次成功、0次 FORCE；没有混入正常成功率。

| 要求 | 独立验证 | 结论 |
| --- | --- | --- |
| 未选评论不进 Runtime | 持有 Operator override 时10条输入仅1候选、0 Utterance；恢复后1次口播 | PASS（新 Adapter 路径） |
| 重复/合并 | 同 source 主备身份、并发100次重复、10人同问、各 receipt 状态 | PASS（短期内存去重 + 已保留 trace） |
| 尺码/整体/SKU库存 | 独立复现单/多尺码、2XL、复合问题与 Runtime 2XL 事实识别；不以整体库存代替单码 | PASS（修复后；启发式路由边界仍在） |
| TTL/忙队列 | busy 时不投递并 prune；选中后锁等待导致过期的 SQL/HTTP 回归0/0 | PASS；晚到期选择计为 failed attempt，不能把 prune 的 expired 当作全部 deadline failures |
| Room/Session/user | trusted mapping、owner、同 Room 第二候选队列拒绝、Room owner 撤销复验 | PASS（单实例） |
| Stop/Tick | Service 命令锁保护 admission；Stop前已接收的任务取消；STOPPING 后拒绝新 Utterance | PASS（CPU/有序并发边界） |
| Operator | Speak/Interrupt 进入 override，Scheduler 默认不打断 busy；显式恢复自动模式 | PASS；当前任务/断点不会自动续讲 |
| 自动 FORCE | 所有 offline/wall/random 负载 FORCE=0 | PASS；仅 opt-in 的特定 AUTO_SCRIPT 优先级抢占，之后要求操作员恢复 |
| 锁/竞态 | Scheduler Dispatch 时释放 scheduler.mu；Service.commands→controller.mu→scheduler.mu 顺序；race全量通过 | 没有在所测路径发现死锁；全局命令锁的跨 Room 等待仍存在 |
| Replay 取消 | 取消时 waiting Receive 拒绝；Stop 等待在途 sink call；stop-before-start保留 | PASS（Mock；新 Adapter sink 必须响应取消） |
| 重启/请求超时 | RESERVED/ACCEPTED/FAILED 不重投；lost ack 只1次 Fake Runtime请求 | PASS（at-most-once）；完整 crash/orphan恢复未验收 |

## 随机到达与资源观测

新增选项只用于 load CLI，不改变生产 Scheduler 默认值。用固定种子指数分布 interarrival，实际经过 Mock Adapter 的 wall timers，Fake speech 每次 busy2s；burst保持100条同时到达。`-wall-seconds 30` 是期望到达时长，固定输入数量的随机时长并非恰好30秒。实际1/s场景为30条/20.129s，不能改报为严格1/s持续30秒。

| 期望速率/输入 | 实际耗时秒 | 峰值候选 | 合并 | 选择/投递 | 丢弃 | 过期 | 等待P50/P95 ms | 采样峰值Go heap bytes | process CPU秒 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: | ---: |
| 1/s，30 | 20.129 | 7 | 14 | 10/10 | 6 | 0 | 3362.11 / 15040.90 | 586632 | 0.032 |
| 5/s，150 | 30.780 | 11 | 123 | 15/15 | 8 | 4 | 6952.23 / 13112.41 | 830016 | 0.075 |
| 20/s，600 | 30.466 | 8 | 257 | 15/15 | 327 | 1 | 6147.62 / 13550.90 | 1371248 | 0.138 |
| 突发100 | 0.251 | 6 | 87 | 1/1 | 12 | 0 | 102.03 / 102.03（n=1） | 685320 | 0.001 |

合并/选择/丢弃/过期比例分别以 input 为分母：1/s为46.7%/33.3%/20.0%/0%；5/s为82.0%/10.0%/5.3%/2.7%；20/s为42.8%/2.5%/54.5%/0.17%；burst为87%/1%/12%/0%。丢弃包括限速/缓存/Stop末尾未处理候选，不能全称队列满；候选 TTL 与 selection waiting 的规则没有被放宽。所有场景计数守恒，Force=0，failed=0，peak≤64。

随机 offline 的1000混合事件：100去重、365合并、33选中并成功、37过期、465丢弃，峰值26，等待P50/P95为12447/19970ms，CPU约0.046s；到达与讲话 clock 是虚拟，不能将短CPU执行时间当作观众端吞吐。

这些数据说明队列在当前合并/限速策略下有界，但评论已经经常等待6–15秒，很多输入被合并或丢弃。短时未 OOM 不等于持续直播 UX 达标。heap 是100ms/阶段采样，CPU是进程 user+system delta；不是全栈峰值 RSS/GPU native memory。Fake load 的实际 LLM/TTS请求数为0，delivery不是实际 inference请求数。正式 CPU 事实/聊天分支与历史真实 JSON另外统计。

## 主播场景与媒体

正常讲解中的评论默认等已有 AUTO_SCRIPT/OPERATOR 任务完成，不无限 FORCE；多人同问可合并；当前 Room activeProductId 与固定 product 不同时清队列并进入 override，要求新 Session，防止旧商品问题被新事实回答。Operator FORCE 沿用原 Generation Fence；恢复按钮只恢复选择模式，不续播已中断的讲解。当前没有完整自动脚本场控。

现有 BoundConsumptionMediaOutput 使用原 link/epoch、当前 generation 的消费目标；WebRTC receiver consumption 或 RTMP pipe-delivery position 才给 credit，排队不等于消费。headless RTMP 排除无订阅 preview 的 drain，真正 encoder failure 仍失败。现有 FORCE/旧帧/credit/RTMP/WebRTC drain 与 CPU packet decode 回归执行通过，未改媒体路径。Sherpa 取消回归用 Fake native callback，不能证明不调用 callback 的 native hang 可硬终止。

用户明确授权空闲时短测后，preflight确认RTX3080空闲、无业务Session，原Worker软件未运行。使用已安装launcher及缓存权重启动软件，doctor校验成功，Worker READY；没有云实例开关机、模型重下、Worker重启或破坏性fault。整个真实测试epoch固定 `1e3e5e1c78d64637a429e8b7c050c1df`。

| 真实场景 | 结果与原始证据 |
| --- | --- |
| A 确定性商品 / B DeepSeek | 基线20/20完成、Chrome/RTMP双关联；其中Fast14/LLM6。优化后的20条全部真实LLM完成；混合26条保留综合咨询慢样本。详见延迟报告，不以总体P50替代LLM |
| C 已有讲话 | `AUTO_SCRIPT` priority40/NONE 正在PLAYING时输入普通评论，700ms检查仍在讲且selected未增加；原讲解自然完成，再选评论、正常完成。基线约19.36秒/优化后约16.93秒等待至回复完成，自动FORCE=0；这不满足“繁忙时3秒回复”的期望 |
| D 随机混合输入 | 期望1/s、5/s、20/s指数分布分别8/30/100条，Mock单viewer；独立保存实际时长和指标。HTTP全202，峰值候选3，12次自动完成；9条随机负载候选收尾被丢弃（以原始counter为准），不是全部输入都回答；短场景不是长期多人吞吐。见 real-scenario-summary.json |
| 多人同问 / burst100 | 单HTTP Mock users=100，99次merge、1次选择；真实回复完成。不是100次网络HTTP峰值压测 |
| 商品切换 | Operator hold四条候选后切独立Room商品，恢复后清队列并override `PRODUCT_CHANGED_NEW_SESSION_REQUIRED`，没有追加旧商品Utterance；finally还原独立fixture商品 |
| E Operator FORCE | 原Utterance interrupted、新Utterance completed，generation=2，新generation出现后旧generation视频数0；自动FORCE=0。操作员显式恢复调度，不声称自动续讲 |
| Replay取消 | 已投递input稳定，取消后不追加事件；结束时过期候选计数保留，不假装全部回复成功 |
| 无浏览器 RTMP | 新formalSession没有Chrome订阅，真实Fast完成，RTMP audio580/video262、非零audio414/markedVideo260；Legacy LIVE202/Stop后409；ENDED、绑定释放 |

证据为 `real-browser-measured20.json`、`real-browser-scenarios.json`、`real-browser-optimized-llm20.json`、`real-browser-optimized-mixed26.json`、`real-headless.json`、对应raw Runtime/Backend日志、RTMP receiver JSON与epoch过滤Worker telemetry。每次都正常Stop。首轮自定义Redis stream配置错误（PREPARING）、第二轮未开诊断marker（8条已完成但视频无法关联）属于fixture失败，分别保留normal20/final20原始文件，不混成成功延迟样本。

真实负载的1/s、5/s、20/s实际速率受固定随机样本影响分别约2.26/s、5.21/s、14.33/s。总253输入含120去重、111合并、12选择、10丢弃（含商品切换清队列），峰值3、自动FORCE0；商品切换时4条输入合并为1候选再清除。资源JSON记录进程生命期CPU/RSS/HWM，不能伪称各速率全栈瞬时峰值。LLM/TTS实际调用由runtime trace计数，不用Fake delivery代替。
真实native XiaoYa已生成六组PCM/WAV，覆盖 XL/XXL/2XL、129.90元、500毫升、型号、混合语言与长句；输出非零且格式正确。真实Chrome录像也已生成。用户先确认“整体还是很真实的”，随后明确“录像和六组音频都检查了，读音、音画同步、唇形均通过”，真人门槛 **PASS_BY_USER**。原始答复见 human-review.json，没有以音频存在替代读音正确。没有平台 credentials/official Adapter，因此平台观众端 RTMP：NOT TESTED。共享 Worker 中断/恢复、长时 GPU soak：未执行。

## 清理与交付边界

最终SQL/Worker状态和清理结果见 real-final-sql.json、real-worker-final.json、cleanup.json：仅清理Agent C所有的Session、CPU服务/观察器、临时SQL/Redis/MediaMTX容器及转发；GPU Worker保留READY、activeGenerationId为空，不关闭云实例。共享原服务和缓存权重没有改动。

人工评审材料位于 `runtime/evidence/independent-real/human-review.html`（录像和WAV为本地忽略产物，SHA256见media-manifest.json）。真人评审已确认整体真实感与逐项读音/同步/唇形通过，官方平台观众端仍NOT TESTED。完整媒体与发布门槛不会因单实例客观测试通过而自动关闭。

连接复用后的首轮complex20仅记录Chrome：命令误用了不生效的 `INTERACTION_RTMP=1`，且observer路径错误；保留启动失败日志，不能声称该组RTMP复验。后续wake-complex20使用实际 `INTERACTION_RTMP_OBSERVER=1` 和已部署observer.py，另行保留完整JSON。

最终首短分句组综合20条全完成，Chrome/RTMP分路径与时钟上界均达标；同一Session最终FORCE旧任务interrupted/新任务completed、旧generation视频泄露0，Replay取消后input稳定；前一backlog先在override下自然TTL后，独立忙主播回复完成。原wake组busy阶段超时另列，不把phase失败算成正常20条失败，也不称整个wake试验成功。原始JSON见 real-browser-clause-complex20.json。

已导出的Runtime cache轨迹由real-all-runtime-traces.json保存；最早marker缺失的8条诊断任务未完整保留cache，不参与有效延迟成绩。Worker轨迹由real-worker-trace.jsonl.gz保存；后者是既有Worker日志按本次epoch筛选并重新序列化的JSON行，未伪称完整原始log。SHA和行数见worker-telemetry-manifest.json。各utterance的tts_started是首次合成阶段标记，不能当作每分句native generate总调用数；逐分句计数尚未测量。
