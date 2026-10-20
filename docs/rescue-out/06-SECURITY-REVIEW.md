# 06 — 安全审查：生命周期隔离、资源回收、Stop、权限

## 1. 不变量（修复后）

| # | 不变量 | 机制 | 证据 |
| --- | --- | --- | --- |
| I1 | 旧 Generation 的迟到结果不能撤销、重标或修改新 Generation | Media/IPC-Finish/poll/finish 诊断一律按捕获的 `life` 判定；撤销只经 `_retire_life(life)`（要求 `self._life is life and barrier == life.barrier`） | 新回归 12 个旧回调用例；Agent4 原始 7 例 |
| I2 | 当前 life 的真实故障不被吞掉 | `_retire_life` 对当前 life 等价于全局 `retire()`；请求仍返回 `MEDIA_DELIVERY_FAILED` | 负控 failure/cancel、真实 Publisher 死亡 |
| I3 | 同一 life 只被 invalidate 一次 | 已被撤销（barrier 已变）时 `_retire_life` 为空操作；清理由先撤销者负责 | `[barrier]`、Stop 用例（修复前 barrier 加 2） |
| I4 | 旧媒体字节不会进入新子进程 | `Publisher.call` 锁前捕获 `expected` 进程/管道，锁内与返回后复核身份；`abort(expected)` 不杀更新的子进程 | 源码审查（未改）；真实用例中旧子进程已回收、新子进程存活 |
| I5 | 新 Generation 只能在 `operations` 锁内由 `bind` 创建 | 未改 | 源码审查 |
| I6 | Stop 优先 | `stop()` 同步写墓碑并全局 `retire()`；旧回调之后不能再 invalidate；墓碑阻止新 bind | Stop 用例；lifecycle `stop_linearizes_*` 4 例；real-edges `[stop]` ×10 |
| I7 | 过期不被当作正常冲突 | `_watch` 全局撤销并记录 `LEASE_LOST`；未改 Right 0.9 s / 100 ms 余量 | 过期用例；`expired_right_during_terminal_*` |
| I8 | 不重放 | 旧请求只返回失败，无重试；`used_attempts` 阻止旧 Attempt 再 bind | 计数器用例 |

## 2. 资源回收

- 清理仍走 `close_resources()` 的合并任务（Publisher → Receiver → socket → WebRTC → `ingest.isolate`），任何一步失败都会尝试剩余步骤并置 `failed`。本次未改。
- 作用域撤销不会遗漏资源：若 life 已被他人 invalidate，则该撤销者已经或正在调用 `close_resources()`；所有 invalidate 调用点（`retire`、`finish` 成功路径、`_watch`、`stop`、`bind/install` 前置 retire）均伴随资源关闭。
- `bind()` 失败路径保持全局 `retire()`：锁内不可能存在更新的 life，且这是“Stop 在启动中途”时回收后启动 Publisher 的唯一路径。
- 进程退出/重启恢复（`Publisher.recover` 的 PID+创建时间+环境标记校验）、supervisor 清理：未改，`test_supervisor_cleanup` 与 SIGKILL 重启用例 PASS。

## 3. 权限与输入

- IPC 鉴权（control/producer token、producerIncarnation 校验）、strict JSON、MediaMTX auth 回调：未改。
- IPC Finish 超时现在只撤销 `guardian._life.attempt == attempt` 的 life。调用者已通过与 `media` 相同的 token/producer 校验；指名旧 Attempt 只会得到 `DRAIN_UNKNOWN`，无法借此撤销他人的新 Generation（修复前可以）。
- 无新增网络端点、凭据、日志字段；证据文件不含 URL、密钥、票据。

## 4. 残余风险（未解决，诚实列出）

| 风险 | 说明 |
| --- | --- |
| R1 `OUTPUT_FENCE_UNPROVEN` | cgroup 变更控制器有意不可用；真实 Linux 隔离、旧 Publisher/socket/凭据撤销未证明。**保持** |
| R2 生产 PhysicalSource | 无条件拒绝；Host Launcher、必需 Sink、真实 Observer 未实现 |
| R3 取消放大为整机失败 | `retire()` 等待者被取消即 `failed=True`（02 P3-a），可用性风险 |
| R4 负载敏感计时 | 02 P3-b/P3-c；未放宽任何期限 |
| R5 受保护文件未登记 | `service.py`、`process.py` 均待 Agent4 审核；validator-v2 与契约 1 例因此失败 |
| R6 Darwin 环境 | `SO_PEERCRED`/cgroup 等 Linux 语义未测 |

Durable LIVE 关闭；未启动 GPU；未推流到任何正式平台；未在共享 Linux 上做任何 cgroup 操作。
