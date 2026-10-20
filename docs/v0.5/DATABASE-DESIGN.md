# durable-live-1 PostgreSQL设计（Agent 2实施）

> CCR-ADL-001 review at PR8 `01a752baf79c25d4d268167d016c8c62e754cfdf`: active durable-live-1 is preserved. [durable-live-2 incremental answer candidate](ccr/CCR-ADL-001.md) and [migration/owner handoff](ccr/CCR-ADL-001-HANDOFF.md) are PENDING OWNER ACK; this historical v1 freeze does not approve that upgrade.

本PR**不提交正式migration**。main当前到000005，Agent2独占下一migration：在本基线预留 `000006_durable_live.sql`；若集成目标已有000006必须CCR改用下一个空编号并映射表设计，禁止覆盖实验分支 `v05_*` 表。新增表统一 `dl05_*`，不是允许永久并存两套调度事实源；最终集成必须选择或迁移单一权威。

以下为规范列/约束设计；所有ID为text，所有时间timestamptz，version/epoch/sequence为bigint且positive，JSON integer≤9007199254740991。state用text CHECK（与schema枚举一致）；不是可绕过的自由字符串。通用created_at/updated_at NOT NULL DEFAULT clock_timestamp()，revision NOT NULL DEFAULT1，变更以expected revision CAS。不可变字段应通过repo白名单及DB trigger保护。

## 表、唯一约束与外键

所有表携带tenant_id/owner_id并FK `config_principals(tenant_id,user_id)`；父表提供 `UNIQUE(tenant_id,owner_id,id)`，子表使用同scope复合FK，不能只验证ID。run/room/product/session必须复用resource_owners核验；migration不认领legacy无owner行。scope不可由JSON客户端指定授权。

