# AstraLive v0.4 — 独立互动与媒体复验

基线 `59d96c8818a4512651a2f945ced71278929c9e12`，分支 `audit/v04-interaction-gate`，2026-10-10。

**INTERACTION INTEGRATION: BLOCKED** — 独立 formal Go→Bound Runtime 的 CPU 集成与修复后回归 PASS；完整当前真实主播场景尚未独立跑通。**MEDIA REGRESSION: BLOCKED** — CPU 媒体回归 PASS，新增文本转换未做真实 XiaoYa 听感/GPU/Chrome 复验。

## 新执行的回归

执行环境：macOS 本地 Go/Bun/Python；school-linux 上单独建立 Agent C PostgreSQL16-alpine/Redis7-alpine，仅转发独立26404/26405端口。既有商家 DB/Redis/服务没有清空、删除或改写。所有 inference 为 Fake/CPU，真实外部 Provider 调用数为0。命令原始日志、JSON、SHA256 索引见 [checks.json](evidence/independent/checks.json)。

Go 命令均在 `backend/` 执行，设置 `CONFIG_TEST_DATABASE_URL` 与 `DATABASE_URL` 指向新建一次性 audit DB，`INTERACTION_TEST_REDIS_URL` 指向新建一次性 Redis，`RUN_INTERACTION_CPU=1`；formal evidence 路径分别指向 independent/formal-final.json、formal-race-final.json。没有默认回退到商家连接。

| 实际命令 | PASS | FAIL | SKIP | 证据 |
| --- | ---: | ---: | ---: | --- |
| `go test -count=1 -json ./...` | 58顶层 / 87含子测试 | 0 | 1 opt-in | [go-final.jsonl](evidence/independent/go-final.jsonl) |
| `go test -race -count=1 -json ./...` | 58顶层 / 87含子测试 | 0 | 1 opt-in | [go-race-final.jsonl](evidence/independent/go-race-final.jsonl)；无 race 报告 |
| `go vet ./...` | exit0 | 0 | 0 | [go-vet.log](evidence/independent/go-vet.log) |
| `PYTHONPATH=runtime runtime/.venv/bin/python -m unittest discover -s runtime/tests -v` | 145 | 0 | 11；total156 | [runtime-final.log](evidence/independent/runtime-final.log) |
| `gpu_worker/.venv-tests/bin/python -m unittest discover -s gpu_worker/tests -v` | 21 | 0 | 0 | [worker.log](evidence/independent/worker.log)；CPU simulation/pinned decode |
| `PYTHONPATH=runtime runtime/.venv/bin/python -m unittest tests.test_contracts tests.test_acceptance_guards tests.test_interaction_observer -v` | 7 | 0 | 0 | [contracts-final.log](evidence/independent/contracts-final.log) |
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

Formal CPU 通过真实 HTTP create/start→Go Session→immutable binding→Bound Runtime→Redis/SSE→Stop/release。[formal-final.json](evidence/independent/formal-final.json) 正常阶段11条输入、9次合并、2次 Selection、2次成功；未选中时 SQL Utterance=0。已选事实走 Fast Path，聊天走 Fake LLM streaming。故障阶段2次失败为持久 receipt 重投拒绝与注入 Runtime429，0次成功、0次 FORCE；没有混入正常成功率。

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

用户明确授权空闲时短测后，只读 SSH 发现 RTX3080 memory1MiB、利用率0%、配置的17088管理端口及17087推理端口都未监听：[gpu-preflight.json](evidence/independent/gpu-preflight.json)。没有 READY Worker 可使用，没有启动或恢复 Worker、实例、模型下载。因此本轮 A=Fast、B=真实 LLM、C=讲话中评论、D=高频混合、E=FORCE 的**新增真实 Chrome/RTMP/GPU**运行全部 BLOCKED；CPU对应验证与历史 A/B JSON复核明确另列。

真人中文 XL/XXL/2XL、129.90元、500毫升、型号、混合语言、长句听感及主观唇形：NOT TESTED。没有平台 credentials/official Adapter，因此平台观众端 RTMP：NOT TESTED。共享 Worker 中断/恢复、长时 GPU soak：未执行。

## 清理与交付边界

Final formal Runtime sessions=0、leases=0，绑定 release/capture deletion 验证通过；四个 Agent C 自建容器与独立端口转发已清理。[cleanup.json](evidence/independent/cleanup.json)。测试种子身份/业务行仅存在于被销毁的测试 DB。没有修改实际商家数据，没有 Flush Redis，没有删除 GPU 权重，没有启动/关停 GPU实例。

可继续审阅单实例实现与局部修复；不能用本报告替代新的真实播放或持续直播场景验收。
