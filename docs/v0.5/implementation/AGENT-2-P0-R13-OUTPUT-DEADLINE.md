# Agent2 — P0-R13-OUTPUT-DEADLINE 修复交接

状态：修复候选已完成组件验证，**请求 Agent4 对新 SHA 独立正式复审**；不代表生产输出安全验收，不合并 PR13/main，不开启 Durable LIVE/GPU。

原阻塞 HEAD：`0230d93cbcb1a353ba2270670d26fcf467cd1c21`。[Agent4 完整报告](https://github.com/leileiya1/AstraLive/pull/13#issuecomment-6243810117)。同一 Worktree `AstraLive-agent-2`、分支 `feat/v05-durable-recovery`，起始工作区干净。先 fetch、核对 PR HEAD，再原样复现；随后正常 merge 固定 integration 审查基线 `e9698923c6ed367ef31befc1e137811624b9ef20`，仅接入 Agent4 的审核文档/证据。没有 reset、stash、clean、force push、新分支或新 Worktree。

唯一 DTO 依赖仍为 `e3302f6b2bb19e0184cde3a6cbbcaf3ea4371565`。冻结 SHA `c7fd46209d3cbc6f58541dba8b4e1c85609c823e`，独立重算22文件完整 digest 为 `3c0c317ed00f6fa4d2cf15ef3f61fc002d4bb22bf02d53ee9f1b407458bb28b1`。本轮消息中的 digest 有省略，以固定冻结文件/manifest及 Agent4 原报告中的完整值核验；未修改 manifest、22规范文件、000001–000007或官方 DTO。

## 原样复现与修复

从 integration 审查 SHA 读取 `agent4-authority-boundaries.go.txt` 到自己新建的临时测试目录。用 Go overlay 将该原始文件映射为测试；修复前仓库 HEAD 与报告完全对应。原始源码 SHA256 `0bf24152b3bd99016f12b486d1de960bd398be53d4d7ae0136c4df023193f91c`，正式纳入本模块的 `output_deadline_agent4_test.go` 与其原字节一致，sleep/断言均未更改。

| 原始案例 | 修复前真实 PG/race | 修复后同一源码 |
| --- | --- | --- |
| A：Output +150ms，最终 Consume response 校验暂停220ms | FAIL；过期仍 true，latch=1 | PASS；拒绝正授权；加强回归额外验证 latch/副作用回滚 |
| B：START 后缩短 Output 到+250ms | FAIL；remainingProofMs=786，validUntil 越界 | PASS；validUntil/当前预算均不越过当前 Output 截止时间 |
| C：Prepare 后缩短 Output 到+250ms | FAIL；Permit TTL=800，expiresAt 越界 | PASS；Permit/FactObservation 期限受实际截止时间约束 |

[原始命令与输出](../evidence/agent-2/p0-r13-output-deadline/) 保留 before/after JSONL、源码、完整 BLOCKED 评论、全套命令/exit code、SQL环境和源码哈希。修复前失败未删除或改写成 PASS。

实际修复仅在 Agent2 独占 Authority：

- `state.registered` 在原有 installation/process/output 共享锁域读取真实 `o.expires_at`，保留 `outputExpiry` 并纳入 `state.limit`；未移除原有效性谓词。Runtime 请求不能设置或延长这个可信来源期限。
- `state.limit` 取当前 lease、Provider Binding、command/answer deadline、Output、当前 Permit/FactObservation 的最早截止时间。首次消费额外交集原始 Grant/初始证明；持续 Query/续证不以已消费 Grant 的旧 deadline 截断合法长句。
- 新 Permit/FactObservation、新签发的首次 Grant 均被当前上界截断。Query 保留原不可变 Grant/Permit/Observation body，用已有 `validUntil` 和 `timing` 表达**当前资格的交集**；不能把旧 Permit 的较晚 expiresAt 单独视为当前授权。
- 事务末尾在本地 response validator 后读取 DB `clock_timestamp()`，检查当前最早期限。过期返回错误并回滚，包括已执行的 latch INSERT。首次 true START/Continuation/Consume 还必须保留冻结的100ms安全边距；不增加容忍窗口。
- 相对 proof/consume budget 在最后一次 DB-time 检查后重算，Query 的 authorityTime 同步更新，避免把 validator 等本地耗时返还给客户端。校验与 Commit 之间没有应用 callback/RPC；网络交付、Guardian最终 gate/ACK/Runtime deadline 检查仍不可省略。
- 注册使用的临时 state copy 也传递其更早的有效期限，避免丢失 Output 上界。没有新 wire 字段、私有操作、迁移或播放状态。

## 并发含义与证明边界

可信 Registrar/output mirror 更新遵守既有 Run→output 锁顺序；测试覆盖另一事务先提交缩短、以及后发 writer 被既有 output SHARE lock 阻塞。前者授权读取新 deadline；后者不能在最终检查与 SQL Commit 之间插入修改，提交后的新请求拒绝已撤销资格。时间不会被锁冻结，因此仍必须在最后检查 DB 时间。

已在撤销前线性化的 SQL提交/返回预算不能被数据库追溯撤回。跨进程传播继续依赖冻结的当前 proof、短 Permit、静态余量、独立 watchdog 和 Receiver最终 gate；不承诺网络零时延、实际媒体立即撤回或物理 exactly-once。这里没有修改 Guardian/Runtime/发布边界。

## 新增边界与回归

除了3个原始案例，增加14个顶层 deadline 回归，其中5个参数化组另含13个子测试。结果分别报告顶层和子测试数，不把聚合结果重复计为独立覆盖：

- expires_at 精确等于同一 DB clock 值；Permit/Query/Consume均拒绝。
- Permit、Query、Consume response校验期间 Output 到期；副作用回滚。
- Query最终预算扣除本地耗时，原不可变 Grant 不变。
- 另一事务在 Authority事务等待 Run锁时提交缩短；当前 Query/Consume使用新值。
- Permit/Query/Consume持有 Output共享锁时，另一个 output-only writer 无法越过最终提交；随后请求拒绝。
- 8个并发 Consume 与资格撤销竞争；包含所有请求已进入事务外预检、撤销先提交的确定性顺序。最多一个先行 winner，撤销后没有第二次 true。
- 合法消费后丢失 ACK、Output失效、标记 UNKNOWN并刷新 mirror；原 latch/CONSUMED Grant 保留，不能重新授权。
- Unit1可信 Drain后，同一 Attempt下 Unit2拥有独立 Grant/execution，期限仍有效且受当前 Output上界约束。
- 已消费单元可在原 Grant到期后刷新当前证明；额外连续每250ms刷新，跨越初始 Grant和原 Artifact事实元数据期限，期间没有 proof gap、没有第二次 START/TTS资格。
- Stop、UNKNOWN、旧 Epoch与Output失效组合拒绝；注册最终提交也检查有效期限。
- Permit后、START前 Output缩短时，首次不可变 Grant及consume budget被截断；更早Run lease继续优先。

原有30项 PostgreSQL Authority测试保留，覆盖旧v1隔离、Stop、唯一latch、事务回滚、未知状态、Unit2及owned commit→SIGKILL。物理安装/断言/Observer仍是显式测试fixture；没有实际口播或媒体运行。

## 完整结果与共享阻塞

最终准确结果、SKIP列表、命令、无overlay证明见 [summary.json](../evidence/agent-2/p0-r13-output-deadline/summary.json)。

- 专用真实 PostgreSQL 17.11、fsync on：Authority race全部通过；原始A/B/C、原30项和新增14项全部在内。顶层 helper SKIP由父测试专门启动，不等于未做 SIGKILL注入。
- 137冻结契约、11 Journal、13官方wire跨语言、候选/v1 validator、唯一生成检查：PASS。
- 原样完整 `go test ./...` 和 `go test -race ./...`：**仍 FAIL**，唯一失败为共享 `TestPostgresLegacyMigrationUpgradePreservesData` 将迁移数断言为6（实际7）；没有修改共享测试，没有迁移overlay，没有宣称整套PASS。Authority和旧durablelive包在原样运行中均PASS；`go vet ./...` PASS。
- Agent4负责明确000001–000007文件集合断言，以及非规范 protected-files 清单旧hash的精确preimage/postimage审计。本修复没有应用或修改这些策略；当前原样137/313保护哈希通过，不代表Agent4后续集成改动已经验收。

专用集群由本轮 `initdb` 创建，绑定随机 loopback端口，测试DB为 `agent2_v2_p0_output` 与 `agent2_v1_p0_output`。不读取共享 DATABASE_URL/Redis配置；不启动GPU。最终停止本轮自己的集群并保留 data/logs，见 cleanup.json。准确证据环境不含数据库口令或 consumeTicket。

## NOT TESTED / 请求 Agent4

真实生产 Registrar/source adapter、HTTP/IPC身份与时延、Guardian fsync/两层ACK/最终短gate、Worker/GPU/Publisher/Decoder/Sink/RTMP/WebRTC/观众、整机/跨主机故障、whole-server PostgreSQL或Redis outage 均 NOT TESTED。本轮无需修改共享 app/runtime、SQL权限或生产资源，未做新增GPU/媒体实验。

请求 Agent4 针对新完整 SHA，独立运行原始A/B/C及新增边界/完整回归，检查 earliest-deadline 与最终DB-time预算、已有消费/UNKNOWN/Stop/Unit2语义，并确认实际 Receiver使用当前 `validUntil/timing` 与全部身份条件；之后再决定是否解除P0-R13阻塞。共享迁移断言/保护哈希仍由 Agent4在其受控集成中处理。此文不是FINAL ACK或合并许可。
