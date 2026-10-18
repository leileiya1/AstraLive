# Agent 3 — PostgreSQL streaming domain test report

**REAL POSTGRESQL DOMAIN INTEROP: PASS。** 此结论仅覆盖真实 PostgreSQL Authority/事务/CAS、正式 DTO 和隔离域编排；Receiver/Registrar/Observer 是显式 fixture，实际 IPC/TTS/媒体/required Sink 为 **NOT TESTED**。

固定 integration `235258ad75f7d271a279ea89fd88ddf80e797f31`，Authority merge `a4a57fcc0effd5dd5ea9689b355a963b007c20f3`，wire `e3302f6b2bb19e0184cde3a6cbbcaf3ea4371565`。原分支正常 merge，正式七条迁移原字节未改，未使用旧六条迁移断言或测试 overlay。冻结22文件及完整 digest 独立核对通过，见 [baseline verification](agent-3-postgres-evidence/baseline-verification.json)。交接见 [handoff](AGENT-3-POSTGRES-HANDOFF.md)。

## 运行命令与原始结果

复现命令（需要本机 PostgreSQL 17 的 initdb/pg_ctl/createdb/dropdb/psql、Go、已装项目测试依赖的 Python）：

```sh
python3 backend/internal/turnmanager/answerstream/run_postgres_interop.py --full --output /tmp/agent3-pg-final
```

Runner 每次新建专用 localhost 实例及三个独占数据库，拒绝使用外部 DSN/现存实例。`/tmp/astralive-agent2-python/bin/python` 仅复用 Python 依赖环境，不连接其服务；所有 PostgreSQL 均本轮独占。

| 实际命令 | 最终结果 | 原始证据 |
| --- | --- | --- |
| `go test -race -json -count=1 ./internal/turnmanager/answerstream -run '^TestPostgres'` | **18 顶层 PASS，61 含子测试 PASS，0 FAIL/0 SKIP**；14.101s | [JSON lines](agent-3-postgres-evidence/streaming-pg-race.txt) |
| `go test -p 2 -json -count=1 ./...` | 229 顶层 PASS /13 SKIP /0 FAIL；420 含子测试 PASS；17.978s | [JSON lines](agent-3-postgres-evidence/go-test.txt) |
| `go test -p 2 -race -json -count=1 ./...` | 同为229 顶层 PASS /13 SKIP /0 FAIL；420 含子测试 PASS；38.942s | [JSON lines](agent-3-postgres-evidence/go-race.txt) |
| `go vet ./...` | PASS，exit0 | [输出](agent-3-postgres-evidence/go-vet.txt) |
| 六组原契约 unittest | **137/137 PASS**，18.444s（进程18.639s） | [完整输出](agent-3-postgres-evidence/contracts137.txt) |
| 原 Journal pytest | **11/11 PASS**，0.41s | [输出](agent-3-postgres-evidence/journal11.txt) |
| 正式 Python wire unittest | **13/13 PASS**，2.141s | [输出](agent-3-postgres-evidence/wire13.txt) |
| v1/v2 validator、生成器 `--check` | 全部 PASS；未改冻结规范/生成器/SDK | [v1](agent-3-postgres-evidence/validator-v1.txt)、[v2](agent-3-postgres-evidence/validator-v2.txt)、[生成器](agent-3-postgres-evidence/generated-check.txt) |
| `SELECT * FROM schema_migrations` | 实际七条，含 `000007_answer_stream.sql` | [原始表](agent-3-postgres-evidence/migration-count.txt.gz) |

PostgreSQL原始表格/initdb日志以gzip保留原字节（含工具自带尾随空格）；`gzip -dc` 可读取，原始SHA见 [encoding manifest](agent-3-postgres-evidence/raw-log-encoding.json)。其余日志直接保存原文。

完整命令、运行目录、退出码、资源及耗时：[commands.json](agent-3-postgres-evidence/commands.json)。逐包计数和全部 skip：[go-summary.json](agent-3-postgres-evidence/go-summary.json)。20个有测试包退出PASS，另12个无测试文件；13个SKIP是测试，不以“全通过”隐藏。

