# AstraLive v0.4 — 独立端到端延迟复核

2026-10-10，审计分支 `audit/v04-interaction-gate`，基线 main `59d96c8818a4512651a2f945ced71278929c9e12`。

**END-TO-END LATENCY: BLOCKED**。总体20样本的 Chrome 估计 P50/P95=2896.53/4176.80ms 复算一致，但P50保留误差范围跨过3秒；原始 clock request/response brackets没有保存，且音频关联不具备独立 trace marker。**已观测 DeepSeek Path: FAIL**：6条样本即使采用乐观时钟下界仍不满足P50≤3s、P95≤5s。二者分别报告，不能把总分位数解释为复杂问答成绩。

## 原始材料与可复核程度

输入为 `agent-b-real-browser.json`、`agent-b-real-summary.json`、`agent-b-real-prior-trials.json`、`agent-b-real-faults.json`、`agent-b-real-headless.json`。独立脚本 [revalidate-interaction-latency.py](../../scripts/revalidate-interaction-latency.py) 仅离线读取，全部统计、原文件 SHA256、样本 indices、分解和门槛见 [latency-recomputed.json](evidence/independent/latency-recomputed.json)。

还核对了 `/tmp/astralive-agent-b-real-private/browser-fixed20b.json`：20条 sample 和20条 attempts 与提交 JSON 完全相同。独立 RTMP 原始 `rtmp-full20.json` 的尾部保留6000行，其中13条样本的首音频/首视频记录均可逐对象匹配；前7条已从有界 deque 中滚出，不能声称全20条均在最终 receiver 原始尾部再次验证。可用 Runtime observed log 及检查的原 GPU-host Backend log 没有这次正常20样本的完整 trace 行；它们不能成为重新构建 Go/Runtime admission 时间的凭据。这些限制与 hashes 明确保留在 [original-evidence-audit.json](evidence/independent/original-evidence-audit.json)。

脚本独立确认：样本/attempt indices一一对应，20个不同TraceId/UtteranceId，terminal均completed，所有分段有限且非负，Runtime accepted→speakable→PCM→GPU receipt→media push→completed单调；Chrome/RTMP marker与generation吻合，首 Video PTS 与 speechOriginSample 时间轴吻合；所有已存 lower/upper 与 estimate±uncertainty一致。相关数字没有缺失样本被补0，也未删除最大延迟。

这证明 retained JSON 的统计和身份/时间轴内部一致；不能独立证明未保留的原始 clock exchange 时刻、每个音频波峰必定来自该 Utterance、每条原始日志或实际扬声器输出。

## Clock domain 与观测含义

| 观测 | Clock / 边界 | 能证明什么 |
| --- | --- | --- |
| Go comment_received→selected | 本机 Go monotonic | queue waiting；不是 source平台网络耗时 |
| Runtime admission→各stage | Runtime monotonic | Runtime内部相对时长；不能直接减 Go wall time |
| selected→first_speakable | observer把Go receipt age与Runtime clockOriginAge映射到Chrome，保留合计 uncertainty | 跨主机区间估计；dispatch ack不是精确Runtime admission |
| tts_first_pcm | Runtime收到非空增量PCM | 未证明观众已经听到 |
| avatar_first_generated_frame | Runtime收到当前 generation 的实际 GPU TALKING packet | 非Worker主机计算起点，非浏览器呈现 |
| Chrome audio | analyser首次非零波峰，performance.now | 已解码流观察；没有audio trace marker，也不是物理扬声器时刻 |
| Chrome video | marker、generation与expectedDisplayTime | 浏览器帧呈现估计；不是硬件屏幕回执 |
| RTMP | receiver_monotonic，decoded H264/AAC | 独立本地接收解码；不是官方直播平台观众播放 |

原始 observer 使用 request/response interval 中点和 half-width 对齐 age；算法没有直接相减不同主机 wall timestamps。统计脚本能检查已保存的区间，但未保存每次 q.start/q.end、原始 age/source receipt，使独立重建全部 offset 不可能。不能将报告过的 uncertainty 当作已独立再测量。

Chrome A/V onset 使用 `max(audio.at,video.displayAt)`；video有业务marker，而audio只是input发送之后第一次峰值。最终正常试验在前一语句完成后固定等待，不能用于证明“正在讲话时随机新评论”的可靠音频归属。GPU credit/FFmpeg pipe completion也不是观众音画播放时刻。

## 分位数与独立计算

经验 nearest rank：升序数组位置 `ceil(n*p)-1`。不是插值分位数，不是删掉慢样本后求平均，也没有把阶段P50相加冒充总P50。误差范围是各 sample lower、upper分别排序后的分位数，允许排序变化；不是简单给总P50加一个统一RTT。

单位毫秒。

| 路径 / receiver | n | P50估计 | P95估计 | 最大 | P50上下界 | P95上下界 |
| --- | ---: | ---: | ---: | ---: | --- | --- |
| Overall / Chrome | 20 | 2896.53 | 4176.80 | 6668.99 | 2598.93–3193.64 | 3924.75–4428.85 |
| Fast / Chrome | 14 | 2709.72 | 3238.89 | 3238.89 | 2433.84–2874.07 | 2948.19–3529.59 |
| DeepSeek / Chrome | 6 | 3973.84 | 6668.99 | 6668.99 | 3750.29–4197.39 | 6364.74–6973.24 |
| Overall / RTMP | 20 | 2974.99 | 4228.91 | 6754.45 | 2625.56–3248.74 | 3942.21–4515.61 |
| Fast / RTMP | 14 | 2734.35 | 3300.57 | 3300.57 | 2459.11–3000.01 | 2960.82–3640.32 |
| DeepSeek / RTMP | 6 | 4007.64 | 6754.45 | 6754.45 | 3762.59–4252.69 | 6381.65–7127.25 |

