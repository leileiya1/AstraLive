# 2026-10-09 最新状态

`BLOCKED — LATENCY`。已恢复相同模型与正确音频窗口；历史阶段 A 不重复伪装。本次真正公开 TTS 增量输入短测已执行，长测在浏览器音画门禁停止。

完整证据与边界见 [本次重试报告](SOULX-LIVE-RETRY-2026-10-09.md)。

---

以下是此前收尾记录；涉及旧实例与尚未执行事项，以本次重试报告为准。

# SoulX 真正增量 PCM 实验

阶段 A 机制/时间戳实验已完成；视觉动态验收与正式媒体链路仍独立。

已阅读全部七份前期报告，并核实 GPU、环境和官方 commit 9bc03de06bb0de82cd6bc477804512ae06144bf2 保留、上游无改动。Python3.12/Torch2.8/cu128 保持原状。

Adapter 不接收音频文件，只接收带格式、sequence、sample index、sample count、generation 和 EOF 的 PCM。Producer 在每段采集时长过后才发送，Consumer 在 EOF 前已经消费实际 GPU 帧。固定重算 8 秒滚动窗口，不重算不断增长的 WAV。wav2vec2 归一化、双向注意力和插值不允许把完整 embeddings 直接追加后宣称等价；保留官方有限历史路径。33 帧窗口、9 帧动作历史、每块24新帧，需15360新样本/960ms预缓冲。最后2帧特征邻域按官方方式钳位，没有缩短窗口或假设未来音频。

10/30/60 秒 × 20/40/100ms 输入均实际生成并完整解码250/750/1500帧。原始证据 streaming/validated/evidence。初版 generation2 姿态恢复触发新编译，首帧15.18秒；修复为将该路径加入预热并使用一致的 no_grad 模式。修复版该首帧1.36秒。

100ms 输入的长片曾有48–49ms消费迟到；明确增加120ms消费缓冲后，30/60秒回归最大迟到1.34/0.79ms。证据 streaming/playout-validated。旧版本证据没有覆盖。模型/特征/人物缓存常驻；EOF、350ms迟到、变长切片、20FPS慢消费者和FORCE均另有记录。缓存待机没有计入模型FPS。

Queue：32000 queued samples + <15360 partial samples + 128000 historical samples；24 queued frames；另有每次模型固定24帧块/临时回传数组及9帧已消费姿态，不能将这些在途数据隐去。

所有首帧指标须参照 AUDIO-VIDEO-LATENCY.md。Python消费/调度tick不是浏览器显示；MP4后期复用源音轨并不能证明实时音画同步。上游依据：[官方指定版本 stream 路径](https://github.com/Soul-AILab/SoulX-FlashHead/blob/9bc03de06bb0de82cd6bc477804512ae06144bf2/generate_video.py)。

收尾状态：SOULX STREAMING WORKER READY。用户选择不执行阶段C，Worker已停止。阶段A保留代表性60秒20ms/100ms片与Idle切换片；其他重复视频已删除，原指标与失败/成功日志保留。历史输出文件清理清单见STREAMING-CLEANUP-MANIFEST.json，不能继续用原文件总数宣称全部MP4仍在Mac。
