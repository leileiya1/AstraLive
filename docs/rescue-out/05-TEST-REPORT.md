# 05 — 测试报告（全部为本机 2026-10-20 实际执行）

环境：macOS (Darwin 27, arm64)；Python 3.12.13（`.venv-guardian`）；Go（见 `evidence/after/regression/go-version.txt`）；PostgreSQL 17（每次测试私有 initdb，回环）；MediaMTX v1.21.1（`/tmp/astralive-guardian-tools/mediamtx`，私有端口）；Redis（私有实例）。**没有** GPU、外部平台、共享服务、Linux cgroup。
环境变量：`GUARDIAN_TEST_MEDIAMTX=/tmp/astralive-guardian-tools/mediamtx LC_ALL=en_US.UTF-8`。

计数之间存在重叠，不得相加。

## 1. 修复前（`service.py` = `94eb702c…`）

| 命令 | 结果 | 日志 |
| --- | --- | --- |
| `pytest output_guardian/tests/test_guardian.py output_guardian/tests/test_supervisor_cleanup.py output_guardian/tests/lifecycle` | **59 PASS / 1 FAIL**（`test_real_rtmp_full_decode_drain_stop`：首个音频包 `MEDIA_DELIVERY_FAILED`，见 02 P3-b） | `evidence/before/v1-lifecycle-baseline.txt` |
| `run_agent4_probes.py before stale` | **10 FAIL**：P1 mock 1 + real scoped 3 + real fresh-output 3；P2 fixture 3 | `evidence/before/agent4-probes-stale.txt`，`evidence/before/probe-out/` |
| 新回归 `test_stale_generation.py`（变异检查，第 1 版） | 14 FAIL / 3 PASS —— 其中 2 个负控仅因断言新诊断字段而失败，**已修正测试**，原日志保留 | `evidence/before/new-regressions-against-preimage-DRAFT1.txt` |
| 新回归（最终版） | **12 FAIL / 5 PASS**：全部 12 个旧回调用例失败；5 个负控（当前 life 故障/取消、IPC 指名当前 life、真实 Publisher 死亡、夹具串行）两边都通过 | `evidence/before/new-regressions-against-preimage.txt` |

## 2. 新增回归 `output_guardian/tests/lifecycle/test_stale_generation.py`（17）

| 用例 | 类型 | 证明 |
| --- | --- | --- |
| `test_stale_media_never_retires_replacement[ack/failure/cancel]` | mock | 旧 ACK/失败/取消都只让旧请求失败；新 life、barrier、Right、Publisher 原样；新 Generation 随后仍可收媒体 |
| `test_current_life_media_fault_is_still_retired[failure/cancel/barrier]` | mock 负控 | 当前 life 真实故障/取消仍被撤销；已被别处撤销时**只撤销一次**（修复前 barrier 加 2） |
| `test_stale_media_after_stop_keeps_stop_precedence` | mock | Stop 后旧回调不再二次 invalidate；Stop 墓碑仍阻止新 bind |
| `test_stale_media_after_expiry_then_replacement` | mock | 过期撤销 + 新 bind 后，旧回调不影响新 life，过期诊断保留 |
| `test_old_media_never_reaches_replacement_counters` | mock | 新 Generation 计数器不被旧请求污染，旧 Attempt 仍 `STALE_RUN_EPOCH` |
| `test_ipc_finish_deadline_retires_only_named_life[old/current]` | 真实 aiohttp IPC + mock Guardian 依赖 | 超时只撤销被指名的 life；指名旧 Attempt 不触及新 life |
| `test_poll_ingest_observation_for_replaced_life_is_discarded` | mock | 旧 ingest 列表不会触发 `exclusive()`、不会设置 `publisher_seen`，新 life 不被后续误撤销 |
| `test_real_stale_media_ack_keeps_new_generation[0..2]` | **真实** PG + MediaMTX + 原生子进程 | Agent4 场景 + 断言旧子进程已回收、新子进程存活且随后接受 3 个真实音频包 |
| `test_real_current_publisher_death_is_still_retired` | 真实负控 | 杀死当前真实 Publisher 后恰好一次撤销 |
| `test_real_fixture_writes_are_serialized` | 真实 PG | 8 路并发 `rig.permit()` + 后台 `renew_forever()` 无 `InterfaceError` |

修复后：**17/17 PASS**。

## 3. 修复后（`service.py` = `0a5441b5…`）