| 表 / 主键 | 列和约束 |
| --- | --- |
| dl05_runs / run_id | tenant/owner/room_id FK live_rooms；status/desired_state/recovery_policy；run_epoch≥0（未首次acquire时为0）；current_session_id/current_plan_id nullable；started_at/ended_at；stop_revision bigint default0、stopped_at、state_revision；UNIQUE(scope,run_id)。partial UNIQUE(room_id) WHERE status NOT IN ('STOPPED','FAILED') 防两逻辑run争一Room |
| dl05_run_sessions / run_session_id | scope/run_id/session_id，binding_id引用既有session_provider_bindings(binding_id)，introduced_epoch、retired_at、output_fenced_at；UNIQUE(session_id)、UNIQUE(scope,run_id,session_id)，FK scope/run；现有session必须与run.room及owner一致（事务+约束trigger）。绑定release后仍保留脱敏历史引用 |
| dl05_plans / plan_id | scope/run_id/product_id FK products、product_snapshot_version、snapshot jsonb、revision、generation_source、segment_order jsonb；UNIQUE(run_id,revision)、UNIQUE(scope,run_id,plan_id)；snapshot无secret；segment_order必须非空唯一，与segments序号用deferred constraint trigger校验 |
| dl05_segments / segment_id | scope/run_id/plan_id复合FK；sequence、content、text_hash、state、utterance_id nullable FK utterances、idempotency_key、checkpoint_state、fact_dependencies jsonb、estimated_duration_ms；UNIQUE(plan_id,sequence)、UNIQUE(run_id,idempotency_key)、UNIQUE(scope,run_id,plan_id,segment_id)。text_hash为64hex，序列连续由deferred校验 |
| dl05_turns / turn_id | scope/run_id/plan_id（可null）/turn_type/source_segment_id或source_comment_trace_id、priority、state、scheduled_at/started_at/finished_at、expires_at（COMMENT必有）、input_text、idempotency_key；CHECK按type二选一/null；UNIQUE(run_id,idempotency_key)；复合FK source_segment必须属于同run+plan |
| dl05_comment_sources / source_receipt_id | scope/run_id/platform/platform_room_id/source_event_id、trace_id、turn_id；UNIQUE(scope,run_id,platform,platform_room_id,source_event_id)，FK同scope/run/turn；合并多source映射一个turn，不能在新Session重新认领 |
| dl05_attempts / attempt_id | scope/run_id/turn_id/segment_id nullable/session_id/run_epoch/utterance_id/command_id、attempt_number、executor_incarnation、last_checkpoint、answer_text_hash nullable、required_sinks jsonb非空、range_proof jsonb；UNIQUE(turn_id,attempt_number)、UNIQUE(utterance_id)、UNIQUE(command_id)；FK同scope/run/session及turn/segment；不可变身份/内容 |
| dl05_run_slots / run_id | scope/run、active_attempt_id nullable、boundary_checkpoint_id nullable、slot_version；active_attempt FK同run；唯一一行，UNKNOWN也持占用直到输出隔离证明。不能仅partial unique ACTIVE状态来释放UNKNOWN |
| dl05_outbox / intent_id | scope/run/session/utterance/command/attempt/turn/idempotency_key/run_epoch、operation、request_hash、envelope jsonb、status/next_attempt_at/claimed_by/lease_expires_at、claim_version、send_started_at、attempt_count、last_error_code、created_at/updated_at；UNIQUE(command_id)、PostgreSQL16 `UNIQUE NULLS NOT DISTINCT(run_id,turn_id,operation,idempotency_key)`，turn_id显式FK；EXECUTE_TURN要求session/attempt/turn/utterance非null且epoch≥1；STOP_RUN/INSTALL_FENCE的attempt/turn/utterance必须null，CREATED阶段Stop可epoch=0且session=null，不创建虚假话轮。所有非null关联复合FK。命令payload不得含credential |
| dl05_runtime_inbox / command_id | scope/run/attempt/epoch、request_hash、status ACCEPTED/STARTED/TERMINAL/NOT_EXECUTED/UNKNOWN、receipt_id UNIQUE、revision、producer_incarnation、started_at/terminal_at、result_hash、executor_sealed_at；FK outbox(command_id)，NOT_EXECUTED要求sealed/no-effect proof |
| dl05_checkpoints / checkpoint_id | scope/run/session/attempt/command/epoch、event_id UNIQUE、producer_incarnation/producer_seq、state、last_known_state nullable、evidence_type/ref/hash、occurred_at、received_at、envelope jsonb、projection_status PENDING/APPLIED/QUARANTINED/HISTORICAL；UNIQUE(attempt_id,producer_incarnation,producer_seq)。append-only证据；投影状态可单列sidecar避免改原证据 |
| dl05_run_leases / run_id | scope/run、lease_owner、lease_expires_at、fencing_token、run_epoch、lease_version、phase PENDING_INSTALL/ACTIVE/SEALED；CHECK fencing_token=run_epoch；run保留epoch高水位，删除lease不允许重置 |
| dl05_output_permits / permit_id | scope/run/session/epoch、lease_version、producer_incarnation、guardian_id、issued_at/expires_at、revoked_at、fence_proof_ref；旧permit不能续用，最多1秒；scope/run/epoch FK到任期历史 |
| dl05_room_outputs / room_id | scope/room FK live_rooms；active_run_id nullable、output_binding_version单调递增、guardian_id、expires_at、fence_proof_ref；独占publisher权威，跨run亦不可重叠；permit携带room_id/output_binding_version复合FK；FAILED未隔离不能释放该输出权。此version不是runEpoch或Worker wire值 |
| dl05_run_terms / (run_id,run_epoch) | scope、owner、phase、previous_epoch、allocated_at/activated_at/sealed_at、required_sinks、output_fence_proof；保留所有任期与单调证明，不覆盖历史 |
| dl05_plan_progress / plan_id | scope/run/plan、completed_prefix、resume_sequence、revision；后者只可跨完整前缀与显式gap decisions；完成prefix永不跨UNKNOWN |
| dl05_decisions / decision_id | scope/run/plan/attempt可空、operator_id、action、reason、expected_revision、created_at；UNIQUE(run_id,decision_id)，不可变；记录Stop/Resume/skip/replay授权与持久幂等响应 |

循环外键：先建run（current指针空），再建run_sessions/plans，最后ALTER添加run.current_session/current_plan复合FK，DEFERRABLE INITIALLY DEFERRED。segments.utterance_id指向同run/session最新attempt需deferred trigger；attempt/outbox循环先创建attempt（commandId值，无FK），outbox引用attempt，最后deferred FK attempt.command_id→outbox.command_id。控制Outbox可无attempt，不得用伪造segment/turn填充外键。不能暂时用不校验JSON逃避关系。PostgreSQL16依据现有infra/compose.yaml；其他版本需Agent2给出等价partial唯一索引证明。