原23项 Streaming（contentplan 12、turnmanager 11）全部保留；新增18项 PG 后两域包合计41顶层 PASS。原 `turnmanager` 26顶层 PASS/1可选导出 SKIP，包含持续讲解、TTL、公平、FORCE、Stop、恢复/UNKNOWN race；`interaction` 15顶层 PASS。真实 Authority 包在同一全量命令内47顶层 PASS/1子进程入口 SKIP（83含子测试 PASS）；正式 Go wire 8顶层 PASS。

13项SKIP为：App SQL锁审计1、Redis依赖2、v1子进程入口1、专用PG停服测试1、v2子进程入口1、HTTP配置/完整交互服务2、v1可选请求导出1、配置浏览器及独立配置环境3、旧事件服务集成1。子进程入口正常由对应父测试另行触发，不把直接入口SKIP冒充业务PASS。本轮没有启动Redis、浏览器或共享服务，也没有开启会停止测试实例的全量PG停服用例。

## A–J 实际证据

| 要求 | 真正执行的验证 |
| --- | --- |
| A：EOF前首句 | channel Source 阻塞Provider EOF；完整价格句已真实 Prepare、JournalStart 和 Backend消费 latch=1；未Seal。真实LLM/TTS未调用。 |
| B：双Unit/单START | 两条顺序各真实 Artifact=2、Grant=2、Latch=2、execution=2、COMMENT Turn=1；sequence1首次grant恰好1；第二条为Continuation，同Generation7；CONTROL完成前Slot一直占用，商品段仍READY。 |
| C：Prepare/Drain两序 | Prepare-before-Drain 时域Start和真实Backend Continuation均拒绝提前执行；Drain-before-late-Prepare 能继续。另阻塞2.1秒跨原FactObservation有效期后，Unit2经新同值观察正常Prepare/START，无ANSWER_GAP。 |
| D：CAS/幂等/并发 | 错误初始revision真实STATE_CONFLICT且0 Artifact；同请求并发/重试与Alias返回原revision，1 Artifact/0执行授权；不同合法描述符并发同身份时1成功、1ANSWER_CONFLICT。丢失已提交Prepare回包后，同一不可变Artifact/key重试，只有1 Artifact/1 Grant/1 Latch。 |
| E：商品事实变化 | Unit1完成后改变实际SQL价格、库存、updatedAt版本或activeProduct：旧Unit2 Check/Prepare/Start拒绝，保留Slot和READY商品段。删PRICE依赖并重哈希仍被真实Assertions拒绝。 |
| F：Stop竞争 | Prepare/首次START/Continuation分别测试stop-first、operation-first、race（9子场景）。Stop后不能再Prepare、START、Consume或Continuation，Grant/Latch不增长；Slot不被误释放。已真实消费后Stop截断合成ACK，正式MarkUnknown保留UNKNOWN和原Latch=1。 |
| G：ACK/UNKNOWN/旧身份 | 丢真实START/Continuation提交回包、丢真实Consume后合成ACK：正式持久UNKNOWN、拒绝重播和新适配器重新START。旧Epoch/输出Binding、Generation6 proof、Unit1旧proof用于Unit2均拒绝；新execution保持ACTIVE。丢LOCAL_MEDIA_DRAINED检查点回包也记UNKNOWN且不释放Slot。 |
| H：Seal/drain/CONTROL | 分别缺Seal、缺required drain，直接调用真实Completion也拒绝；补齐真实操作后才可CONTROL完成。单元Drain、甚至Seal+全部drain尚未CONTROL时Slot仍占用，商品段不推进。 |
| I：最早期限/续期 | Output在Acquire前过期、Grant后缩短至更早期限、Consume后缩短均检查；Authority snapshot.validUntil与相对proof budget不超过输出期限，过期后新证明/消费拒绝。原Grant/Permit超过1秒后，已消费单元取得新Permit并Query同execution仍CONSUMED，合法Drain无第二次START/TTS意图；消费前过期则无Latch。 |
| J：中文完整语义 | SQL来源的129.90元、XL/XXL/2XL、否定无S尺码、完整if/then、库存/材质原文真实入库/完成。错误价格、悬空条件、残缺转折、未证明比较、价格被句号割裂均fail-closed且无Artifact。重量/英文单位/比较关系完整性仍由原23项纯域正反样本覆盖；当前Projection不能证明这些字段，因此实际SQL适配拒绝，不伪造规则。 |