| 检查 | 命令（摘要） | 结果 | 日志 |
| --- | --- | --- | --- |
| Agent4 原始 P1 探针 | `run_agent4_probes.py after stale` | **7 PASS**（mock 1 + scoped 3 + fresh-output 3） | `evidence/after/agent4-probes-stale.txt`，`evidence/after/probe-out/stale-real-*/` |
| Agent4 原始夹具探针 | 同上 | **3 FAIL（预期保留）**：测原始受保护 `rig.db`，见 02 P5 | 同上 |
| Agent4 原始媒体探针 | `run_agent4_probes.py after media` | **66 PASS**：race 3、budget 3、rtmp 20、phases 20、stress 20 | `evidence/after/agent4-probes-media.txt` |
| 媒体范围审计 | `range-audit.json` | 60/60 全范围账本 `[0,64000]`、100 帧/100 PTS；6 份 race/budget 账本按设计只记录调度字段 | `evidence/after/range-audit.json`；账本 `probe-out/media-ledgers.tar.gz` + `media-ledgers.SHA256` |
| 生命周期全部 | `pytest output_guardian/tests/lifecycle` | **52 PASS** | 本节命令重跑 |
| P2 目标用例 ×10 | `test_real_proven_ranges_never_override_lifecycle`（5 参数） | **50/50 PASS** | `evidence/after/regression/real-edges-x10.txt` |
| 组合 Guardian 第 1 次 | `pytest output_guardian/tests` | 218 PASS / **1 FAIL**（v2 `test_real_decode_unit1_finish_unit2_same_process_clocks` `LEASE_LOST`）/ 1 SKIP | `evidence/after/regression/guardian-combined-RUN1.txt` |
| 该 v2 用例单独 ×10 | | **10/10 PASS**（v2 不导入 `service.py`，见 02 P3-c） | `evidence/after/regression/v2-cpu-clocks-repeat.txt` |
| v2 单独 | `pytest output_guardian/tests/v2` | **142 PASS / 1 SKIP**（Linux cgroup，Darwin 未测） | `evidence/after/regression/v2-full.txt` |
| 组合 Guardian 最终 | `pytest output_guardian/tests`（最终源码） | **219 PASS / 0 FAIL / 1 SKIP** | `evidence/after/regression/guardian-combined-FINAL.txt` |
| 契约 137 | `python -m unittest tests.test_contracts … tests.test_receiver_stop_races` | **136 PASS / 1 FAIL**：`test_schema_examples_states_protected_files_and_pending_ack`，原因为受保护 `process.py` 哈希不符（基线已存在，同 Agent4） | `evidence/after/regression/contracts-137.txt` |
| Adapter + v2 wire | `unittest tests.test_receiver1_wiring tests.test_durable_live_v2_wire` | **21 PASS** | `adapter-wire.txt` |
| Journal | `pytest runtime/tests/test_durable_live_journal.py` | **11 PASS** | `journal.txt` |
| validator v1 | `scripts/validate-durable-live-contracts.py` | **PASS** | `validator-v1.txt` |
| validator v2 | `scripts/validate-answer-contract.py` | **FAIL**：`AssertionError: output_guardian/process.py`（基线已存在，未改登记） | `validator-v2.txt` |
| 生成代码 | `scripts/durable-live/generate_v2_wire.py --check` | **PASS**（132 定义 / 38 操作，`3c0c317e…`） | `generated-check.txt` |
| Go vet | `go vet ./...` | **PASS** | `go-vet.txt` |
| Go test（无数据库） | `go test -p 2 -count=1 ./...` | 147 PASS / 0 FAIL / **133 SKIP** —— 不等价覆盖，不作为结论 | `go-test.jsonl` |
| Go race（无数据库） | `go test -p 2 -race ./...` | 147 PASS / 0 FAIL / 133 SKIP | `go-race.jsonl` |
| Go test 私有 PG 第 1 次 | 库名不符合守卫 | 142 PASS / **86 FAIL**（全部为 `refuse shared/non-isolated database` 守卫拒绝），保留 | `go-test-pg-ATTEMPT1-db-name-guard-FAIL.jsonl` |
| Go test 私有 PG | `agent2_*` / `agent2_v2_*` 库，`-p 1` | 227 PASS / **1 FAIL**（Redis 守卫要求固定端口 56382）/ 52 SKIP | `go-test-pg.jsonl` |
| Go Redis 用例 | 私有 Redis @ 127.0.0.1:56382 | 1 PASS / 1 SKIP（需 owned Redis 子进程） | `go-test-redis.jsonl` |
| **Go race 私有 PG + Redis** | `go test -p 1 -race -count=1 ./...` | **228 PASS / 0 FAIL / 52 SKIP** | `go-race-pg.jsonl` |
| lint | ruff（用户全局严格规则） | `service.py` 修复前后发现项完全相同（10 BLE001/1 C408/1 SIM114/1 UP041，均为既有代码）；新文件全部通过 | `lint.txt` |
| format / diff-check | `ruff format --check`；`git diff --check` | PASS / PASS | `format-check.txt` |

Go 52 个 SKIP：receiver1 36（需 Agent4 专用库标记文件与 PR11 归档）、answerstream 8（需 Agent3 专用库）、其余为显式 opt-in（浏览器、owned 子进程助手等）。

## 4. Linux（school-linux Docker，隔离容器）

详见 `evidence/school-linux/README.md`。要点：新回归在 Linux 上 **85/85 PASS**（5×17）；发现并修复 1 个 Linux 专属的确定性测试缺陷（v2 IPC `[v1]`，第一次修复 `f036fa3` 无效并保留记录，`d17d008` 修复后 PASS）；剩余失败为镜像缺 ffmpeg/git（5）、`--network none` 下 WebRTC（1）、受保护 `rig` fixture 的 Linux 负载计时 ERROR（2 次）及 1 次未复现、未保留 traceback 的 ERROR。

修复后 Mac：`output_guardian/tests/v2/test_ipc.py` 17 PASS。

## 5. 资源清理

私有 PG 已 `pg_ctl stop -m fast` 并删除数据目录；两个私有 Redis `shutdown nosave`；确认无残留监听（`evidence/after/regression/go-resources-cleanup.txt`）。Guardian 测试的 PG/MediaMTX/子进程由 fixture 自行回收。

## 6. 未测试（不得视为通过）

Linux cgroup/UID/网络/ACL/物理隔离；生产 PhysicalSource、Host Launcher、必需 Sink、Observer；receiver1 Agent4 专用库原生套件；GPU；真实平台推流；Durable LIVE。
