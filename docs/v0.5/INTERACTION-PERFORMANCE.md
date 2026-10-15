# Interaction Performance — 分开评价真实媒体与CPU策略

已阅读Agent C的 `docs/v0.4/LATENCY-REVALIDATION.md`、`INTERACTION-LATENCY-TRACE.md`和NEXT-PHASE-READINESS。历史长AUTO_SCRIPT中普通评论回复完成等待约17–19秒，高频选择等待P95约14.25秒；这是历史报告的忙场景，不能改称本轮Chrome首次关联音画结果。原sentence_stream改善首句TTS，未释放整个业务Utterance，故需要本轮段级边界。

| 口径 | 目标 | 本轮状态 |
| --- | --- | --- |
| 商品讲解期间：接收到Chrome首次关联音画 | P50≤5秒、P95≤8秒 | NOT TESTED |
| 空闲/低负载：接收到Chrome首次关联音画 | P50≤3秒、P95≤5秒 | NOT TESTED |
| 自然让出、恢复、checkpoint确认等待 | 分别测量，不加各阶段P50冒充总P50 | CPU流程已测；真实时间NOT TESTED |
| 真实DeepSeek/XiaoYa/SoulX、WebRTC、本地RTMP、官方平台 | 分端验证 | 全部NOT TESTED |

CPU用虚拟时钟验证完整商品计划与普通问题的自然边界，不运行模型或Chrome。3秒模拟段、第1秒收到问题只需等待当前段剩余部分，不再等待十几秒长Utterance；这验证了等待结构，不是实际5/8秒达标证据。LLM首token、TTS准备、GPU和平台缓冲仍会贡献延迟。目标段2–4秒也不是精确音频时长上限。

`turnmanager.Metrics`为集成提供有界观察器：FirstAVIdle/FirstAVBusy独立分布，YieldWait、ResumeWait、CheckpointWait、SilentGap分别统计。复用interaction.Stats的nearest-rank分位数；保留按时间顺序的尾部样本和总观测数量，不筛掉慢样本。所有ingress/selected/expired/drop/merge/dedup及segment/resume/duplicate/interruption计数均含完整分母。已有Scheduler仍负责原计数，不建立第二套选择算法。

Agent4应在真实观察器关联run/plan/segment/turn/attempt/utterance/generation后接入观察器。浏览器firstAV用关联音频与视频中较晚时间；跨主机时钟保留误差上下界。不能用HTTP202、首PCM、GPU返回帧或本地sink证据代替Chrome播放。仅已选择评论有回复时延，必须同时报告所有输入数量、选择率、过期率及未完成/超时样本，不只报最快选中者。

额外指标：segment_completed/segment_planned、resume_correct/resume_attempted、duplicate_explanation、interruption、comment_occupancy_ms/(comment+script)、所有本地静默间隔。CheckpointWait从LOCAL_MEDIA_DRAINED到BUSINESS_COMMIT；ResumeWait从回答commit到下一SCRIPT PLAYING。用户停止后的清理间隔不混入直播静默。CPU Fake故意不生成任何真实firstAV样本；缺失分布显示n=0，不填0ms冒充测试成功。

本轮CPU压力用例实际计数（Go原始日志）：5秒内100条独立评论，并各重复投递一次，共ingress=200、deduplicated=100、dropped=40、selected=3、expired=0，讲解完成10/10段。选中率为3/200全部投递或3/100独立原始评论；两者分母均保留。未选中评论不被当作快速回复，剩余候选和丢弃不从总体消失。这个短测试验证限流/有界排队与讲解不饿死，不是100条都已回答的吞吐测试。多人同XL单独用例由原Scheduler合并3条为1条，保留全部3个source；没有用大量普通重复问题稀释选择率。
