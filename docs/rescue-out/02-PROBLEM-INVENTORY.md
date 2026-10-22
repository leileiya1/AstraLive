# 02 — 问题清单

状态说明：**FIXED** = 本分支已修复并有前后对比证据；**OPEN** = 未修复；**KNOWN-FLAKE** = 已观察到、根因未定、未放宽任何条件。

| ID | 优先级 | 问题 | 状态 |
| --- | --- | --- | --- |
| P1 | P1 | 旧 Generation 的 Media 迟到回调全局 `retire()` 撤销新 Generation | **FIXED** |
| P1b | P1（同类） | IPC Finish 超时路径全局 `retire()` | **FIXED** |
| P1c | P2（同类，纵深防御） | `_poll` 用旧 ingest 观察结果标记/判定新 Publisher | **FIXED** |
| P1d | P3（诊断） | 旧 `finish()` 覆盖新生命周期的 drain 诊断字段 | **FIXED** |
| P2 | P1（测试阻塞） | 生命周期测试多个协程共用同一 asyncpg 连接 | **FIXED（测试层）** |
| P3-a | 观察 | 任一 `retire()` 等待者被取消会使整个 Guardian `failed=True` | OPEN（设计上偏保守，未改） |
| P3-b | KNOWN-FLAKE | v1 `test_real_rtmp_full_decode_drain_stop` 冷启动首个音频包 `MEDIA_DELIVERY_FAILED` | OPEN |
| P3-c | KNOWN-FLAKE | v2 `test_real_decode_unit1_finish_unit2_same_process_clocks` 在组合负载下 `LEASE_LOST` | OPEN |
| P3-d | 已知历史 | RTMP 音频尾部覆盖间歇不匹配（Agent5 记录，`tail28 expected64`） | OPEN（本次 66 次未复现） |
| P4 | 治理 | `service.py`/`process.py` 与 313 项保护登记哈希不一致 | OPEN，需 Agent4 审核 |
| P5 | 环境 | 原始 Agent4 夹具并发探针仍 FAIL（针对受保护 `rig.db` 本身） | 预期保留，见下 |
| P6 | P2（Linux 测试） | v2 `test_real_ipc_denies_unprovisioned_context[v1]` 在 Linux 确定性失败：服务端拒绝未读请求后 Linux 发 RST，`send()` 只处理 EOF | **FIXED**（`d17d008`；`f036fa3` 的首次修复无效，已记录） |
| P7 | KNOWN-FLAKE（Linux） | 受保护 `rig` fixture：MediaMTX SIGTERM 3 s 超时；`start()` 失败被 `close()` 的 `OUTPUT_FENCE_UNPROVEN` 掩盖 | OPEN，需 Agent4 决定是否修改受保护 conftest |
| P3-f | KNOWN-FLAKE（负载） | v1 `test_real_proven_ranges_never_override_lifecycle[crash]` 在全量负载下 1 次失败：安全断言（DRAIN_UNKNOWN、未 drain）通过，仅诊断标签不同——ingest 轮询先发现被杀的 Publisher，得到 `OUTPUT_FENCE_UNPROVEN` 而非 `MEDIA_DELIVERY_FAILED`；单独 20/20 通过；近 7 次全量运行中出现 2 次（机器同时有其他高负载进程）；未放宽断言 | OPEN（`evidence/stage2c/coordinator-run1-*`、`after/regression/crash-case-x20.txt`） |
| P8 | P2（产品质量） | 真实 TTS 静默丢字：拉丁字母（T恤、S/M/L、USB-C）以及影响含义的符号（%、+、~、¥、℃、×、㎡、/、&、#）都被跳过，价格/折扣会读错 | **FIXED**：通用读法规范化 + 按模型词表核对，真实引擎验证只剩停顿符被跳过，见 12-P8 |

---

## P1 — PR11-STALE-MEDIA-RETIRES-NEW-LIFECYCLE

**位置**：`output_guardian/service.py` `Guardian.media()`（修复前 L499–509）。

**根因**：`media()` 在 `await self.publisher.call(message)` 之后，任何异常（包括对旧 Attempt 正确的 `STALE_RUN_EPOCH` 拒绝）都进入 `except BaseException: await self.retire()`。`retire()` 作用于**当前**全局状态：barrier+1、删除当前 Right、杀死当前 Publisher。若在等待期间 `bind()` 已建立 Generation 2，则旧请求的清理撤销了 Generation 2。Renew/Finish/poll 已使用 `_retire_life(life)`，Media 是遗漏的同类路径。

**影响**：任何晚到的旧 ACK、旧失败、旧取消都能杀死一个合法授权、未过期、未 Stop 的新 Publisher（可用性 + 生命周期隔离破坏）。不会导致旧媒体写入新子进程（`Publisher.call` 已按 `expected` 隔离）。

