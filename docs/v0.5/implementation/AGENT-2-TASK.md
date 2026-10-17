# Agent2 — v2 persistence and Authority task package

状态：任务包已准备，未在本轮派发/启动。仅使用原AstraLive-agent-2 Worktree/现有分支。先读取[baseline](../IMPLEMENTATION-BASELINE.md)、[正式交接](../ccr/CCR-ADL-001-FINAL-HANDOFF.md)与[ownership](ownership.json)，记录PR8公布的完整开工SHA及冻结SHA/digest。不得从浮动main重建基线。

## 独占范围与依赖

- `backend/db/migrations/000007_answer_stream.sql` 唯一Owner Agent2；000001–000006原字节保留。不执行共享/生产DB迁移；用专用测试DB。
- `backend/internal/durablelivev2/authority/**` 为隔离v2持久层/Authority包，必要既有 `backend/internal/durablelive/**` 语义复用限Agent2；v1生成DTO/spec不得改为v2。
- 依赖Agent4 `backend/internal/durablelivev2/wire/**`；生成器/DTO/Context不自行维护。Registrar可信物理来源、HTTP路由/角色装配和Session/Binding由Agent4接线。
- `runtime/app/durable_live_journal.py` 的Journal语义需求交patch与测试给Agent4，不直接改公共Runtime路径。新handlers在authority模块导出，不自行挂到main/server。

## 分阶段交付

1. Additive表/不可变约束/FK及授权scope：trusted process/install mirror、DB-time stage challenge、bootstrap sidecar、Artifact child、actual text/hash/product/facts、prepare alias/receipt、ticket verifier、consume nonce/identity、唯一Grant latch/execution及知识投影。按冻结handoff现有表边界实施，不建立第二业务数据库。
2. 实现注册/撤销、Authority Query/Commit/metadata、Prepare/START/Continuation/当前Permit+FactObservation/Drain/Seal、UNKNOWN/Stop与恢复投影。Backend独占持久写；受限Guardian调用不能获得CONTROL/任意SQL能力。不能把生产实现替换成reference oracle。
3. Register/Commit当前权限、run/lease/slot/Attempt、源mirror版本、DB时间、CAS和Stop同锁域短事务；外部source/fact preflight在事务外，事务内复核镜像权威版本。Agent4可信来源尚未接入时使用明确拒绝或测试fixture，不能默认可信。
4. 原文/Hash/事实版本/receipt/CAS原子提交；ticket与Grant同事务，仅存verifier，首次true响应不可重放。重复提交无新执行权；ACK丢失/已STARTED/UNKNOWN不重发、删latch或自动重播评论。

## 验收与交付

真实专用PostgreSQL空库与000006升级/data preservation、repeat/concurrent migration runner、多连接唯一Grant/execution/nonce竞争、跨owner/Room/session拒绝、Prepare alias/Drain身份冲突、Stop×Register/Commit/CAS、事务rollback、提交后进程崩溃/ACK丢失、商品/事实/Binding过期、旧Epoch与UNKNOWN保留。查询候选/历史必须授权且一致，不将未返回解释为空。证明无DB事务等待网络；恢复不绕过新Provider Binding。

保留137契约/11Journal、Go/race/vet与旧v1回归。提供base/head/依赖DTO SHA、migration编号、原始SQL/进程日志和未运行列表。应用rollback保持v2准入关闭并保留active/UNKNOWN/去重/审计数据，不写破坏性down。PR目标integration；由Agent4审核合入，不碰main或其他Worktree。真实Guardian/GPU不是本模块PASS的推论。
