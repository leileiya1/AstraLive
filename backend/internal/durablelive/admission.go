package durablelive

import (
	"context"
	"github.com/jackc/pgx/v5"
	"time"
)

func (s *Store) claimTurn(ctx context.Context, tx pgx.Tx, p Principal, r, q Object) (Object, error) {
	if e := checkEpoch(r, q); e != nil {
		return nil, e
	}
	if e := revision(r, q); e != nil {
		return nil, e
	}
	lease, e := s.validLease(ctx, tx, p, r, "ACTIVE", true)
	if e != nil {
		return nil, e
	}
	if str(r, "status") != "LIVE" {
		return nil, fault("STATE_CONFLICT")
	}
	if e = s.validateSession(ctx, tx, p, r); e != nil {
		return nil, e
	}
	slot, e := loadSlot(ctx, tx, str(r, "runId"))
	if e != nil {
		return nil, e
	}
	if slot["activeAttemptId"] != nil || num(slot, "slotVersion") != num(q, "expectedSlotVersion") {
		return nil, fault("STATE_CONFLICT")
	}
	t, e := loadTurn(ctx, tx, str(q, "candidateTurnId"))
	if e != nil {
		return nil, e
	}
	waiting := str(t, "turnType") == "COMMENT" && str(t, "state") == "WAITING"
	if !scopeMatches(r, t) || (str(t, "state") != "READY" && !waiting) {
		return nil, fault("STATE_CONFLICT")
	}
	if t["planId"] != nil && t["planId"] != r["currentPlanId"] {
		return nil, fault("PLAN_CHANGED")
	}
	var now time.Time
	e = tx.QueryRow(ctx, `SELECT clock_timestamp()`).Scan(&now)
	if e != nil {
		return nil, e
	}
	if instant(t["scheduledAt"]).After(now) || (t["expiresAt"] != nil && !instant(t["expiresAt"]).After(now)) {
		return nil, fault("STATE_CONFLICT")
	}
	// A WAITING comment becomes READY only after the unique slot is free and
	// all epoch/lease/plan/TTL guards above have passed. Both FSM edges and the
	// attempt/outbox commit share this transaction; failed claims roll it back.
	if waiting {
		if _, e = tx.Exec(ctx, `UPDATE dl05_turns SET state='READY',revision=revision+1 WHERE turn_id=$1 AND state='WAITING'`, t["turnId"]); e != nil {
			return nil, e
		}
	}
	payload := Object{"mode": "OPERATOR_TEXT", "text": t["inputText"], "textHash": textHash(str(t, "inputText")), "productId": nil, "planId": t["planId"], "segmentId": t["sourceSegmentId"], "factDependencies": []any{}, "expiresAt": stamp(now.Add(15 * time.Second)), "requiredSinks": []any{}}
	var sinks []byte
	e = tx.QueryRow(ctx, `SELECT required_sinks FROM dl05_run_terms WHERE run_id=$1 AND run_epoch=$2`, r["runId"], num(r, "runEpoch")).Scan(&sinks)
	if e != nil {
		return nil, e
	}
	payload["requiredSinks"], e = decodeArray(sinks)
	if e != nil {
		return nil, e
	}
	switch str(t, "turnType") {
	case "SCRIPT":
		payload["mode"] = "SCRIPT_TEXT"
		var content, hashValue, state, product string
		var facts []byte
		var seq, prefix int64
		e = tx.QueryRow(ctx, `SELECT s.content,s.text_hash,s.state,s.fact_dependencies,s.sequence,p.product_id,pp.resume_sequence FROM dl05_segments s JOIN dl05_plans p ON p.plan_id=s.plan_id JOIN dl05_plan_progress pp ON pp.plan_id=p.plan_id WHERE s.segment_id=$1 AND s.run_id=$2 AND s.plan_id=$3`, t["sourceSegmentId"], r["runId"], t["planId"]).Scan(&content, &hashValue, &state, &facts, &seq, &product, &prefix)
		if e != nil {
			return nil, e
		}
		if state != "READY" || seq != prefix || content != str(t, "inputText") {
			return nil, fault("STATE_CONFLICT")
		}
		payload["productId"] = product
		payload["text"] = content
		payload["textHash"] = hashValue
		payload["factDependencies"], e = decodeArray(facts)
		if e != nil {
			return nil, e
		}
		// Only an authoritative preflight may refresh timestamps. Preserve every
		// assertion identity/hash; save fresh dependencies in this new immutable
		// command, never rewrite the stored plan or an already-issued envelope.
		if approval, ok := ctx.Value(factApprovalKey{}).(factApproval); ok && approval.hash == hash(arr(payload, "factDependencies")) && time.Since(approval.at) < 2*time.Second {
			payload["factDependencies"] = approval.fresh
			approval.hash = hash(approval.fresh)
			ctx = context.WithValue(ctx, factApprovalKey{}, approval)
		}
	case "COMMENT":
		payload["mode"] = "COMMENT_QUESTION"
		payload["expiresAt"] = t["expiresAt"]
	case "SYSTEM":
		payload["mode"] = "SYSTEM_TEXT"
	}
	if e = s.validatePayload(ctx, tx, p, r, payload, true); e != nil {
		return nil, e
	}
	attemptID, uttID, commandID, intentID := freshID("att"), freshID("utt"), freshID("cmd"), freshID("intent")
	trace := str(t, "sourceCommentTraceId")
	if trace == "" {
		trace = str(q, "requestId")
	}
	cmd := Object{"schemaVersion": "0.5", "contractRevision": RevisionName, "tenantId": p.TenantID, "ownerId": p.OwnerID, "runId": r["runId"], "sessionId": r["currentSessionId"], "commandId": commandID, "intentId": intentID, "attemptId": attemptID, "turnId": t["turnId"], "utteranceId": uttID, "runEpoch": r["runEpoch"], "leaseVersion": lease["leaseVersion"], "idempotencyKey": t["idempotencyKey"], "traceId": trace, "createdAt": stamp(now), "operation": "EXECUTE_TURN", "payload": payload}
	cmd["requestHash"] = commandHash(cmd)
	if e = validate("RuntimeCommand", cmd); e != nil {
		return nil, e
	}
	source := "OPERATOR"
	switch str(t, "turnType") {
	case "SCRIPT":
		source = "AUTO_SCRIPT"
	case "COMMENT":
		source = "PLATFORM_EVENT"
	case "SYSTEM":
		source = "SYSTEM"
	}
	_, e = tx.Exec(ctx, `INSERT INTO utterances(id,session_id,source,text,priority,interrupt_policy,status,trace_id) VALUES($1,$2,$3,$4,$5,'QUEUE','QUEUED',$6)`, uttID, r["currentSessionId"], source, t["inputText"], num(t, "priority"), trace)
	if e != nil {
		return nil, e
	}
	// Preserve the legacy receipt key, but never treat RESERVED as no-effect proof.
	if str(t, "turnType") == "COMMENT" {
		tag, e := tx.Exec(ctx, `INSERT INTO interaction_receipts(session_id,trace_id,status,utterance_id) VALUES($1,$2,'RESERVED',$3) ON CONFLICT DO NOTHING`, r["currentSessionId"], trace, uttID)
		if e != nil {
			return nil, e
		}
		if tag.RowsAffected() != 1 {
			return nil, fault("COMMAND_CONFLICT")
		}
	}
	a := Object{"tenantId": p.TenantID, "ownerId": p.OwnerID, "runId": r["runId"], "attemptId": attemptID, "turnId": t["turnId"], "segmentId": t["sourceSegmentId"], "sessionId": r["currentSessionId"], "utteranceId": uttID, "commandId": commandID, "runEpoch": r["runEpoch"], "attemptNumber": int64(1), "executorIncarnation": nil, "lastCheckpoint": "PLANNED", "answerTextHash": nil, "requiredSinks": payload["requiredSinks"], "createdAt": stamp(now), "updatedAt": stamp(now)}
	_, e = tx.Exec(ctx, `INSERT INTO dl05_attempts(tenant_id,owner_id,run_id,attempt_id,turn_id,segment_id,session_id,run_epoch,utterance_id,command_id,attempt_number,last_checkpoint,required_sinks,document) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,1,'PLANNED',$11,$12)`, p.TenantID, p.OwnerID, r["runId"], attemptID, t["turnId"], t["sourceSegmentId"], r["currentSessionId"], num(r, "runEpoch"), uttID, commandID, payload["requiredSinks"], a)
	if e != nil {
		return nil, e
	}
	if e = insertIntent(ctx, tx, p, r, cmd); e != nil {
		return nil, e
	}
	_, e = tx.Exec(ctx, `UPDATE dl05_turns SET state='DISPATCHING',revision=revision+1 WHERE turn_id=$1`, t["turnId"])
	if e != nil {
		return nil, e
	}
	_, e = tx.Exec(ctx, `UPDATE dl05_run_slots SET active_attempt_id=$2,boundary_checkpoint_id=NULL,slot_version=slot_version+1 WHERE run_id=$1`, r["runId"], attemptID)
	if e != nil {
		return nil, e
	}
	if t["sourceSegmentId"] != nil {
		_, e = tx.Exec(ctx, `UPDATE dl05_segments SET state='ACTIVE',utterance_id=$2,updated_at=clock_timestamp() WHERE segment_id=$1`, t["sourceSegmentId"], uttID)
		if e != nil {
			return nil, e
		}
	}
	cp := systemCheckpoint(a, "PLANNED", "PLAN_COMMIT", "backend-planner", "intent:"+intentID)
	if e = insertCheckpoint(ctx, tx, cp, "APPLIED"); e != nil {
		return nil, e
	}
	if e = bump(ctx, tx, str(r, "runId")); e != nil {
		return nil, e
	}
	t, e = loadTurn(ctx, tx, str(t, "turnId"))
	if e != nil {
		return nil, e
	}
	intent, e := loadIntent(ctx, tx, intentID)
	if e != nil {
		return nil, e
	}
	slot, e = loadSlot(ctx, tx, str(r, "runId"))
	return Object{"requestId": q["requestId"], "runRevision": num(r, "revision") + 1, "turn": t, "attempt": a, "intent": intent, "slot": slot}, e
}
func insertIntent(ctx context.Context, tx pgx.Tx, p Principal, r, cmd Object) error {
	_, e := tx.Exec(ctx, `INSERT INTO dl05_outbox(tenant_id,owner_id,run_id,intent_id,session_id,utterance_id,command_id,attempt_id,turn_id,idempotency_key,run_epoch,operation,request_hash,envelope,status) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,'PENDING')`, p.TenantID, p.OwnerID, r["runId"], cmd["intentId"], cmd["sessionId"], cmd["utteranceId"], cmd["commandId"], cmd["attemptId"], cmd["turnId"], cmd["idempotencyKey"], num(cmd, "runEpoch"), cmd["operation"], cmd["requestHash"], cmd)
	return e
}
func (s *Store) validatePayload(ctx context.Context, tx pgx.Tx, p Principal, r, payload Object, requireFactProof bool) error {
	var now time.Time
	e := tx.QueryRow(ctx, `SELECT clock_timestamp()`).Scan(&now)
	if e != nil {
		return e
	}
	if !instant(payload["expiresAt"]).After(now) || textHash(str(payload, "text")) != str(payload, "textHash") {
		return fault("INVALID_ARGUMENT")
	}
	if payload["productId"] != nil {
		if e = owner(ctx, tx, p, "product", str(payload, "productId")); e != nil {
			return e
		}
		var active string
		e = tx.QueryRow(ctx, `SELECT COALESCE(active_product_id,'') FROM live_rooms WHERE id=$1`, r["roomId"]).Scan(&active)
		if e != nil {
			return e
		}
		if active != str(payload, "productId") || payload["planId"] != r["currentPlanId"] {
			return fault("PLAN_CHANGED")
		}
		if s.Facts != nil && str(payload, "mode") == "SCRIPT_TEXT" {
			// Recheck authoritative SQL inside the short transaction too. A
			// product update between external preflight and CAS cannot reuse a
			// same-product stale plan (including static description/size facts).
			current, err := productView(ctx, tx, p, r)
			if err != nil {
				return err
			}
			var version string
			if err = tx.QueryRow(ctx, `SELECT product_snapshot_version FROM dl05_plans WHERE plan_id=$1 AND run_id=$2`, payload["planId"], r["runId"]).Scan(&version); err != nil {
				return err
			}
			if current.SnapshotVersion != version {
				return fault("PLAN_CHANGED")
			}
		}
	}
	// Dynamic facts need a trusted authoritative revalidation hook. Without one,
	// their presence closes admission instead of inventing source/hash semantics.
	for _, v := range arr(payload, "factDependencies") {
		f := v.(map[string]any)
		approval, ok := ctx.Value(factApprovalKey{}).(factApproval)
		freshProof := ok && time.Since(approval.at) < 2*time.Second && approval.hash == hash(arr(payload, "factDependencies"))
		if f["productId"] != payload["productId"] || (!freshProof && (!instant(f["expiresAt"]).After(now) || instant(f["validatedAt"]).After(now) || now.Sub(instant(f["validatedAt"])) > 2*time.Second)) {
			return fault("PLAN_CHANGED")
		}
		if requireFactProof && !freshProof {
			return fault("DEPENDENCY_UNAVAILABLE")
		}
	}
	return nil
}
func (s *Store) dispatchTurn(ctx context.Context, tx pgx.Tx, p Principal, r, q Object) (Object, error) {
	if e := notStopped(r); e != nil {
		return nil, e
	}
	if e := checkEpoch(r, q); e != nil {
		return nil, e
	}
	if e := revision(r, q); e != nil {
		return nil, e
	}
	in, e := loadIntent(ctx, tx, str(q, "intentId"))
	if e != nil {
		return nil, e
	}
	if !scopeMatches(r, in) || in["commandId"] != q["commandId"] || in["runEpoch"] != r["runEpoch"] {
		return nil, fault("COMMAND_CONFLICT")
	}
	return Object{"requestId": q["requestId"], "intent": in}, nil
}
