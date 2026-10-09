# 2026-10-09 最新状态

`BLOCKED — LATENCY`。新端口 45713 实例按原 SHA/commit 恢复，53.605 秒达到预热 READY，统一 epoch 连续服务。私有 token＋SSH、4帧信用、隔离 Feature Flag。Worker 已停止，0MiB。

完整证据与边界见 [本次重试报告](SOULX-LIVE-RETRY-2026-10-09.md)。

---

以下是此前收尾记录；涉及旧实例与尚未执行事项，以本次重试报告为准。

# 私有 SoulX Worker 实现

最终状态：`SOULX STREAMING WORKER READY`。指独立实验 Worker 的增量 PCM、常驻模型、代际控制和私有传输已有证据；不代表正式直播集成验收。2026-10-09 按用户费用安排停止 Worker，不执行一小时测试。

代码位于 streaming/adapter.py、worker.py、wire.py、async_link.py、prefetch.py、resample.py。模型代码保持官方 commit 9bc03de06bb0de82cd6bc477804512ae06144bf2，Python3.12 / Torch2.8.0+cu128 / FlashAttention2.8.3 不变。独立 PyAV17.1.0 worker-deps 不改原环境。

GPU仅监听127.0.0.1:17087，经验证SSH主机密钥的两段私有隧道到school-linux，并验证随机token、protocol_version和worker_epoch。固定授权人物；输入图、官方代码、推理参数及完整实际权重SHA清单形成cache_id。无公网无认证RGB或推理接口。这是有认证的双向TCP MVP，尚非部署版gRPC；内部协议见 streaming/PRIVATE-PROTOCOL.md。

GPU_WORKER_READY要求模型、Avatar、特征/推理、9帧已消费姿态恢复、编码预热全部完成。600秒测试进程ready32.017秒；增强权重清单/健康机制后的进程ready39.234秒。两次都复用了现有编译缓存，不是179秒空缓存冷启动成本的重测。增强版本实际跑过真实LLM/TTS和多次浏览器短测，600秒证据属于此前版本；阶段B代码及ready/event快照单独保存于streaming/evidence/stage-b-sources和worker-*-stage-b文件。

H264/libx264：ultrafast、zerolatency、无B帧、GOP25；新generation重建编码器/解码器并从IDR开始。媒体PTS来自sample index。音频队列32000样本、partial<15360、固定128000历史样本；视频模型队列24帧、网络4帧credit。pose仅取远端真正消费确认的最后9帧，取消后拒绝旧GPU输出，无需重载模型。

控制处理不阻塞在PCM满队列；健康检查区分没有提交推理与已提交推理停滞。OOM/adapter error或无法安全结束GPU线程会关闭隔离进程，远端进程存活不等于ready。真正OOM/crash/推理卡死注入未做，不把网络断线试验说成全故障矩阵验收。

实测阶段A、600秒15000帧、错误token拒绝、CUDA推理中FORCE、真实浏览器断隧道回退，见其余报告。新增CPU检查11项（预取6、重采样2、异步credit3）；原Runtime测试25项在隔离副本通过。正式runtime/app的17份源文件SHA保持不变。

Worker PID93769已停止，最终GPU显存0MiB且无compute进程。临时Runtime、Backend和专用隧道也停止；租赁实例是否停止计费由云平台关机状态决定。
