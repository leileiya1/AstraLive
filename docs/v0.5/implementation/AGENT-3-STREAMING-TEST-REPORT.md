# Agent 3 durable-live-2 streaming test report

> 本文为前一阶段 CPU/wire 历史记录。当前真实 Authority/七迁移 PostgreSQL 结果已更新至 [PG交接](AGENT-3-POSTGRES-HANDOFF.md) 与 [PG报告](AGENT-3-POSTGRES-TEST-REPORT.md)，不再等待 Agent2 pin；历史结果保留。
本轮交付为 CPU 域实现及真实共享 wire 编码/跨语言验证。已按Agent4正式通知正常合并并固定SDK `e3302f6b2bb19e0184cde3a6cbbcaf3ea4371565`；真实 Authority/PG 联验仍等待Agent2固定SHA。无生产入口、竞争DTO、SQL、媒体协议或LIVE开关改动。

基线 `e98d8cf53d1aa5518f9c908785b7a5feae5117f8`；冻结契约 `c7fd46209d3cbc6f58541dba8b4e1c85609c823e`，22文件 digest `3c0c317ed00f6fa4d2cf15ef3f61fc002d4bb22bf02d53ee9f1b407458bb28b1`。原 Worktree/分支安全 fast-forward，无新 Worktree/分支/Agent。逐文件核验原字节及 digest：[baseline-verification.json](agent-3-evidence/baseline-verification.json)。

## 实际命令与结果

| 检查 | 最终实际结果 | 原始输出 |
| --- | --- | --- |
| `cd backend && go test -count=1 -race -json ./internal/contentplan/... ./internal/turnmanager/... ./internal/interaction ./internal/durablelivev2/wire` | 7 packages PASS；83个顶层测试通过，0 FAIL，1 SKIP；含子测试179 PASS | [命令/耗时](agent-3-evidence/go-race.json)、[完整JSON输出](agent-3-evidence/go-race.txt)、[逐包计数](agent-3-evidence/go-summary.json) |
| 新 `contentplan/answerstream` | 12个顶层测试通过，含子测试46 PASS，0 FAIL/0 SKIP | 同上 |
| 新 `turnmanager/answerstream` | 11个顶层测试通过，含子测试21 PASS，0 FAIL/0 SKIP | 同上 |
| 六组契约 `unittest ... -v` | 137/137 PASS，19.527s | [完整命令](agent-3-evidence/contracts-137.json)、[原始输出](agent-3-evidence/contracts-137.txt) |
| `PYTHONPATH=runtime python -m pytest -p no:cacheprovider runtime/tests/test_durable_live_journal.py -q` | 11/11 PASS，0.43s | [命令](agent-3-evidence/journal-11.json)、[输出](agent-3-evidence/journal-11.txt) |
| `python scripts/validate-answer-contract.py` | PASS，132 definitions /25+13 operations /12 FSM /13 vectors /313 protected hashes /3 Stop scenarios | [输出](agent-3-evidence/validator-v2.txt) |
| `python scripts/validate-durable-live-contracts.py` | PASS，44 frozen files /20 operations /4 vectors | [输出](agent-3-evidence/validator-v1.txt) |
| 共享wire Python `unittest tests.test_durable_live_v2_wire -v` | 13 PASS，2.535s | [原始输出](agent-3-evidence/official-wire-python.txt) |
| `python3 scripts/durable-live/generate_v2_wire.py --check` | PASS；未改共享包/生成器/规范 | [输出](agent-3-evidence/generated-check.txt) |
| 真实Go DTO产出→真实Python DTO decode/hash | 2 Artifact +2 Prepare +1 Seal；Hash/manifest PASS | [描述符](agent-3-evidence/official-wire-artifacts.json)、[结果](agent-3-evidence/official-wire-interop.json) |
| 新包及共享wire `go vet` | PASS，exit0 | [命令](agent-3-evidence/go-vet.json) |
| 显式Mock编码器产出的实际回答，经冻结 `validate_artifact()` 独立校验 | 2/2 Schema、正文Hash、Artifact Hash、链关系 PASS | [描述符](agent-3-evidence/mock-artifacts.json)、[结果](agent-3-evidence/mock-artifact-validation.json) |

唯一 SKIP 是既有 `TestExportContractRequests`：未设置可选 `ASTRALIVE_DIRECTOR_EVIDENCE`，故没有重新导出旧 v1 请求；不是行为测试被跳过。新 v2 测试不依赖此开关。初轮测试辅助代码有字段误写为方法的编译错误，已修正；上表是修正后最终运行结果。

## 已覆盖的行为

- 中文正例在每一个字符边界拆成两次Token输入后，仍得到完全相同的正文：小数价格、XL/XXL/2XL、英文g/kg、型号、完整if/then、否定转折和比较。现有FactAnswerResolver的空格及“币种信息暂不可用”完整文案也被精确保留。
- 负例包含仅有条件前件、只有/才缺失、否定后件缺失、双重否定、比较缺数字/单位、拆开的价格/型号/尺码、不受支持的产品/优惠断言和未结束的EOF。标点和字符数不能替代完整语义证明。
- Provider EOF被通道阻塞时，首个完整单元已Prepare/START/消费；确认首次TTS意图计数=1、未Seal。没有测真实DeepSeek或TTS。
- 窗口满时Source读次数不增长；一个Prepare owner、无Token队列、并发第二次Prepare被拒绝；Source错误/超限/Stop会关闭流，已缓冲的下一句也不能从关闭的Scanner继续读取。
- Prepare-before-Drain、等待下一句期间先Drain、正常同Generation Unit2、单全局START、每单元一次消费/TTS意图、32并发Start只产生一个赢家。
- Prepare ACK丢失仅重试同一描述符/Hash，不再次读取或生成；START/Continuation/Consume ACK丢失进入UNKNOWN，拒绝重试发言、完成或续播。
- 商品事实变化/过期/缺失/额外依赖拒绝；迟到下一段的同值事实可经可信Mock重新观察；已有Artifact不改写，Hash链和最终正文Hash来自实际回答。
- 缺Seal或缺required drain不能CONTROL完成；单元Drain不调用CONTROL、不释放业务Slot、不写商品cursor；Stop/UNKNOWN/消费中Stop/drain中Stop均不越过业务完成门槛。
- 新域对象对同一权威Mock的已消费任务无法再次取得首次授权；真实重启仍须Agent2恢复与持久唯一性，不允许凭新对象重播。
- 既有Turn Manager的10段持续讲解、自然让出及续讲、TTL、公平预算、重复/merged source身份、Stop、FORCE、旧Epoch、商品切换和UNKNOWN race回归均保留。

## 验收边界

`WireEncoding`、`Artifact.Typed()`、Prepare/Seal请求构建使用Agent4真实唯一DTO和canonical/hash工具；协调器测试也已使用真实wire编码。`Facts`、`Executor`、`Completion` 仍是明确Mock。保留的fixture编码器只是独立测试基准；正式wire编译/跨语言PASS不等于Agent2真实Authority互操作。完整句采用可信词汇驱动的有限语法；未知自由改写会fail-closed，不能视作通用中文NLU。

真实PG多连接/提交崩溃/持久Latch、Tool与Binding来源装配、私有IPC、Registrar、Runtime once-TTS、fsync、Guardian物理输出、异步PCM/GPU lineage、真实required-range drain、DeepSeek/XiaoYa/SoulX/GPU、Chrome/WebRTC/RTMP/观众、忙讲解P50≤5s/P95≤8s和空闲P50≤3s/P95≤5s，均 NOT TESTED。新增Authority、事实检查和同步开销须在后续真实时间线中测量。
