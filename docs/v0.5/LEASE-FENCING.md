# Lease 与实际输出边界

## 控制权

Lease 使用 PostgreSQL 时间，默认 15 秒；续租以 owner + runEpoch + leaseVersion CAS，仅递增 leaseVersion。接管增加 runEpoch 并保留历史任期，先 PENDING_INSTALL，独立输出隔离与 Runtime 确认后才 ACTIVE。未来/旧 epoch 普通命令都不能自行安装 fence。

Stop 不需要获得当前 Lease，也不因调用者 revision 过期被丢弃。事务写 stopRevision/tombstone、撤销 Permit、关闭新准入并保存每个历史 Session 的 STOP Intent。只有输出隔离、Session 终止、Binding release 和控制清理全部证实后才 STOPPED；失败清理不重新开启媒体。

Service principal 的 instanceId 来自受信任注册器，不从 JSON 自报 owner 推导。Python producer 与管理 owner 不同，不能用 Runtime token 续租、创建 Turn 或管理 Run。

## 媒体边界

数据库中的任期数字只是授权的一部分。实现同时提供：

1. 持久短 Permit，绑定 Room、Run、Session、producer、runEpoch、leaseVersion、outputBindingVersion；最多 1000ms，不超过剩余 Lease。
2. Python 从发请求时的 monotonic 开始扣时，并减 100ms 安全余量，同时检查跨系统暂停的时钟；迟到的 Permit/START 响应不给 effect 授权。
3. `OutputGate.handoff` 在本地 sink 写入边界验证完整 Attempt/Utterance/generation 映射；过期、旧 epoch、旧 Generation、旧 Room binding 均拒绝。
4. watchdog 在没有下一帧时也关闭 sink。Stop/barrier 后迟到的 Permit 响应不能重新开输出。
5. Room output binding version 独立于 runEpoch。FAILED Run 的业务唯一约束释放，不代表旧 Publisher 已隔离；未有旧 Session 的隔离证明，新 Run 不能占用该 Room 输出。

`runEpoch`、Python generation、Worker epoch 和 GPU wire generation 是不同域。本实现不修改 `gpu_worker/validated/`、TCP、PTS、Credit 或 SoulX；集成适配器继续调用现有 Session/Worker ACL 与 Generation Fence。

## 部署门槛

OutputGate 的本地测试不是生产 Guardian 部署证明。生产必须有唯一受控 Guardian 持有 RTMP publishing 连接/凭据及 WebRTC peer，Runtime 不得有旁路发布权限；Guardian 的 OUTPUT_GUARDIAN principal 只能由受信任注册器登记。

`RuntimeControl` 的 install_fence、verify_stop、stop_session 回调必须真实关闭旧连接并验证持久 term/tombstone。缺少回调、Worker READY、实际授权、全 required sink 证明时拒绝准入。不能用 mock close() 替代生产隔离。Agent 4 负责部署、共享入口接线及真实媒体验收；本 PR 保持默认关闭。

允许物理推流中断。平台缓存可能继续播放，Session 重建不等同于 RTMP 无缝或观众即时静音。
