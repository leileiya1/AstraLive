# Guardian receiver-1 acceptance — 2026-10-17

**OUTPUT GUARDIAN BLOCKED**. 本轮交付隔离实现与真实 CPU/进程测试；没有启用
Durable LIVE，没有将 Mock 或 CPU Sink 当作生产 RTMP/WebRTC 所有权证明。

基线 `e98d8cf53d1aa5518f9c908785b7a5feae5117f8`，复用原 worktree/分支。
实现提交 `f43d308`；随后两个提交只补充 Restart/身份/真实 OS fsync 故障测试。
精确源码 SHA/hash、命令、退出码与环境见 [source manifest](evidence/source-manifest.json)、
[commands](evidence/commands.json)、[supplementary 1](evidence/supplementary-command.json)、
[supplementary 2](evidence/supplementary-command2.json) 和 [environment](evidence/environment.json)。

| 最终验证 | 实际结果 | 原始证据 |
| --- | --- | --- |
| 新 v2 模块 | **69 PASS / 0 FAIL / 0 SKIP** | [完整日志](evidence/guardian-v2-final2.txt)、[JUnit](evidence/guardian-v2-final2.xml) |
| 原 Guardian 回归 | **25 PASS / 0 FAIL / 0 SKIP** | [日志](evidence/guardian-original.txt)、[JUnit](evidence/guardian-original.xml) |
| 冻结契约 | **137 PASS** | [日志](evidence/contracts-137.txt) |
| Journal | **11 PASS** | [日志](evidence/journal-11.txt) |
| Runtime 原回归 | 169 项：**158 PASS / 11 SKIP** | [完整 skip 原因](evidence/runtime-unit.txt) |
| v2 validator | 132 definitions、25+13 operations、13 vectors、313 protected hashes、3 Stop traces PASS | [日志](evidence/validator-v2.txt) |
| v1 validator | 44 frozen files、20 operations、4 vectors PASS | [日志](evidence/validator-v1.txt) |
| lint / diff | PASS | [lint](evidence/lint.txt)、[diff](evidence/diff-check.txt) |
| 冻结/ownership 审计 | 22 文件原 hash 和 manifest 保持一致；共享 Runtime、GPU、Backend 零修改 | [逐文件证据](evidence/scope-and-freeze.json) |
| 清理 | 本 worktree venv 进程剩余0；测试 finalizers/kill/join/registry/socket 断言通过 | [清理记录](evidence/cleanup.json) |

Runtime 11 个 skip 是显式关闭的真实 provider/avatar/WebRTC/full-chain opt-in，
不是失败转为 PASS。Journal 包含在 Runtime 总数中，不能相加冒充更多覆盖。
原 Guardian 的真实专用 PostgreSQL/MediaMTX 验收属于 v1 回归，**不是 v2 SQL latch
或连续 RTMP drain 的验收**。Backend Go 回归没有重跑，本轮没有 Backend 改动。

v2 完整测试先后54/67/69通过，后两次增加测试，没有更改生产实现，也未覆盖早期日志。
具体分层如下：

