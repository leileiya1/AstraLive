# 04 — 实际修改记录

基线：`origin/feat/v05-output-guardian` @ `47eedbb0f4d990c18cbe8bdf462b65486d385523`。
提交：分支 `rescue/astralive-v05-final` 上的单个本地提交（SHA 见 `git log -1`，最终报告中给出）。未推送。

## 1. 文件与 SHA256

| 文件 | 受保护 | 修改前 SHA256 | 修改后 SHA256 |
| --- | --- | --- | --- |
| `output_guardian/service.py` | **是** | `94eb702cd978b76a21cd29e3642397c976a8b221593a651b55f5375b6a18fa47` | `0a5441b5064bda615977b47f1966809ed913f05d246cbeee5c58cb43c3a02508` |
| `output_guardian/tests/lifecycle/test_real_edges.py` | 否 | `445b82ea7b2002cb4142a91845f45be3549af15501a3e7837247dfda335cfef1` | `642c3c48b40b2a08b20fb776adf85f254491b33f73ca8d380e1b3de433fa0493` |
| `output_guardian/tests/lifecycle/serial_rig.py` | 否 | （新建） | `96cd6c04d8a15cb014628a45d94f5ac379f0fb3bbd2ff0641f458438ba65f0bd` |
| `output_guardian/tests/lifecycle/test_stale_generation.py` | 否 | （新建） | `3554bef44e06ca2e5b2fd7e16285d7ea1294b9dc9480495b982347092c786110` |

未修改：`process.py`（`56d4093b…`）、受保护 `tests/conftest.py`（`101add95…`）、`protected-files.json`（313 项）、全部 validator、7 个迁移、官方 DTO、生成代码、Go 源码。

## 2. `service.py` 函数级变更

| 函数 | 变更 |
| --- | --- |
| `Guardian.media` | 准入：`life = self._life`，为 None 则 `Closed()`，`self._check_life(life)`；删除局部 `barrier`。首帧 PTS≠0：`retire()` → `_retire_life(life, "OUTPUT_FENCE_UNPROVEN")`。await 后：`check(attempt)+barrier` → `_check_life(life)`（两处）。异常：`retire()` → `_retire_life(life, code)`，随后仍 `raise Closed("MEDIA_DELIVERY_FAILED")` |
| `Guardian.finish` | `last_drain_fault`（成功与失败两处）、`last_drain_stats`、`last_drain_poll_fault` 仅在 `self._life is life` 时写；返回值、阶段、cause、撤销逻辑不变 |
| `Guardian._poll` | `await self.ingest.publishers()` 后、`await self.ingest.exclusive()` 后各加 `if self.barrier != barrier: continue` |
| `ipc_app.handle` (finish 超时) | `guardian.retire()` → 仅当 `guardian._life.attempt == attempt` 时 `guardian._retire_life(life, "DRAIN_UNKNOWN")`；仍 `raise Closed("DRAIN_UNKNOWN")` |

精确 diff：`evidence/protected/service.py.diff`（SHA256 `d69181f7523ee054c1a4bbd05846ccf6516a598fbfedb6fe047850e74cca37fc`）；preimage/postimage 全文：`evidence/protected/service.py.{preimage,postimage}`；审核提案：`evidence/protected/PROTECTED-CHANGE-PROPOSAL.json`。

## 3. 受保护文件审核请求（等待 Agent4 独立审核）

| 项 | 值 |
| --- | --- |
| 路径 | `output_guardian/service.py` |
| 登记哈希（313 项清单） | `12b5225dffcfad095bf4f07140d30c907325a8ccf244aa124b80d3153fc76e52` |
| 本分支基线（Agent5 未批准提案 94eb） | `94eb702cd978b76a21cd29e3642397c976a8b221593a651b55f5375b6a18fa47` |
| 本次候选 postimage | `0a5441b5064bda615977b47f1966809ed913f05d246cbeee5c58cb43c3a02508` |
| 登记状态 | **未登记**；未修改清单/validator；未自行批准 |

审核时需同时审 `12b5→94eb`（Agent5 Finish/Renew 协调）与 `94eb→0a54`（本次）。`process.py 5d95→56d4` 仍待审。

## 4. 与 Agent5 未推送提交 `2bf2600` 的对比

独立实现后对比，四处修改点完全一致（media、poll 两处、IPC 超时、finish 诊断）。差异仅两点，均为有意：

1. 准入检查：本次用完整 `_check_life(life)`（Right、Attempt、life 身份、barrier）；`2bf2600` 只比较 barrier。
2. 异常形态：`2bf2600` 用 `try/finally: raise Closed("MEDIA_DELIVERY_FAILED"/"DRAIN_UNKNOWN")`，会把**清理本身失败**时 `retire()` 抛出的 `Closed`（`OUTPUT_FENCE_UNPROVEN`）掩盖掉；本次保持修复前的形态。

`2bf2600` 的 `feacde73…` 与本次 `0a5441b5…` 不同；两者都未登记。Agent5 的 `77b1758` 中“bind 必须保持全局 retire”的结论经本次复核成立，已采纳（未改 bind）。

## 5. 测试层变更

- `serial_rig.py`：`SerialConnection` 包装 `rig.db`，对 `execute/executemany/fetch/fetchrow/fetchval` 加同一把 `asyncio.Lock`；以 `@pytest_asyncio.fixture(name="rig")` 覆盖父 fixture。父 fixture 拆卸使用自己的局部 `db` 变量，不受影响。
- `test_real_edges.py`：导入上述 fixture（1 行）。断言、调度、期限、输入均未改。
- `test_stale_generation.py`：17 个回归，见 05 §2。文件级 `# ruff: noqa: F811`：pytest 按名称解析重导出的 `local` fixture（别名导入在 pytest 9.1.1 下无法注册，已实测 12 ERROR 后回退）。

## 6. 后续提交（Linux 部署测试中发现）

| 提交 | 文件 | 内容 |
| --- | --- | --- |
| `f036fa3` | `infra/guardian/rescue-test/Dockerfile`（新，测试专用镜像）；`output_guardian/tests/v2/test_ipc.py` | 镜像；teardown 容忍 reset —— **单独无效**（见 school-linux 证据） |
| `d17d008` | `output_guardian/tests/v2/test_ipc.py` | `send()` 将 `ConnectionResetError` 与 EOF 同视为“无回复关闭”；teardown 抑制保留（传输层会再次抛出同一异常） |

两者均不涉及受保护文件或生产源码。

## 7. 证据工具

- `evidence/run_agent4_probes.py`：把 Agent4 原始探针复制进临时包运行，仅替换 `/tmp/agent4-pr11-final-results` 字面量，运行后删除临时包。原始探针字节与来源 SHA256：`evidence/probes/ORIGINAL-SHA256.txt`（来自 `origin/integration/v05-durable-live` @ `e4292ac`）。
