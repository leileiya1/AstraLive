# Agent5 — Guardian v2 and continuous output task package

状态：任务包已准备，未在本轮派发/启动。沿用AstraLive-agent-5 Worktree/现有分支，只同步[baseline](../IMPLEMENTATION-BASELINE.md)公布的完整pin；不创建/编辑Agent4工作树。先读冻结Receiver/Stop规则与[ownership](ownership.json)。

## 独占范围与依赖

`output_guardian/**`、`infra/guardian/**` 的隔离v2 IPC/receiver/Authority client/输出adapter由Agent5实施。生产wire共用Agent4 Python契约包；Authority依赖Agent2，可信process/install/challenge/Session/Binding及Runtime客户端由Agent4负责。既有v1保持隔离，v2不fallback到attempt-only v1 bind，不增任意SQL写权限或Runtime CONTROL权。现有runtime/app/guardian_media.py与其他Runtime热点修改提交patch给Agent4。

## 分阶段交付

1. 先完成版本化私有IPC/角色/实际进程凭据/独立channel和当前registration身份核验，13操作只按冻结协议。CONTROL install读→closed Stage→Backend登记在Permit/START前。两个Runtime竞争唯一Backend latch；Query/普通receipt不能还原ticket/true ACK。
2. 实现短gate与独立不可逆Run Stop：最终Consume ACK/激活、Renew、Media有界接收/ordinal、Finish与Stage/Stop/Restart同一同步边界。RPC/fsync/Observer/网络/backpressure在gate外；返回后及最终动作前复核barrier、完整身份和证明。Commit已消费但Stop/ACK丢失只留UNKNOWN audit，绝不重授。真实deny-replay temp/file/directory fsync失败/重启保守关闭。
3. 连续Publisher/Decoder/Sink保留Session PCM/PTS/Credit：正常单元Finish不终止整个Session发布，也不重绑Generation/重置媒体时钟；Unit2用新Artifact/Grant/execution接续。提交时捕获原lineage穿过IPC、队列、子进程、encoder/mux、decoder和每个required sink，实际不可逆边界复核可撤销barrier/身份。旧单元不能重贴current slot；不只在父进程加锁就宣称输出fence。
4. Observer证明真实终止单元尾部和全部required连续ranges；AAC延迟/解码尾部/WebRTC required evidence必须有可靠关联。enqueue/PCM生成/packet计数/Worker Credit不能代替drain，缺任何required sink则UNKNOWN，不推业务cursor。
5. 在既有独立Guardian资源所有权方案下完成Linux/容器UID、socket/网络、publish凭据归属和旧连接/旧key物理隔离。新Epoch激活前证明旧输出被隔离，Guardian重启未知输出关闭。凭据不下发Runtime/前端/日志。阻塞边界无法实现时保留OUTPUT_FENCE_UNPROVEN并报告，不能放宽协议。

## 验收与交付

仅使用专用CPU测试进程、DB/Redis和发布目标，不杀共享Worker/服务，不运行GPU。真实IPC不同role/channel/进程替换拒绝；两Runtime一次消费；两层ACK丢失、物理fsync失败/restart；本地Stop先于Backend的A/B/C原交错；Stop×Consume/Renew/Media/Finish/Restart；远程RPC/fsync/Observer暂停时Stop不阻塞；实际子进程/队列/decoder/sink的旧输出撤销；双Epoch/Permit过期/Guardian crash；Unit1真实drain→Unit2连续时钟和迟到旧媒体拒绝。

分别给出源码、CPU/Mock、真实PG、真实进程/IPC、实际CPU媒体/Decoder/Sink、Linux/容器隔离、未测GPU/Chrome/官方观众状态。真实RTMP本地解码不等于官方观众；短样本不等于24小时SLA。保留137契约/11Journal与原25项Guardian回归，失败/skip和清理证据完整保存。

交付独立增量PR至integration，列出wire/Authority/Registrar依赖SHA、兼容旧v1方案、资源上限和rollback，Agent4审查后合入。所有生产入口默认关闭，不改冻结规范、SoulX TCP Binary Wire、PTS/Credit、模型或其他Owner文件。