实际正文、textHash、artifactHash、productSnapshotVersion和PRICE依赖从真实数据库读回对比；不是只检查请求DTO结构。所有Answer/Inbox/Grant/Latch/Receipt/Drain/Checkpoint写均通过正式Authority操作。初始Run/COMMENT/Outbox/Plan是合成CONTROL admission，在原v1约束要求的原子事务里创建；场景只更改可信商品/输出/epoch源镜像，没有SQL直接把回答执行状态改成成功。

## 真实组件与合成部分

| 层 | 本轮性质 |
| --- | --- |
| PostgreSQL 17.11、七条正式迁移、事务/行锁/CAS/唯一约束/回执/授权/latch/检查点 | **REAL，运行通过**；fsync/synchronous_commit/full_page_writes=on。 |
| ProductProjection+products源值/哈希、正文语义与依赖分类 | **REAL SQL源投影与真实实现**；商品内容是测试数据；未接生产Tool入口。 |
| 正式Go DTO、EncodeRequest、Actor context、Handle结构/语义校验与真实响应 | **REAL，运行通过**；没有复制DTO或绕过Authority Handle返回成功。 |
| 已准入COMMENT、Run、Session、Binding、角色/进程、Registrar安装/Ed25519 stage来源 | **SYNTHETIC FIXTURE**；真实Authority验证/持久化，物理来源未验收。 |
| Receiver ACK/Guardian、Observer/SINK_ADMITTED/ALL_REQUIRED_DRAIN/RTMP_PIPE_WRITE范围 | **SYNTHETIC FIXTURE**；实际Consume事务和Observer登记/Backend校验是真实SQL，ACK/范围不是物理证明。 |
| Provider | 受控通道/字符Source，**非真实DeepSeek**；延迟只证明EOF时序。 |
| IPC/Registrar/Guardian fsync/Runtime once-TTS、PCM/GPU异步lineage、媒体/required Sink | **NOT TESTED**。 |
| Chrome/WebRTC/RTMP/观众/首句P50/P95/忙闲SLA、生产Durable LIVE | **NOT TESTED / OFF**。 |

## 故障历史、资源与清理

开发中四次focused运行曾失败：前两次是fixture未将既有admission与Plan/Segment放入原子事务，第三次是统计查询错误列名，第四次是fixture把预期Authority拒绝调用了Fatal而不是返回错误。已仅在Agent3测试中修复；没有修改Authority/SQL/协议。后续两轮中间全量和最终全量均exit0。原始失败输出、命令及每次清理保存在 [development-runs](agent-3-postgres-evidence/development-runs/)，总历史见 [history](agent-3-postgres-evidence/development-history.json)。

最终实例只监听127.0.0.1:60078；专用目录 `/tmp/astralive-agent3-stream-pg-pch3mf0n`。三个数据库全部drop，PostgreSQL正常fast stop且postmaster.pid不存在：[cleanup](agent-3-postgres-evidence/cleanup.json)、[stop输出](agent-3-postgres-evidence/stop.txt)。包括开发尝试在内7个自建实例均已停止、21个数据库均清理；保留空集群目录及诊断日志供追查，不删除其他Worktree或操作任何共享PG/Redis。Runner在数据库清理/实例停止不完整时退出失败。

最终命令子进程记录累计用户CPU 33.146s、系统CPU 10.082s；RUSAGE_CHILDREN累计peak RSS high-water 402456576 bytes（约384MiB），**不是每项独立峰值或数据库后台进程RSS**。Go GOMAXPROCS=4、全量-p2、PG pool<=16、单元32上限及原窗口/Token硬上限保留；无GPU、无音频缓存。实际PG配置原表：[inventory](agent-3-postgres-evidence/postgres-inventory.txt.gz)。

没有发现需要Agent2修改的阻塞接口。Agent4/5仍须接可信Registrar、ReceiverProofs、Stop及媒体续期/lineage，完成真实跨进程和required Sink证明。首句预算需计入ProductProjection/事实检查、Backend各次往返/事务、Registrar/Guardian fsync/ACK、Runtime once-TTS和媒体首帧；本轮不据契约/本地PG测试宣称达到任何首句SLA。
