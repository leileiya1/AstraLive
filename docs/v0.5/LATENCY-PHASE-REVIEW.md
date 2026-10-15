# hour-7 响应延迟独立复核（2026-10-15）

本次只读分析封存数据，没有启动 GPU、SSH、provider、录制或大录像解码，也没有修改 Runtime、Go、Timeline、sink、已有验收 oracle、契约或超时。工具基于 `aab062f`；被观测的历史直播源码是 `88a68246d46a3942515d9895247a3ebfe15e2e07`。这两者不是同一次运行的源码版本。

25 个已选中问题的 SQL 时戳和既有 Chrome 条件估算可以连成阶段链。**总条件估算 P50 9.374 秒、P95 12.093 秒、P99 12.408 秒，不能宣称达到 P50≤5 秒/P95≤8 秒目标。** 它们还不是已校准的 busy-comment SLA 或实际观众听到的时间。旧 hour-7 的整体 `FAIL`、Stop 失败和 1 个 `UNKNOWN` 尾段原样保留；本报告不会改写旧 Gate。

## 可量化阶段

单位为毫秒，全部 n=25；分位数按 `(n-1)*p` 线性插值。每行实际阶段和与该行总条件估算一致，最大差为 0 ms。各阶段的边际 P50/P95 **不能相加**。

| 阶段 | P50 | P95 | 证据及限制 |
| --- | ---: | ---: | --- |
| Go selectedAt → SUSPEND_REQUESTED 入库 | 150.147 | 175.554 | Go UTC↔DB 同主机时钟假设；这是控制记录，不是最后一帧/最后一个可听采样 |
| SUSPEND_REQUESTED → 边界 SEGMENT_COMPLETED 入库 | 4912.449 | 6708.360 | 同 DB 时钟的回执插入间隔，包含边界等待和完成/释放/入库开销 |
| 边界完成 → ANSWER BEGIN_EPOCH_ACTIVE 入库 | 365.195 | 405.403 | 同 DB 回执间隔 |
| ANSWER epoch → ANSWER_PREPARED 入库 | 189.500 | 192.301 | 同 DB 回执间隔；不能称为 LLM 耗时 |
| ANSWER_PREPARED → COMMIT_SEGMENT 命令 createdAt | 60.255 | 67.892 | DB↔Go UTC 假设 |
| 命令 createdAt → Inbox accepted 入库 | 34.705 | 40.614 | Go UTC↔DB 假设；含派发/本地调用/入库，不能称为纯网络耗时 |
| Inbox accepted → generating 入库 | 3.378 | 4.180 | 同 DB 回执间隔 |
| generating → SEGMENT_READY 入库 | 3381.583 | 5081.026 | 完整生成/存储/校验/入库包络；缺细分时钟锚点 |
| READY → COMMIT_INTENT 入库 | 7.173 | 8.626 | 同 DB 回执间隔 |
| COMMIT_INTENT → COMMIT_INSTALLED 入库 | 7.371 | 8.651 | 同 DB 回执间隔，不是物理播放开始 |
| COMMIT_INSTALLED → Chrome 相关音画 | 201.358 | 245.333 | **条件估算**，继承原条码+录制音频前缀匹配与跨时钟假设 |

同一批 25 行的均值总延迟为 8911.214 ms。边界记录等待均值 4137.378 ms、完整 READY 包络均值 3757.749 ms，两者占总均值 **88.60%**。这是实测回执包络的归因，既不是因果优化收益，也不证明每个物理动作的耗时。

## 独立时长与缺失锚点