## 索引与并发认领

必要索引：outbox partial `(next_attempt_at,run_id,intent_id) WHERE status='PENDING'`；`(lease_expires_at) WHERE status='CLAIMED'`；`(run_id,run_epoch,status)`；turn `(run_id,state,priority DESC,scheduled_at,turn_id)`、COMMENT `(expires_at) WHERE state IN ('READY','WAITING')`；checkpoint `(attempt_id,producer_seq)`与`(run_id,received_at)`；run active status/updated_at；lease expires_at；comment source唯一索引；decision(run_id,created_at)。不能用created_at作为业务顺序。

认领算法（事务只做SQL）：

1. 无锁读到期候选run/intent ID；Begin；先锁 `dl05_runs WHERE run_id=$1 FOR UPDATE SKIP LOCKED`，无行即让给其他worker。
2. 按统一锁序读取lease/slot，媒体验证未Stop、DB time未过期、owner/epoch一致；INSTALL_FENCE验证pending任期；STOP_RUN验证tombstone并允许独立cleanup claim，不依赖媒体lease。再对指定run的到期outbox `ORDER BY next_attempt_at,intent_id FOR UPDATE SKIP LOCKED LIMIT 1`。
3. UPDATE状态CLAIMED、claimed_by、claim_version+1、lease_expires_at（不晚于run lease）；RETURNING不可变信封；Commit。**Commit后**才发送远程请求。
4. 返回处理按相同锁序+intent claim_version/owner/epoch CAS。过期claim一律RECONCILING；不能由清理线程直接改PENDING。下一任期不重用旧epoch envelope，新执行必须新attempt且遵守UNKNOWN政策。

lease acquire同run锁，DB-time检查expiresAt，CAS高水位+1；renew验证epoch/owner/version/未Stop。普通事务锁序run→lease/slot→turn→attempt→outbox→inbox→checkpoint/progress。跨run Room输出交接必须另用room_outputs→按run_id排序锁旧/新run的短事务；普通run事务不得反向获取room_outputs锁，permit核验采用已绑定版本快照并在guardian handoff重验，不能在发permit后允许旧新binding同时输出。输出切换两阶段撤销/隔离后激活。不在Scheduler/controller锁内调用repo。claim等待有限lock/statement timeout，不能无限持事务。迁移部署需advisory lock并单runner，Agent2负责在现有runner seam实现，Agent3不改migration。

## 保留、压缩、清理与回滚

默认可配置：原始评论/生成文本终态后7天脱敏删除；完整checkpoint envelope 30天后压缩为每attempt终态proof+range摘要/hash；终态run/plan/attempt/outbox/decision元数据90天后归档。活跃run、UNKNOWN、未完成清理、被引用证据不得TTL删除。幂等source tombstone、command key/hash、run epoch高水位及Stop tombstone至少保留到run删除；归档run仍禁止接收任何旧命令，runId永不重用。超过retention的事件只查归档拒绝重播，不能重新当新输入。

清理按受限batch事务（最多500行），先归档proof引用/脱敏，再删除子对象；active对象FK使用RESTRICT，无大范围CASCADE，不因删product/owner绕过审计。建议按月checkpoint分区但须维护全局event去重表；初版普通表加批次清理即可。不持事务做压缩/对象存储上传，先snapshot export后验证hash再标可删除。监控outbox最老年龄、UNKNOWN数、lease抢占、checkpoint缺口、清理积压，指标无comment/user labels。

上线只新增，不改000001..000005。rollback首先关默认off功能、拒绝新claim、完成Stop/隔离所有输出，导出UNKNOWN与审计；旧v0.4不得接手未停止的durable Session。应用回滚保留新表；DDL down仅在无active/UNKNOWN、归档校验后按反FK顺序删除dl05_*，不得删除/回写legacy Session/Utterance/receipt，不重置可存活run的epoch。Agent2需提供真实SQL竞争、FK、崩溃与回滚演练结果；本文不是已执行migration。
