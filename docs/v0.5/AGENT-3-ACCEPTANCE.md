# Agent 3 Acceptance — CPU / Mock

状态：模块CPU/Mock验收；共享接线、真实数据库和媒体验收另行完成。基线和边界见[Handoff](AGENT-3-HANDOFF.md)。

| 场景 | 可复核测试 | CPU判定 |
| --- | --- | --- |
| 连续10段、无人评论持续讲解 | TestTenSegmentsWithoutComments | PASS |
| Segment1插话、当前段未commit不让出、回答后第2段 | TestNaturalCommentBoundaryAndResume | PASS |
| Segment3多人同问XL、保留身份且只回答一次 | TestRealSchedulerMergesSizeQuestionsAtSegmentThree / TestSegmentThreeMergedSizesAndRepeatedSelection | PASS |
| 连续5秒、每秒20条+相同事件重复注入 | TestSchedulerContinuousBurstUsesExistingAlgorithms | PASS |
| 持续评论不饿死讲解、2次/8秒/12秒预算、重启不重置 | TestSustainedCommentsNeverStarveExplanation / TestFairnessBudgetsAndRestart / TestOccupancyAndMaxScriptWait | PASS |
| FORCE等待显式恢复和fence | TestForceRequiresExplicitResumeAndFence | PASS |
| TTL到期及重启后不刷新 | TestTTLNeverResetByWaitingOrRestart | PASS |
| 商品突变、新计划不套旧问题 | TestProductSwitchDoesNotReuseOldFactsOrTurns | PASS |
| LLM/TTS/Worker失败不伪造完成 | TestFailureStagesNeverCompleteSegment / TestCommentFailureCanResumeAfterProvenBarrier / TestDegradedProviderAndLostAck | PASS |
| 重复完成、部分drain、证据冲突 | TestNaturalCommentBoundaryAndResume / TestDrainProofRequiredAndEvidenceConflict | PASS |
| 播放中崩溃UNKNOWN、Manager重启、旧Epoch | TestUnknownAndOldEpochFailClosed / TestUnknownWithoutSlotStillBlocksCursor | PASS |
| Stop后新旧Manager/迟到完成均不恢复 | TestStopDoesNotRestartAndLateEvidenceCannotResume | PASS |
| 多Manager并发不增加媒体任务 | TestConcurrentManagersDoNotDoubleDispatch | PASS（Fake CAS，不是多PG实例） |
| 长句、价格/尺码/型号/单位/否定/条件 | TestNaturalAtomicText / TestShortJoinAndLongReject | PASS |
| 动态事实过期、改变值、无权威Tool | TestFactExpiryAndUnsupportedTools / TestFactRefreshCannotChangeAssertion | PASS |
| 未批准gap不越过cursor | TestGapRequiresExplicitDurableDecision | PASS |
| 冻结协议20组request/response无损round-trip、4组hash | TestProtocolExampleRoundTrips / TestCanonicalGoldenVectors | PASS |
| Runtime exact-text不经LLM改写、严格hash/商品/有效期 | runtime/tests/test_durable_live_segments.py | PASS |
| 场控展示、UNKNOWN人工入口、Stop禁止恢复 | TurnManagerPanel.test.tsx | PASS |

Fake使用虚拟时钟和模拟sink proof，只有通过模拟BUSINESS_COMMIT才推进cursor；模拟媒体证据不是真实sink日志。部分投影和请求将导出到`docs/v0.5/evidence/agent-3/`供JSON Schema及规范hash独立校验，未导出密钥或实际观众文本。

复现命令（仓库根）：

```sh
python3 backend/internal/contentplan/contract/generate.py
go -C backend test -race ./...
go -C backend vet ./...
ASTRALIVE_DIRECTOR_EVIDENCE="$PWD/docs/v0.5/evidence/agent-3" go -C backend test -count=1 ./internal/contentplan/... ./internal/turnmanager/... -v
python3 backend/internal/contentplan/contract/validate_evidence.py docs/v0.5/evidence/agent-3
python3 scripts/validate-durable-live-contracts.py
python3 -m unittest tests.test_durable_live_contracts -v
PYTHONPATH=runtime python3 -m unittest discover -s runtime/tests -p test_durable_live_segments.py -v
python3 docs/v0.5/agent-3/check-patches.py
cd frontend
bun install --frozen-lockfile
bun run test
bun run build
```

Python契约命令需`tests/requirements.txt`。本轮纯契约初检使用`/tmp/astralive-agent3-contract-venv`，完整回归使用后述Python3.12隔离环境，不改全局Python。原始成功结果和汇总将记录在本目录evidence/agent-3；数据库依赖测试若跳过不能据此声称真实PG验收。

真实GPU、真实DeepSeek/XiaoYa/SoulX、Chrome首次关联音画、WebRTC、本地RTMP、官方平台、物理听感、长时soak、真实PG/guardian故障注入：全部 **NOT TESTED**。两个延迟SLA均 **NOT TESTED**，本PR未修改或掩盖历史17–19秒结果。最终成功标准仍需Agent4完成整合后实测。

本轮实际结果（[机器汇总](evidence/agent-3/verification.json)，每项含原始日志）：

- 全仓Go race：91个顶层测试通过，7个环境依赖测试跳过；新增3包共38个顶层测试通过（contentplan 10、contract round-trip 1、turnmanager 27）。子测试另见JSON日志。
- `go vet ./...`：通过。
- 冻结v0.5+既有v1.1 Python契约：17项通过；44个保护文件hash全部一致。
- Runtime既有Session/Streaming/Fact/故障回归：38项通过；新增exact-text辅助模块：6项通过。
- 前端：43项通过（新增3项）；类型检查与production build通过。
- Scheduler未应用补丁：临时树race通过，另含忙SCRIPT选评/3人合并身份完整测试。
- 导出29个CPU请求、3个RuntimeCommand：Schema和规范requestHash全部通过。

首轮Runtime回归2项因独立环境未安装NumPy而报错，原日志保留为`runtime-regression-before-dependency.log`。仅补充NumPy测试依赖后重跑该组38项全部通过，没有改既有Runtime实现。完整复现使用Python3.12隔离环境`/tmp/astralive-agent3-runtime-venv`，依赖版本见`python-dependencies.txt`。根目录默认Python3.9可跑纯契约/辅助模块，但既有Runtime需要Python3.10+。

推荐一键复现：用上述Python3.12环境运行`python docs/v0.5/agent-3/verify.py`。验证脚本只跑CPU/Mock，不自动启动真实Provider、数据库服务或GPU。