- GPU descriptor 的 `resources.inference_elapsed_us` 为本轮 native inference 调用并同步后的累计耗时：P50 2167.332 ms、P95 3791.435 ms。源码 `gpu_worker/validated/adapter.py` 在每个 native block 的 inference 前后计时并累加；embedding、CPU readback、编码、传输、Runtime 解码与 TTS 不在该计时内。它与 generating→READY 包络重叠，**不作为另一段相加，也不将两者相减后命名为 TTS、编码或网络耗时**。
- 真实 `llm-calls.jsonl` 25 条全部是 `bridge_choice`：P50 676 ms、P95 1141.4 ms。这些是回答之后的 bridge 调用；没有 command/turn ID 或绝对开始/结束时间锚点，禁止按数组顺序强配到某个问题，也不计入首次答案响应链。
- 25 条实际 `answerPreparedCommands.answerText` 均非空。`runtime/app/narration.py` 只有缺少该文本时才调用 answer LLM；本次事实回答不能把 ANSWER_PREPARED 间隔包装为回答 LLM 优化结果。
- 缺少每 attempt 的 TTS first/final PCM、StageBegin/Begun、embedding、首尾 GPU block、首尾编码/传输/存储 ACK、Runtime decode/overlay 的可关联成功计时锚点。细分结果为 `NOT_VERIFIABLE`，新的细锚点实验为 `NOT TESTED`。
- 精确 interrupt decision→物理最后 narration sample 为 `NOT_VERIFIABLE`；SEGMENT_COMPLETED 是全部 required sinks 回执与 native release 之后的日志插入，不能代替物理 sample 或观众端声音。

## 身份、回执和时钟规则

新增工具只做后处理。对源 reference→SQL attempt/commit/descriptor 使用真实身份（包括 business attempt、command、run/timeline/Worker epoch）。**Inbox execution attempt ID 与媒体 business attempt ID 不同**，禁止直接用同名 `attempt_id` 硬拼；本工具由相同 command ID、receiptSeq、observationHash 和 producerIncarnation 精确回连实际 ACK 和 SQL receipt。

边界来自答案前一个真实 source ordinal 的 NARRATION segment，SUSPEND_REQUESTED 必须显式指向该 segment；ANSWER epoch 由同 session/run 下 `reason=ANSWER` 和目标 timeline epoch 精确关联。缺少标记返回未知，不找最近时间冒充。createdAt 只读取实际 COMMIT_INTENT 中已存命令的 commandId/type/createdAt 白名单，输出不复制 payload、lease 或 provider 配置。

`v05_receipts.observed_at` 在 migration 000006 中默认 `clock_timestamp()`；Timeline/journal INSERT 不提供外部 observed_at。故 DB 间隔可观测，但仍是**入库时间**，且没有独立排除 DB wall-clock 跳变。Go selectedAt/createdAt 与 DB 的映射假定同主机 UTC；未独立校准 NTP/时钟跳变。

Chrome 末段继承 hash-pinned `hour_metrics.py` 结果：原 source ordinal、sequence=0 的单一 rendered barcode，经 Chrome `timeOrigin+presentationTime/at` 定位，并用同录制的音频前缀与条码起点相对差估算相关音频。未假定录制第一 PTS=recordingStart。解码录制↔实际呈现/audio device 的映射仍未独立校准。它不是 phoneme lip-sync、track.recv→观众听到，也没有证明选择时确实 busy；`busyCommentSLA=NOT_VERIFIABLE`、`audienceAudible=false`、自然度 `NOT_TESTED` 保留。

## 可验证的下一轮 A/B 提案（未实施）

1. **自然语义段长度对照。** A 使用原自然段；B 对相同事实进行较短且完整的自然语义分段，优先评估 2–4 秒目标。两臂保持相同必需事实与覆盖 oracle、文本语义、captured product version、音色、speaker、语速、prompt 负载、评论问题/优先级/随机种子、模型和 feature flags。句段不能截断事实、不能切成 160 ms 小块、不能删事实来变快；若需改变提示结构应单独分层控制。先真实缓存 TTS 的本地预检，确认每段 cap 与同一轮内容总时长，再运行两臂真实 GPU/Chrome/RTMP。**这首先是工作负载/内容规划实验，缩短 fixture 不是代码优化证据。** 较短段可能增加段数、native block/pad、控制与生成空窗，不能预言 P95 一定改善。
2. **先补 READY 包络测量。** 提案为每个真实 identity 记录上述 TTS/embedding/native/encode/store/decode/READY 细锚点，使用本进程 monotonic duration、同 trace/17-tuple 关联，远程边界额外记录 RTT/校准误差。成功与失败路径都保留。先在本地协议/真实 CPU TTS 验证日志不泄露凭证、不能反向改变状态或 lease，再做真实 GPU 测量。只有证据定位了占用，才提出编码/CPU/传输的独立优化臂；不提前增大 queue/cap/timeout，不调整模型算法来掩盖指标。
3. **控制路径唤醒对照需另行设计审查。** 现 `Controller.Run` 是 100 ms polling，多步 ANSWER epoch/准备命令串行，测得约 0.5 秒边界后控制间隔。polling 是可能贡献之一（**INFERENCE**），不是已证明全部原因。可提案在事务提交后唤醒并保留 PG polling fallback；仍须重读 durable authority/Stop barrier，不跨 SQL 持有 Scheduler 锁，不以内存通知取代 PostgreSQL truth。未实现，不能直接许诺省去这些毫秒。
4. **边界期间提前 LLM/TTS 不可直接并行。** 若需要新增 durable preparation 命令、未来 epoch/generation 授权或改变当前单 active stage 顺序，必须先给出最小 CCR、状态/资源/取消设计并获确认。当前不执行。不得抢跑 GPU stage、storageACK 当 pose、预先提交/发布未授权媒体、借用当前讲解 generation 来生成下一段，亦不得跨 UNKNOWN 重播。