| 本轮场景 | 已证明范围 |
| --- | --- |
| Stop A：本地先 Stop、Backend 尚 ACTIVE | 真本地 gate/持久日志 + Mock Authority；无新 latch/ACK，原 registration 不可 restage |
| Stop B：媒体准备后最终 handoff 前 Stop | 真实线程暂停大块 hash；Stop 完成后拒绝队列交付，ordinal 不前进 |
| Stop C：Consume 最后 proof、Commit/首次 Query 暂停时 Stop | Mock RPC 暂停 + 真 gate/fsync；ACK 不出现，已消费 latch 仅 UNKNOWN |
| Stop×Renew/Finish/Restart | RPC/Observer 在锁外暂停；不可回到 ACTIVE/STAGED，Run tombstone 不可逆 |
| Consume fsync 暂停 | 真实文件 fsync 线程暂停；独立 Stop **在释放该暂停前完成** |
| 两层 ACK 丢失 | Mock Backend 成功后丢 ACK；真实 Unix HTTP 首次 ACK 被弃读/断连后重连；绝不重新授权 |
| fsync 错误 | 注入 EIO；另有实际关闭 fd 后调用内核 fsync 返回 **EBADF**，分别覆盖文件和目录；都 UNKNOWN |
| fsync/SIGKILL/重启 | 真子进程在 file fsync 前/后、directory fsync 后被 SIGKILL；pending 拒绝启动或仅恢复拒绝信息 |
| Guardian SIGKILL | 专用真实 Guardian 进程死亡后，独立 watchdog 使其 CPU 子进程退出；新实例清理旧 PID/create-time 记录并 closed 启动 |
| 子进程在共享 gate 内 SIGKILL | 25ms 有界获取失败永久 poison；后续准入拒绝，独立 kill/join 不依赖该锁 |
| Unix 角色/实际进程/独立 channel | 真 AF_UNIX：错误 token/PID/create-time/incarnation/scope/role、其他真实进程盗用 token、两 channel 竞争、闭合 JSON/旧 v1 路由均拒绝 |
| 旧 epoch/Binding/Generation 等 | Mock Authority 返回替换的8类完整身份，不能替代 CONTROL 已安装身份，无 Commit/ACK |
| 异步子进程/Decoder/输出边缘 | 真 libav 进程分别暂停 encoder、decoder、output，先撤销 barrier 再释放；无迟到 CPU Sink 输出 |
| 每个 required Sink | 两个独立有界 CPU Sink，单独暂停其队列后 Stop；该 Sink 的最终边缘拒绝迟到 decoded 数据 |
| Unit1→Unit2 | 同一个真实 libav 进程/codec/decoder，不 flush、不重置 Generation。PCM `48000→49280→50560`，视频 PTS `3000000,3040000→3080000,3120000`，ordinal `120…127`，两次实际 decoded tail 对账 |
| 完整私有 IPC→CPU→Decoder→Sink→Finish→Stop | 真 Unix HTTP 和 CPU 音视频全链；实际解码1280 samples及2视频帧，Finish 保持原进程，Stop 后 OS PID 不存在 |
| Drain 拒绝 | 缺 registered Evidence builder、缺 required proofs、enqueue/counter 不能推进本地或业务 drain |
| Grant 初始过期/短 proof | 消费后续 proof 不依赖原 Grant 截止；本地过期 proof 不可被迟到 Renew 复活；RPC 超时不重试消费 |

以上 Authority、Registrar、契约 codec 适配及 Evidence 注册均明确使用 **test Mock**。
文件/目录 fsync、内核 EBADF、Unix 进程凭据、SIGKILL、libav 编解码、Sink bytes/ranges
是真实执行。EBADF 是 fd 故障，EIO 是软件注入；硬件损坏、断电恢复、主机挂起恢复未测。
Mock Evidence 虽符合冻结 schema，其 RTMP kind **不表示 CPU 输出曾进入 RTMP**。
完整 decoded 范围证明使用 payload hash、PCM 连续区间、逐帧 PTS/序号及真正终止单元 tail；
没有把 enqueue、packet 个数、TTS 完成或 Worker Credit 当检查点。

仍阻塞生产的条件：

1. Agent4 统一 DTO/可信 Registrar/安装读取/进程凭据及 Runtime 公共入口没有交付 pin；
   Agent2 v2 Authority transport/SQL 唯一 latch 没有交付 pin。没有自行替代它们。
2. 本机为 Darwin，没有 Docker/Podman。Linux 跨 UID、角色组 ACL、cgroup、网络 namespace、
   Runtime 绕过发布端口/生产凭据的对抗验收 **NOT TESTED**。模板未安装，不能当实证。
3. v2 连续 RTMP/AAC 延迟与解码尾部、WebRTC required ranges/ICE/TURN、真实旧 Publisher
   独占/旧 key 失效尚未接入和证明。旧 v1 的25项成功不填补此缺口。
4. 未运行 GPU/Worker、真实 TTS、Chrome、外部 RTMP/官方观众或24小时 SLA；原始 Credit
   行为仅保持代码不变，未宣称新的真实 GPU Credit 验收。

默认入口即使收到 LIVE 环境开关仍退出78/OUTPUT_FENCE_UNPROVEN。源码、资源上限、
启动/权限方案、严格恢复策略、回滚和 Agent4 适配接口见 [HANDOFF](AGENT-4-HANDOFF.md)。
开发过程中修复过 decoder 初始化、私有 Stage 路径及测试 fixture 等探测失败；说明见
[开发记录](evidence/development-findings.md)。没有降低 frozen assertions 或删改旧测试。