**复现（修复前，本机真实执行）**：Agent4 原始探针 **7/7 FAIL** —— mock 1 + 真实 PG/MediaMTX/原生子进程 scoped 3 + fresh-output 3。每例：barrier 3→4、新 life `REVOKED`、Right 消失、新 Publisher 被杀，`stopRequested=false`、新 Right 剩余约 699 ms。证据：`evidence/before/agent4-probes-stale.txt`、`evidence/before/probe-out/stale-real-*/case-*.json`。

**同类风险排查（同一生命周期，全部 await 之后的全局写）**：

| 路径 | await 后动作 | 结论 |
| --- | --- | --- |
| `media()` 成功/失败/取消 | 全局 `retire()` | **缺陷 P1**，已修 |
| `media()` 首帧 PTS≠0 | 全局 `retire()`，但前面无 await | 实际安全；为一致性改为作用域撤销 |
| `ipc_app` Finish 2 s 超时 | 全局 `retire()` | **同类缺陷 P1b**：旧 life 被撤销后可 bind 新 life，超时清理会撤销新 life。已修 |
| `_poll` `ingest.publishers()/exclusive()` | 基于旧列表设置 `publisher_seen`，之后可能误判新 Publisher 消失 → 撤销新 life | **P1c**，已加 barrier 复核 |
| `finish()` 诊断字段 | 覆盖 `last_drain_*` | 仅诊断，P1d，已作用域化 |
| `renew()` / `finish()` 失败 / `_poll` 异常 | 已用 `_retire_life` | 正确，保留 |
| `bind()` 失败 | 全局 `retire()` | **保持不变是正确的**：bind 持 `operations` 锁，期间不可能出现更新的 life；且 Stop 在启动中途落地时，只有 bind 自身的全局 retire 能回收之后启动的 Publisher（Agent5 `77b1758` 已用回归证明“改成作用域”会出错） |
| `install()` / `stop()` / `close()` / `_watch()` | 全局 | 锁内或同步判定，Stop 优先级本就要求全局，保留 |
| `Publisher.call/abort/start` | 按 `expected` 隔离 | 已核验，不改 |
| `receiver.start` (poll 内) | 旧启动被 bind 的 retire 杀死；poll 单任务，不存在并发新 receiver | 已核验，不改 |

## P2 — asyncpg 测试连接并发

**位置**：受保护 `output_guardian/tests/conftest.py` 的 `Rig.permit()` 使用唯一 `rig.db` 连接；`lifecycle/test_real_edges.py` 在后台 `renew_forever()`（同样调用 `rig.permit()`）运行时再调用 `rig.permit()`。

**根因**：asyncpg 单连接同一时刻只允许一个操作 → `InterfaceError: cannot perform operation: another operation is in progress`。时序相关：本机基线那次 `[stop]` 恰好通过，但 Agent4 原始双写探针 **3/3 FAIL**（`evidence/before/agent4-probes-stale.txt`）。生产 `PostgresAuthority` 有自己的连接与查询锁，不受影响。

**约束**：不得修改已批准的受保护 conftest、不得跳过 Stop 用例、不得重试到绿、不得改期限。

## P3 — 稳定性观察（未修改，不放宽）

- **P3-a**：`retire()` 将任何异常（含等待者被取消）转为 `failed=True`，Guardian 需重启。属于“有疑即关闭”，不是隔离漏洞；但会把一次超时放大成整机不可用。建议后续单独评审，不在本次范围。
- **P3-b**：基线（修复前代码）组合运行中第一个测试的**第一个**音频包超时（`Publisher.call` 0.15 s），与音频尾部问题不同。修复后 2 次组合运行 + 66 次媒体探针 + 10×5 lifecycle 未复现。未改超时。
- **P3-c**：v2 用例（不导入 `service.py`）在第 1 次组合运行中 `LEASE_LOST`；单独 10/10 PASS，最终组合运行 PASS。负载敏感的计时测试，未改期限。
- **P3-d**：历史尾部覆盖问题仍未定位根因，本次 60 份全范围账本均为 `[0,64000]`/100 帧，但不构成 SLA 证据。

## P4 — 保护文件治理

`service.py` 在本分支基线就已是 Agent5 未批准的 `94eb702c…`（登记 `12b5225d…`），`process.py` 为 `56d4093b…`（登记 `5d95a661…`）。因此 contracts **136/1** 与 validator-v2 FAIL 在修复前后都存在。本次产生新的 `service.py` 候选 postimage，**未登记**，需 Agent4 独立审核（见 04 §3）。

## P5 — Agent4 夹具探针为何仍 FAIL

`test_fixture_sql_concurrency` 直接对**受保护原始** `rig` 并发写两次，它证明的是“原始夹具连接不可并发”，这一事实没有也不应改变（Agent4 明确要求保持 conftest 不变、修生命周期测试的 setup）。修复后它仍 3/3 FAIL，原样保留；生命周期测试改为使用串行化层，并有新的 8 路并发 + 后台续期的真实 PG 测试证明其安全。
