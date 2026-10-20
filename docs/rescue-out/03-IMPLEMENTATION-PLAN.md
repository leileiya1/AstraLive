# 03 — 修复方案与执行顺序

## 原则

1. 只修复有证据的缺陷；不重构 Guardian，不新增协议/RPC，不改 PTS/Credit/Grant/超时/覆盖要求。
2. 使用已存在的作用域撤销原语 `_retire_life(life)`，不发明新机制。
3. 旧 Generation 的任何迟到结果只能“拒绝自身”；当前 life 的真实故障仍必须撤销（不吞故障）。
4. 每个修复先有失败复现，修复后用**同一**测试证明，并对修复前源码做变异检查。
5. 受保护文件只动 `service.py`（本就未登记），不动 conftest/inventory/validator/迁移/DTO。

## 修改与顺序

| 步骤 | 文件 | 内容 |
| --- | --- | --- |
| 1 | — | 远程 fetch，建 `rescue/astralive-v05-final`，建 `.venv-guardian` |
| 2 | `evidence/before/` | 基线 v1+lifecycle、Agent4 原始探针（只改输出目录）复现 P1 7/7、P2 3/3 |
| 3 | `output_guardian/service.py` `media()` | 准入时捕获 `life` 并 `_check_life(life)`；await 后用 `_check_life(life)`；失败/取消走 `_retire_life(life, code)`；首帧 PTS 异常同样作用域化；**保留原异常形态**（清理本身失败时仍由 `retire()` 的 `Closed` 上抛） |
| 4 | `service.py` `ipc_app` finish 超时 | 仅当 `guardian._life.attempt == attempt` 时 `_retire_life(life, "DRAIN_UNKNOWN")` |
| 5 | `service.py` `_poll` | `ingest.publishers()` 与 `ingest.exclusive()` 之后复核 barrier，旧观察直接丢弃 |
| 6 | `service.py` `finish()` | `last_drain_fault/poll_fault/stats` 仅在 `self._life is life` 时写 |
| 7 | `tests/lifecycle/serial_rig.py`（新） | 覆盖 `rig` fixture：对测试专用 `rig.db` 的 execute/fetch* 加 `asyncio.Lock`。不是 conftest（v1 测试 `from conftest import port`，嵌套 conftest 会遮蔽） |
| 8 | `tests/lifecycle/test_real_edges.py` | 一行导入 `serial_rig` |
| 9 | `tests/lifecycle/test_stale_generation.py`（新） | 17 个确定性回归（见 05） |
| 10 | 变异检查 | 用修复前 `service.py` 跑第 9 步：12 FAIL / 5 PASS（5 个为负控，必须两边都过） |
| 11 | 回归 | Agent4 原始探针、媒体 66、组合 Guardian、v2、契约、validator、生成、Go test/race（私有 PG/Redis）、lint/format/diff-check |
| 12 | 文档与提交 | 本目录 7 文档 + 证据 SHA256；本地提交，不推送 |

## 明确不做

- 不把 `bind()` 的失败清理改为作用域撤销（会破坏“Stop 在启动中途”回收，见 02 P1 表）。
- 不修改 `process.py`、受保护 conftest、313 项登记、validator、迁移、官方 DTO。
- 不更新任何保护哈希，不合并 PR8/PR11，不推送分支。
- 不放宽 `Publisher.call` 0.15 s、Right 0.9 s/100 ms 余量、Finish 2 s、覆盖要求或 Stop 规则。