两臂正确性护栏：同事实不遗漏/不重复；只认可显式同版本回答覆盖；Stop/FORCE 优先、旧 run/timeline/generation/Worker epoch 拒绝、全部 required sinks 连续 audio+video 回执、精确 pose ACK、native safe release、UNKNOWN 禁止下一 generation/盲目 replay、原 TCP/Redis/default-off 回归。人工自然度与真实 audible 验收单独做，不从 metadata 推导。

下一次 hour gate 必须是**新 source/new run 的完整新数据**，单 session/同 peer/连续时长/明确检查点和 normal Stop+binding release；完整记录 selected/rejected，单独证明选择时 busy，再计算 P50/P95/P99 和时钟误差。不得继承旧 9.374/12.093 秒，也不得拼接多次运行时间。两臂均失败/删失项和 `NOT_VERIFIABLE` 必须入报告，不能只取成功快速样本。

## 复现与证据

在仓库根目录运行（stdlib Python 3.9+）：

```sh
python3 -m unittest discover -s integration/v0.5/tests -p test_latency_phases.py -v
python3 integration/v0.5/latency_phases.py \
  --sql docs/v0.5/evidence/integration-f/real-hour-tcp-7/media/sql-proof.json.gz \
  --refs docs/v0.5/evidence/integration-f/real-hour-tcp-7/media/staged-observer/refs.json \
  --metrics docs/v0.5/evidence/integration-f/real-hour-tcp-7/analysis/astralive-f-hour7-metrics.json \
  --llm docs/v0.5/evidence/integration-f/real-hour-tcp-7/media/staged-observer/llm-calls.jsonl \
  --output /tmp/hour7-latency-phases.json
```

本次 **15 个 synthetic evidence 拒绝/兼容性测试 PASS**。覆盖伪 observation hash/producer/seq、foreign run/business attempt/Chrome marker、缺锚点、重复控制、时钟倒退、未知录制结果、非有限数、RFC3339 时钟规则、禁止用最终 updated_at 补 READY、禁止把 bridge 按顺序配给答案，以及跨原始 SQL 的估算复用。它们不是新的真实 GPU/Golden PASS。

真实封存数据回放 25 行归因、0 行拒绝；原始 `/private/tmp` 与仓库持久 gzip 备份复跑除输入文件路径/压缩原始字节 hash 外，报告完全一致。首次系统 Python 3.9 对合法五位小数秒的 stdlib parser 拒绝保留在独立 tmp 失败文件，随后显式 RFC3339 1..9 位解析修复并新增测试；不将此工具错误改称真实直播失败。

交付：[`report.json`](evidence/acceptance-b-recheck/hour7-latency/report.json)、[`run.json`](evidence/acceptance-b-recheck/hour7-latency/run.json)、[`unit-tests.log`](evidence/acceptance-b-recheck/hour7-latency/unit-tests.log)。报告含 source、原始/解压输入 SHA256、工具 SHA256、逐 turn 阶段与未完成尾段；run 记录基线与实际命令。没有复制全长录像、凭证或完整 payload。
