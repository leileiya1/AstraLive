package durablelive

import (
	"context"
	"github.com/jackc/pgx/v5"
)

func scopeMatches(parent, child Object) bool {
	return str(parent, "tenantId") == str(child, "tenantId") && str(parent, "ownerId") == str(child, "ownerId") && str(parent, "runId") == str(child, "runId")
}
func (s *Store) savePlan(ctx context.Context, tx pgx.Tx, p Principal, r, q Object) (Object, error) {
	if e := notStopped(r); e != nil {
		return nil, e
	}
	if e := revision(r, q); e != nil {
		return nil, e
	}
	if str(r, "status") != "CREATED" && str(r, "status") != "PAUSED" {
		return nil, fault("STATE_CONFLICT")
	}
	if str(r, "status") == "PAUSED" {
		var unsealed bool
		e := tx.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM dl05_run_sessions WHERE run_id=$1 AND output_fenced_at IS NULL)`, r["runId"]).Scan(&unsealed)
		if e != nil {
			return nil, e
		}
		if unsealed {
			return nil, fault("OUTPUT_FENCE_UNPROVEN")
		}
	}
	bundle := obj(q, "bundle")
	plan := obj(bundle, "plan")
	segments := arr(bundle, "segments")
	order := arr(plan, "segmentOrder")
	if !scopeMatches(r, plan) || len(segments) != len(order) || str(obj(plan, "snapshot"), "productId") != str(plan, "productId") || hash(obj(plan, "snapshot")) != str(plan, "productSnapshotVersion") {
		return nil, fault("INVALID_ARGUMENT")
	}
	if e := owner(ctx, tx, p, "product", str(plan, "productId")); e != nil {
		return nil, e
	}
	var next int64
	e := tx.QueryRow(ctx, `SELECT COALESCE(MAX(revision),0)+1 FROM dl05_plans WHERE run_id=$1`, r["runId"]).Scan(&next)
	if e != nil {
		return nil, e
	}
	if num(plan, "revision") != next {
		return nil, fault("PLAN_CHANGED")
	}
	_, e = tx.Exec(ctx, `INSERT INTO dl05_plans(tenant_id,owner_id,run_id,plan_id,product_id,product_snapshot_version,snapshot,revision,generation_source,segment_order,document) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)`, p.TenantID, p.OwnerID, r["runId"], plan["planId"], plan["productId"], plan["productSnapshotVersion"], plan["snapshot"], plan["revision"], plan["generationSource"], plan["segmentOrder"], plan)
	if e != nil {
		return nil, e
	}
	for i, v := range segments {
		seg := v.(map[string]any)
		if !scopeMatches(r, seg) || str(seg, "planId") != str(plan, "planId") || seg["segmentId"] != order[i] || num(seg, "sequence") != int64(i+1) || textHash(str(seg, "content")) != str(seg, "textHash") || str(seg, "state") != "READY" || str(seg, "checkpointState") != "PLANNED" || seg["utteranceId"] != nil || str(seg, "idempotencyKey") != "segment:"+str(seg, "segmentId")+":initial" {
			return nil, fault("INVALID_ARGUMENT")
		}
		for _, f := range arr(seg, "factDependencies") {
			if str(f.(map[string]any), "productId") != str(plan, "productId") {
				return nil, fault("PLAN_CHANGED")
			}
		}
		_, e = tx.Exec(ctx, `INSERT INTO dl05_segments(tenant_id,owner_id,run_id,plan_id,segment_id,sequence,content,text_hash,state,idempotency_key,checkpoint_state,fact_dependencies,estimated_duration_ms,document) VALUES($1,$2,$3,$4,$5,$6,$7,$8,'READY',$9,'PLANNED',$10,$11,$12)`, p.TenantID, p.OwnerID, r["runId"], plan["planId"], seg["segmentId"], seg["sequence"], seg["content"], seg["textHash"], seg["idempotencyKey"], seg["factDependencies"], seg["estimatedDurationMs"], seg)
		if e != nil {
			return nil, e
		}
	}
	_, e = tx.Exec(ctx, `INSERT INTO dl05_plan_progress(tenant_id,owner_id,run_id,plan_id) VALUES($1,$2,$3,$4)`, p.TenantID, p.OwnerID, r["runId"], plan["planId"])
	if e != nil {
		return nil, e
	}
	_, e = tx.Exec(ctx, `UPDATE dl05_segments SET state='INVALIDATED' WHERE run_id=$1 AND plan_id IS DISTINCT FROM $2 AND state='READY'`, r["runId"], plan["planId"])
	if e != nil {
		return nil, e
	}
	_, e = tx.Exec(ctx, `UPDATE dl05_turns SET state='INTERRUPTED',finished_at=clock_timestamp(),revision=revision+1 WHERE run_id=$1 AND plan_id IS DISTINCT FROM $2 AND state IN ('READY','WAITING')`, r["runId"], plan["planId"])
	if e != nil {
		return nil, e
	}
	_, e = tx.Exec(ctx, `UPDATE dl05_runs SET current_plan_id=$2,state_revision=state_revision+1,updated_at=clock_timestamp() WHERE run_id=$1`, r["runId"], plan["planId"])
	return Object{"requestId": q["requestId"], "planId": plan["planId"], "runRevision": num(r, "revision") + 1}, e
}
func (s *Store) admit(ctx context.Context, tx pgx.Tx, p Principal, r, q Object) (Object, error) {
	if e := notStopped(r); e != nil {
		return nil, e
	}
	if e := revision(r, q); e != nil {
		return nil, e
	}
	t := obj(q, "turn")
	initial := str(t, "state")
	if !scopeMatches(r, t) || (initial != "READY" && !(str(t, "turnType") == "COMMENT" && initial == "WAITING")) || t["startedAt"] != nil || t["finishedAt"] != nil || num(t, "revision") != 1 {
		return nil, fault("INVALID_ARGUMENT")
	}
	if t["planId"] != nil && t["planId"] != r["currentPlanId"] {
		return nil, fault("PLAN_CHANGED")
	}
	typ := str(t, "turnType")
	sources := arr(t, "sourceIdentities")
	if typ == "COMMENT" {
		if len(sources) == 0 {
			return nil, fault("INVALID_ARGUMENT")
		}
		var expired bool
		e := tx.QueryRow(ctx, `SELECT $1::timestamptz<=clock_timestamp()`, t["expiresAt"]).Scan(&expired)
		if e != nil {
			return nil, e
		}
		if expired {
			return nil, fault("STATE_CONFLICT")
		}
	} else if len(sources) != 0 {
		return nil, fault("INVALID_ARGUMENT")
	}
	if typ == "SCRIPT" {
		var content, state string
		e := tx.QueryRow(ctx, `SELECT content,state FROM dl05_segments WHERE segment_id=$1 AND run_id=$2 AND plan_id=$3`, t["sourceSegmentId"], r["runId"], t["planId"]).Scan(&content, &state)
		if e != nil {
			return nil, e
		}
		if content != str(t, "inputText") || state != "READY" {
			return nil, fault("STATE_CONFLICT")
		}
	}
	// A source already admitted under any physical Session cannot become a new turn.
	for _, v := range sources {
		src := v.(map[string]any)
		var n int
		e := tx.QueryRow(ctx, `SELECT count(*) FROM dl05_comment_sources WHERE tenant_id=$1 AND owner_id=$2 AND run_id=$3 AND platform=$4 AND platform_room_id=$5 AND source_event_id=$6`, p.TenantID, p.OwnerID, r["runId"], src["platform"], src["platformRoomId"], src["sourceEventId"]).Scan(&n)
		if e != nil {
			return nil, e
		}
		if n != 0 {
			return nil, fault("COMMAND_CONFLICT")
		}
	}
	_, e := tx.Exec(ctx, `INSERT INTO dl05_turns(tenant_id,owner_id,run_id,plan_id,turn_id,turn_type,source_segment_id,source_comment_trace_id,priority,state,scheduled_at,expires_at,input_text,idempotency_key,document) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$15,$10,$11,$12,$13,$14)`, p.TenantID, p.OwnerID, r["runId"], t["planId"], t["turnId"], typ, t["sourceSegmentId"], t["sourceCommentTraceId"], t["priority"], t["scheduledAt"], t["expiresAt"], t["inputText"], t["idempotencyKey"], t, initial)
	if e != nil {
		return nil, e
	}
	for _, v := range sources {
		src := v.(map[string]any)
		_, e = tx.Exec(ctx, `INSERT INTO dl05_comment_sources(tenant_id,owner_id,run_id,source_receipt_id,platform,platform_room_id,source_event_id,trace_id,turn_id) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9)`, p.TenantID, p.OwnerID, r["runId"], src["sourceReceiptId"], src["platform"], src["platformRoomId"], src["sourceEventId"], src["traceId"], t["turnId"])
		if e != nil {
			return nil, e
		}
	}
	if e = bump(ctx, tx, str(r, "runId")); e != nil {
		return nil, e
	}
	return Object{"requestId": q["requestId"], "turn": t, "runRevision": num(r, "revision") + 1}, nil
}
func (s *Store) restore(ctx context.Context, tx pgx.Tx, p Principal, r, q Object) (Object, error) {
	// Run row lock serializes all repository writers; the following reads form one
	// consistent application snapshot without borrowing its transaction to callers.
	slot, e := loadSlot(ctx, tx, str(r, "runId"))
	if e != nil {
		return nil, e
	}
	snapshot := Object{"run": r, "bundle": nil, "completedPrefix": int64(0), "resumeSequence": int64(1), "decisions": []any{}, "unresolvedAttempts": []any{}, "slot": slot}
	if str(r, "currentPlanId") != "" {
		plan, e := jsonRow(tx.QueryRow(ctx, `SELECT document FROM dl05_plans WHERE plan_id=$1`, r["currentPlanId"]))
		if e != nil {
			return nil, e
		}
		rows, e := tx.Query(ctx, `SELECT document || jsonb_build_object('state',state,'utteranceId',utterance_id,'checkpointState',checkpoint_state,'updatedAt',dl05_stamp(updated_at)) FROM dl05_segments WHERE plan_id=$1 ORDER BY sequence`, r["currentPlanId"])
		if e != nil {
			return nil, e
		}
		segments := []any{}
		for rows.Next() {
			o, e := jsonRow(rows)
			if e != nil {
				rows.Close()
				return nil, e
			}
			segments = append(segments, o)
		}
		e = rows.Err()
		rows.Close()
		if e != nil {
			return nil, e
		}
		snapshot["bundle"] = Object{"plan": plan, "segments": segments}
		var prefix, resume int64
		e = tx.QueryRow(ctx, `SELECT completed_prefix,resume_sequence FROM dl05_plan_progress WHERE plan_id=$1`, r["currentPlanId"]).Scan(&prefix, &resume)
		if e != nil {
			return nil, e
		}
		snapshot["completedPrefix"] = prefix
		snapshot["resumeSequence"] = resume
	}
	rows, e := tx.Query(ctx, `SELECT attempt_id FROM dl05_attempts WHERE run_id=$1 AND last_checkpoint NOT IN ('COMPLETED','INTERRUPTED') ORDER BY created_at,attempt_id LIMIT 1000`, r["runId"])
	if e != nil {
		return nil, e
	}
	ids := []string{}
	for rows.Next() {
		var id string
		if e = rows.Scan(&id); e != nil {
			rows.Close()
			return nil, e
		}
		ids = append(ids, id)
	}
	e = rows.Err()
	rows.Close()
	if e != nil {
		return nil, e
	}
	attempts := []any{}
	for _, id := range ids {
		a, e := loadAttempt(ctx, tx, id)
		if e != nil {
			return nil, e
		}
		attempts = append(attempts, a)
	}
	snapshot["unresolvedAttempts"] = attempts
	rows, e = tx.Query(ctx, `SELECT document FROM dl05_decisions WHERE run_id=$1 AND action IN ('WAIT_FOR_EVIDENCE','SKIP_WITH_GAP','CREATE_NEW_TURN') ORDER BY created_at,decision_id LIMIT 1000`, r["runId"])
	if e != nil {
		return nil, e
	}
	decisions := []any{}
	for rows.Next() {
		o, e := jsonRow(rows)
		if e != nil {
			rows.Close()
			return nil, e
		}
		decisions = append(decisions, o)
	}
	e = rows.Err()
	rows.Close()
	if e != nil {
		return nil, e
	}
	snapshot["decisions"] = decisions
	return Object{"requestId": q["requestId"], "snapshot": snapshot}, nil
}
func (s *Store) yield(ctx context.Context, tx pgx.Tx, p Principal, r, q Object) (Object, error) {
	if e := notStopped(r); e != nil {
		return nil, e
	}
	if e := revision(r, q); e != nil {
		return nil, e
	}
	if e := checkEpoch(r, q); e != nil {
		return nil, e
	}
	slot, e := loadSlot(ctx, tx, str(r, "runId"))
	if e != nil {
		return nil, e
	}
	if num(slot, "slotVersion") != num(q, "expectedSlotVersion") {
		return nil, fault("BOUNDARY_CONFLICT")
	}
	if slot["activeAttemptId"] != nil {
		return Object{"requestId": q["requestId"], "state": "WAITING", "boundaryCheckpointId": q["boundaryCheckpointId"], "slot": slot, "runRevision": r["revision"]}, nil
	}
	if slot["boundaryCheckpointId"] != q["boundaryCheckpointId"] {
		return nil, fault("BOUNDARY_CONFLICT")
	}
	var valid bool
	e = tx.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM dl05_checkpoints c JOIN dl05_attempts a ON a.attempt_id=c.attempt_id JOIN dl05_turns t ON t.turn_id=a.turn_id WHERE c.checkpoint_id=$1 AND c.run_id=$2 AND c.run_epoch=$3 AND c.projection_status='APPLIED' AND c.state IN ('COMPLETED','INTERRUPTED') AND (t.plan_id IS NULL OR t.plan_id=$4))`, q["boundaryCheckpointId"], r["runId"], r["runEpoch"], r["currentPlanId"]).Scan(&valid)
	if e != nil {
		return nil, e
	}
	if !valid {
		return nil, fault("BOUNDARY_CONFLICT")
	}
	_, e = tx.Exec(ctx, `INSERT INTO dl05_yields(run_id,boundary_checkpoint_id,idempotency_key,slot_version) VALUES($1,$2,$3,$4)`, r["runId"], q["boundaryCheckpointId"], q["idempotencyKey"], slot["slotVersion"])
	if e != nil {
		return nil, fault("BOUNDARY_CONFLICT")
	}
	if e = bump(ctx, tx, str(r, "runId")); e != nil {
		return nil, e
	}
	return Object{"requestId": q["requestId"], "state": "YIELDED", "boundaryCheckpointId": q["boundaryCheckpointId"], "slot": slot, "runRevision": num(r, "revision") + 1}, nil
}