Fast Chrome 的 retained upper 可以满足两项数值目标，但n14、原始clock/audio约束仍在，且不是本轮修复后的新真实测量，不能升级完整验收为PASS。RTMP Fast P50 upper为3000.0057ms，不能通过四舍五入称为≤3000ms。LLM n6的P95采用max，样本不足以估计稳定人口分布；但该批已观测样本的两项目标明确未通过。

完整20条保留如下；详尽ID/边界与每条Runtime points仍在原JSON。

| index | topic / 路径 | Chrome A/V ms |
| --- | --- | ---: |
| 1 | price / Fast | 2589.28 |
| 2 | sizes / Fast | 3238.89 |
| 3 | stock / Fast | 2709.72 |
| 4 | size_stock / Fast | 2608.50 |
| 5 | chat / LLM | 3973.84 |
| 6 | consultation / LLM | 4059.46 |
| 7 | price / Fast | 2896.53 |
| 8 | sizes / Fast | 2993.22 |
| 9 | stock / Fast | 2925.21 |
| 10 | size_stock / Fast | 2653.67 |
| 11 | chat / LLM | 4176.80 |
| 12 | consultation / LLM | **6668.99** |
| 13 | price / Fast | 2718.73 |
| 14 | sizes / Fast | 2755.82 |
| 15 | stock / Fast | 2601.44 |
| 16 | size_stock / Fast | 2523.40 |
| 17 | chat / LLM | 3853.28 |
| 18 | consultation / LLM | 3723.47 |
| 19 | price / Fast | 2959.84 |
| 20 | sizes / Fast | 2306.54 |

## 独立阶段分解

每格P50/P95 ms，Fast n14、LLM n6。上下文仍包含跨主机观测误差。

| 阶段 | Fast | DeepSeek | 精度 |
| --- | --- | --- | --- |
| comment_receive→selected | 49.74 / 118.57 | 51.24 / 118.50 | Go本机；最终正常试验空闲时输入 |
| selected→first_speakable | 1161.24 / 1432.19 | 2366.39 / 4966.58 | Go/Runtime映射；非精确admission分解 |
| first_speakable→first_PCM | 123.61 / 167.52 | 77.55 / 79.93 | Runtime本机 |
| first_PCM→GPU packet | 1136.98 / 1486.62 | 1153.75 / 1473.06 | Runtime观察；包含原样本窗口/调度/收包 |
| GPU packet→Chrome video | 168.84 / 210.98 | 177.23 / 187.67 | Runtime/Chrome映射；非平台播放 |

复杂咨询主要在 first_speakable 之前增加耗时。其余阶段的 retained 数据不支持“通过删GPU缓冲/固定音画延迟就可达标”的改法。优先降低已知 Go/Tool/Runtime跨主机往返并改善观测，保留 PCM 时间轴、PTS、Fence与消费credit；不能在没有新真实证据时认定优化后的收益。

## 失败样本、先前试验和目标场景

最终正常run20 attempts全部completed、20条都有A/V onset；10人合并preflight是另一个已完成任务，属于正常input30/selection21中的非计时preflight，未冒充第21条计时样本。fault试验中的人工FORCE、interrupt、网络/Worker恢复单独列出，没有当作正常成功样本。

历史 prior trials 保留：2/2 preflight完成；两轮20请求各只完成5条，随后 directed request未选中（其中一次还有SSH中断）；另一轮setup failed，0 Session/0 samples。它们没有从档案删除，也没有与修复后最终run混合求好看的分位数。不能把最终run的0/20失败解释成整轮所有试验0失败。

本轮随机wall load 的 comment→selection P95已达到13–15秒；busy/backlog场景不能套用上表空闲样本的2.9秒总中位数。Fast、LLM、讲话中评论、高频混合与Operator FORCE五类需分别观测。当前READY Worker不存在，因此新真实五类试验BLOCKED；本轮没有购买/租赁/启动/重启GPU或执行hour soak。

## 更严格的下一次测试

1. 在隔离DB/Redis和空闲READY Worker上，用一个observer monotonic clock记录 Adapter ingress和实际Chrome视频/audio onset；尽量同机放置Backend/Runtime/Tool，减少观测与控制RTT。
2. 保存每个原始clock exchange的send/receive、age、TraceId、UtteranceId；输出各阶段上下界。无raw bracket的estimate只能作为估计。
3. 加入仅限测试的音频身份/PTS关联或独立loopback测量，不能用前一个讲话的非零峰值代表新回复；保留所有失败、超时与慢样本。
4. 分层采集足够Fast/LLM样本，以随机到达覆盖已有讲话、高频和FORCE。报告全部输入、selected、failed、expired/dropped、请求数和真实CPU/native/GPU资源；不可只筛选空闲成功任务。
5. 真正平台观众端与真人中文/唇形另设验收。任何local RTMP decode或Browser analyser都不得重命名为平台观众/扬声器PASS。

数值目标继续使用P50≤3秒、P95≤5秒，本轮没有更改统计口径或媒体协议。
