package durablelive

import (
	"context"
	"errors"
	"github.com/jackc/pgx/v5"
	"time"
)

// Coordinator is independent of ingress, Redis and the comment Scheduler. It
// starts with a scan and then polls SQL; Redis availability never grants replay.
type Coordinator struct {
	Store     *Store
	Principal Principal
	Batch     int
}

func (c *Coordinator) Run(ctx context.Context, interval time.Duration) error {
	if interval < 100*time.Millisecond {
		return fault("INVALID_ARGUMENT")
	}
	return runLoop(ctx, interval, c.Tick)
}

func (c *Coordinator) Tick(ctx context.Context) error {
	if c.Principal.Role != "CONTROL" {
		return fault("FORBIDDEN")
	}
	n := c.Batch
	if n == 0 {
		n = 32
	}
	if n < 1 || n > 64 {
		return fault("INVALID_ARGUMENT")
	}
	rows, e := c.Store.DB.Query(ctx, `SELECT run_id FROM dl05_runs WHERE tenant_id=$1 AND owner_id=$2 AND (status NOT IN ('STOPPED','FAILED') OR EXISTS(SELECT 1 FROM dl05_outbox o WHERE o.run_id=dl05_runs.run_id AND o.operation='STOP_RUN' AND o.status NOT IN ('COMPLETED','FAILED'))) ORDER BY updated_at,run_id LIMIT $3`, c.Principal.TenantID, c.Principal.OwnerID, n)
	if e != nil {
		return e
	}
	runs := []string{}
	for rows.Next() {
		var id string
		if e = rows.Scan(&id); e != nil {
			rows.Close()
			return e
		}
		runs = append(runs, id)
	}
	e = rows.Err()
	rows.Close()
	if e != nil {
		return e
	}
	for _, id := range runs {
		if e = c.Store.recoverRun(ctx, c.Principal, id); e != nil {
			return e
		}
	}
	return nil
}
func audit(ctx context.Context, tx pgx.Tx, r, a Object, reason, ref string) error {
	_, e := tx.Exec(ctx, `INSERT INTO dl05_recovery_audit(run_id,session_id,utterance_id,reason_code,evidence_ref) VALUES($1,$2,$3,$4,$5) ON CONFLICT DO NOTHING`, r["runId"], a["sessionId"], a["utteranceId"], reason, ref)
	return e
}
func (s *Store) recoverRun(ctx context.Context, p Principal, id string) error {
	tx, e := s.begin(ctx)
	if e != nil {
		return e
	}
	defer tx.Rollback(context.Background())
	r, e := jsonRow(tx.QueryRow(ctx, "SELECT "+runJSON+" FROM dl05_runs WHERE run_id=$1 FOR UPDATE SKIP LOCKED", id))
	if errors.Is(e, pgx.ErrNoRows) {
		return nil
	}
	if e != nil {
		return e
	}
	if e = authorize(p, r); e != nil {
		return e
	}
	var expired bool
	e = tx.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM dl05_run_leases WHERE run_id=$1 AND lease_expires_at<=clock_timestamp())`, id).Scan(&expired)
	if e != nil {
		return e
	}
	if expired {
		_, e = tx.Exec(ctx, `UPDATE dl05_run_leases SET phase='SEALED' WHERE run_id=$1 AND phase<>'SEALED'`, id)
		if e != nil {
			return e
		}
		_, e = tx.Exec(ctx, `UPDATE dl05_runs SET status='RECOVERING',state_revision=state_revision+1,updated_at=clock_timestamp() WHERE run_id=$1 AND status IN ('LIVE','PREPARING') AND stop_revision=0`, id)
		if e != nil {
			return e
		}
		_, e = tx.Exec(ctx, `UPDATE dl05_output_permits SET revoked_at=COALESCE(revoked_at,clock_timestamp()) WHERE run_id=$1`, id)
		if e != nil {
			return e
		}
	}
	_, e = tx.Exec(ctx, `UPDATE dl05_turns SET state='INTERRUPTED',finished_at=clock_timestamp(),revision=revision+1 WHERE run_id=$1 AND state IN ('READY','WAITING') AND (expires_at<=clock_timestamp() OR $2::bigint>0)`, id, num(r, "stopRevision"))
	if e != nil {
		return e
	}
	_, e = tx.Exec(ctx, `UPDATE dl05_outbox SET status='RECONCILING',last_error_code='LEASE_LOST',updated_at=clock_timestamp() WHERE run_id=$1 AND status='CLAIMED' AND lease_expires_at<=clock_timestamp()`, id)
	if e != nil {
		return e
	}
	rows, e := tx.Query(ctx, `SELECT intent_id FROM dl05_outbox WHERE run_id=$1 AND status IN ('PENDING','RECONCILING','ACCEPTED','FAILED','UNKNOWN') ORDER BY next_attempt_at,intent_id LIMIT 64`, id)
	if e != nil {
		return e
	}
	intents := []string{}
	for rows.Next() {
		var x string
		if e = rows.Scan(&x); e != nil {
			rows.Close()
			return e
		}
		intents = append(intents, x)
	}
	e = rows.Err()
	rows.Close()
	if e != nil {
		return e
	}
	for _, intentID := range intents {
		in, e := loadIntent(ctx, tx, intentID)
		if e != nil {
			return e
		}
		op := str(in, "operation")
		if op != "EXECUTE_TURN" {
			if e = s.recoverControl(ctx, tx, p, r, in); e != nil {
				return e
			}
			continue
		}
		a, e := loadAttempt(ctx, tx, str(in, "attemptId"))
		if e != nil {
			return e
		}
		if str(a, "lastCheckpoint") == "COMPLETED" || str(a, "lastCheckpoint") == "INTERRUPTED" {
			continue
		}
		cmd, e := commandFor(ctx, tx, r, str(in, "commandId"))
		if e != nil {
			return e
		}
		invalid := expired || num(in, "runEpoch") != num(r, "runEpoch") || num(r, "stopRevision") > 0
		if !invalid {
			if e = s.validateSession(ctx, tx, p, r); e != nil {
				invalid = true
			}
			var started bool
			if e = tx.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM dl05_runtime_inbox WHERE command_id=$1 AND started_at IS NOT NULL)`, cmd["commandId"]).Scan(&started); e != nil {
				return e
			}
			if !started {
				if e = s.validatePayload(ctx, tx, p, r, obj(cmd, "payload"), false); e != nil {
					invalid = true
				}
			}
		}
		if str(in, "status") == "PENDING" && !invalid {
			continue
		}
		if in["sendStartedAt"] == nil && (str(in, "status") == "PENDING" || str(in, "status") == "FAILED") {
			if e = s.finishUnsent(ctx, tx, r, a, in); e != nil {
				return e
			}
			continue
		}
		var inboxState string
		e = tx.QueryRow(ctx, `SELECT status FROM dl05_runtime_inbox WHERE command_id=$1`, in["commandId"]).Scan(&inboxState)
		if e != nil && !errors.Is(e, pgx.ErrNoRows) {
			return e
		}
		if !invalid && (inboxState == "ACCEPTED" || inboxState == "STARTED") {
			// Existing Runtime may still hold the queue/task. No network resend, even
			// when the 202 was lost. Start ACK ambiguity is never replayed here.
			var livePermit bool
			e = tx.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM dl05_output_permits WHERE run_id=$1 AND producer_incarnation=$2 AND revoked_at IS NULL AND expires_at>clock_timestamp())`, id, a["executorIncarnation"]).Scan(&livePermit)
			if e != nil {
				return e
			}
			if livePermit || inboxState == "ACCEPTED" {
				_, e = tx.Exec(ctx, `UPDATE dl05_outbox SET status='ACCEPTED',updated_at=clock_timestamp() WHERE intent_id=$1 AND status='RECONCILING'`, intentID)
				if e != nil {
					return e
				}
				continue
			}
		}
		if inboxState == "TERMINAL" {
			if e = s.projectPending(ctx, tx, p, r, a); e != nil {
				return e
			}
			continue
		}
		if str(a, "lastCheckpoint") == "UNKNOWN" {
			continue
		}
		// Missing journal or an executor with no valid permit is knowledge loss,
		// not a no-effect receipt. Preserve the slot until a guardian barrier.
		cp := systemCheckpoint(a, "UNKNOWN", "KNOWLEDGE_GAP", "backend-recovery", "reconcile:"+str(in, "commandId"))
		cp["lastKnownState"] = a["lastCheckpoint"]
		cp["reasonCode"] = "RECOVERY_UNKNOWN"
		if e = setSystemSequence(ctx, tx, cp); e != nil {
			return e
		}
		if e = insertCheckpoint(ctx, tx, cp, "APPLIED"); e != nil {
			return e
		}
		if e = projectCheckpoint(ctx, tx, r, a, cp); e != nil {
			return e
		}
		if e = audit(ctx, tx, r, a, "RECOVERY_UNKNOWN", str(obj(cp, "evidence"), "evidenceRef")); e != nil {
			return e
		}
	}
	// Drain gaps may have been filled since an earlier Redis/HTTP retry.
	rows, e = tx.Query(ctx, `SELECT DISTINCT attempt_id FROM dl05_checkpoints WHERE run_id=$1 AND projection_status='PENDING' AND run_epoch=$2 LIMIT 32`, id, num(r, "runEpoch"))
	if e != nil {
		return e
	}
	attempts := []string{}
	for rows.Next() {
		var a string
		if e = rows.Scan(&a); e != nil {
			rows.Close()
			return e
		}
		attempts = append(attempts, a)
	}
	e = rows.Err()
	rows.Close()
	if e != nil {
		return e
	}
	if num(r, "stopRevision") == 0 {
		for _, id := range attempts {
			a, e := loadAttempt(ctx, tx, id)
			if e != nil {
				return e
			}
			if e = s.projectPending(ctx, tx, p, r, a); e != nil {
				return e
			}
		}
	}
	if e = s.finishStop(ctx, tx, r); e != nil {
		return e
	}
	return tx.Commit(ctx)
}
func (s *Store) finishUnsent(ctx context.Context, tx pgx.Tx, r, a, in Object) error {
	// Since no sender ever committed SEND_STARTED, no compliant sender could
	// invoke Runtime. PENDING never had a claim; FAILED here is Stop-before-send.
	_, e := tx.Exec(ctx, `UPDATE dl05_outbox SET status='FAILED',last_error_code='NOT_EXECUTED',claim_version=claim_version+1 WHERE intent_id=$1 AND send_started_at IS NULL AND status IN ('PENDING','FAILED')`, in["intentId"])
	if e != nil {
		return e
	}
	cp := systemCheckpoint(a, "INTERRUPTED", "FENCE_BARRIER", "backend-recovery", "unsent:"+str(in, "commandId"))
	cp["reasonCode"] = "NOT_EXECUTED"
	if e = setSystemSequence(ctx, tx, cp); e != nil {
		return e
	}
	if e = insertCheckpoint(ctx, tx, cp, "APPLIED"); e != nil {
		return e
	}
	if e = projectCheckpoint(ctx, tx, r, a, cp); e != nil {
		return e
	}
	return audit(ctx, tx, r, a, "NOT_EXECUTED", str(obj(cp, "evidence"), "evidenceRef"))
}
func (s *Store) recoverControl(ctx context.Context, tx pgx.Tx, p Principal, r, in Object) error {
	if str(in, "operation") == "STOP_RUN" {
		var cleaned bool
		e := tx.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM dl05_run_sessions rs JOIN live_sessions se ON se.id=rs.session_id JOIN session_provider_bindings b ON b.session_id=se.id WHERE rs.run_id=$1 AND rs.session_id=$2 AND rs.output_fenced_at IS NOT NULL AND se.status IN ('ENDED','FAILED') AND b.released_at IS NOT NULL)`, r["runId"], in["sessionId"]).Scan(&cleaned)
		if e != nil {
			return e
		}
		if cleaned {
			if str(in, "status") == "UNKNOWN" {
				if _, e = tx.Exec(ctx, `UPDATE dl05_outbox SET status='RECONCILING' WHERE intent_id=$1 AND status='UNKNOWN'`, in["intentId"]); e != nil {
					return e
				}
			}
			_, e = tx.Exec(ctx, `UPDATE dl05_outbox SET status='COMPLETED' WHERE intent_id=$1 AND status IN ('ACCEPTED','RECONCILING')`, in["intentId"])
			return e
		}
	}
	if str(in, "operation") == "INSTALL_FENCE" {
		var active bool
		e := tx.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM dl05_run_terms WHERE run_id=$1 AND run_epoch=$2 AND phase='ACTIVE' AND output_fence_proof IS NOT NULL)`, r["runId"], num(in, "runEpoch")).Scan(&active)
		if e != nil {
			return e
		}
		if active {
			if str(in, "status") == "UNKNOWN" {
				if _, e = tx.Exec(ctx, `UPDATE dl05_outbox SET status='RECONCILING' WHERE intent_id=$1 AND status='UNKNOWN'`, in["intentId"]); e != nil {
					return e
				}
			}
			_, e = tx.Exec(ctx, `UPDATE dl05_outbox SET status='COMPLETED' WHERE intent_id=$1 AND status IN ('ACCEPTED','RECONCILING')`, in["intentId"])
			return e
		}
	}
	if str(in, "status") == "RECONCILING" {
		// Controls cannot speak. Bounded exponential retries preserve the envelope.
		_, e := tx.Exec(ctx, `UPDATE dl05_outbox SET status=CASE WHEN attempt_count>=5 THEN 'UNKNOWN' ELSE 'PENDING' END,next_attempt_at=clock_timestamp()+make_interval(secs=>LEAST(30, power(2,attempt_count)::int)),send_started_at=NULL,claim_version=claim_version+1 WHERE intent_id=$1`, in["intentId"])
		return e
	}
	return nil
}
func (s *Store) finishStop(ctx context.Context, tx pgx.Tx, r Object) error {
	if num(r, "stopRevision") == 0 {
		return nil
	}
	var done bool
	e := tx.QueryRow(ctx, `SELECT NOT EXISTS(SELECT 1 FROM dl05_run_sessions rs JOIN live_sessions se ON se.id=rs.session_id JOIN session_provider_bindings b ON b.session_id=se.id WHERE rs.run_id=$1 AND (rs.output_fenced_at IS NULL OR se.status NOT IN ('ENDED','FAILED') OR b.released_at IS NULL)) AND NOT EXISTS(SELECT 1 FROM dl05_outbox WHERE run_id=$1 AND status NOT IN ('COMPLETED','FAILED') AND operation='STOP_RUN')`, r["runId"]).Scan(&done)
	if e != nil {
		return e
	}
	if done {
		_, e = tx.Exec(ctx, `UPDATE dl05_runs SET status='STOPPED',ended_at=clock_timestamp(),state_revision=state_revision+1,updated_at=clock_timestamp() WHERE run_id=$1 AND status='STOPPING'`, r["runId"])
	}
	return e
}

// InspectLegacyOrphans records legacy ambiguity without migrating or replaying
// existing RESERVED/QUEUED rows. Caller must stop/isolate the legacy Session.
func (s *Store) InspectLegacyOrphans(ctx context.Context, p Principal, sessionID string) error {
	if p.Role != "CONTROL" {
		return fault("FORBIDDEN")
	}
	tx, e := s.begin(ctx)
	if e != nil {
		return e
	}
	defer tx.Rollback(context.Background())
	if e = owner(ctx, tx, p, "session", sessionID); e != nil {
		return e
	}
	_, e = tx.Exec(ctx, `INSERT INTO dl05_recovery_audit(session_id,utterance_id,reason_code,evidence_ref) SELECT session_id,id,'LEGACY_UNKNOWN','legacy:'||id FROM utterances u WHERE session_id=$1 AND status='QUEUED' AND NOT EXISTS(SELECT 1 FROM dl05_attempts WHERE utterance_id=u.id) ON CONFLICT DO NOTHING`, sessionID)
	if e != nil {
		return e
	}
	_, e = tx.Exec(ctx, `INSERT INTO dl05_recovery_audit(session_id,utterance_id,reason_code,evidence_ref) SELECT session_id,utterance_id,'LEGACY_UNKNOWN','receipt:'||trace_id FROM interaction_receipts WHERE session_id=$1 AND status='RESERVED' ON CONFLICT DO NOTHING`, sessionID)
	if e != nil {
		return e
	}
	return tx.Commit(ctx)
}

// DeliverNotifications is at-least-once. SQL commit precedes SSE; a crash after
// publish but before mark can duplicate a notification. Consumers dedup checkpointId.
func (s *Store) DeliverNotifications(ctx context.Context, p Principal, limit int, publish func(context.Context, string, PlaybackCheckpoint) error) error {
	if p.Role != "CONTROL" || limit < 1 || limit > 64 {
		return fault("INVALID_ARGUMENT")
	}
	rows, e := s.DB.Query(ctx, `SELECT n.notification_id,c.envelope FROM dl05_notifications n JOIN dl05_checkpoints c USING(checkpoint_id) WHERE n.published_at IS NULL AND c.tenant_id=$1 AND c.owner_id=$2 ORDER BY n.notification_id LIMIT $3`, p.TenantID, p.OwnerID, limit)
	if e != nil {
		return e
	}
	type item struct {
		id int64
		cp PlaybackCheckpoint
	}
	items := []item{}
	for rows.Next() {
		var i item
		var b []byte
		if e = rows.Scan(&i.id, &b); e != nil {
			rows.Close()
			return e
		}
		if e = decodeInto(b, &i.cp); e != nil {
			rows.Close()
			return e
		}
		items = append(items, i)
	}
	e = rows.Err()
	rows.Close()
	if e != nil {
		return e
	}
	for _, i := range items {
		if e = publish(ctx, i.cp.RunId, i.cp); e != nil {
			return e
		}
		if _, e = s.DB.Exec(ctx, `UPDATE dl05_notifications SET published_at=clock_timestamp() WHERE notification_id=$1 AND published_at IS NULL`, i.id); e != nil {
			return e
		}
	}
	return nil
}

// ResolveUnknown is the operator integration seam using the frozen Decision
// object. It records explicit gaps separately; it never manufactures completion.
func (s *Store) ResolveUnknown(ctx context.Context, p Principal, runID string, expectedRevision int64, d Decision) error {
	if p.Role != "CONTROL" || d.OperatorId != p.InstanceID {
		return fault("FORBIDDEN")
	}
	q := wire(d)
	if e := validate("Decision", q); e != nil {
		return e
	}
	tx, e := s.begin(ctx)
	if e != nil {
		return e
	}
	defer tx.Rollback(context.Background())
	r, e := loadRun(ctx, tx, runID, true)
	if e != nil {
		return e
	}
	if e = authorize(p, r); e != nil {
		return e
	}
	if e = owner(ctx, tx, p, "room", str(r, "roomId")); e != nil {
		return e
	}
	var previous []byte
	e = tx.QueryRow(ctx, `SELECT document FROM dl05_decisions WHERE run_id=$1 AND decision_id=$2`, runID, d.DecisionId).Scan(&previous)
	if e == nil {
		old, e := Decode(previous)
		if e != nil {
			return e
		}
		if hash(old) != hash(q) {
			return fault("COMMAND_CONFLICT")
		}
		return tx.Commit(ctx)
	}
	if !errors.Is(e, pgx.ErrNoRows) {
		return e
	}
	if num(r, "revision") != expectedRevision {
		return fault("STATE_CONFLICT")
	}
	if e = notStopped(r); e != nil {
		return e
	}
	a, e := loadAttempt(ctx, tx, d.AttemptId)
	if e != nil {
		return e
	}
	if !scopeMatches(r, a) || str(a, "lastCheckpoint") != "UNKNOWN" {
		return fault("STATE_CONFLICT")
	}
	if d.Action != "WAIT_FOR_EVIDENCE" {
		var proof string
		e = tx.QueryRow(ctx, `SELECT COALESCE(output_fence_proof,'') FROM dl05_run_terms WHERE run_id=$1 AND run_epoch=$2`, runID, num(r, "runEpoch")).Scan(&proof)
		if e != nil {
			return e
		}
		var fenced bool
		e = tx.QueryRow(ctx, `SELECT output_fenced_at IS NOT NULL FROM dl05_run_sessions WHERE run_id=$1 AND session_id=$2`, runID, a["sessionId"]).Scan(&fenced)
		if e != nil {
			return e
		}
		if proof == "" || !fenced {
			return fault("OUTPUT_FENCE_UNPROVEN")
		}
		cp := systemCheckpoint(a, "INTERRUPTED", "FENCE_BARRIER", "backend-operator", proof)
		cp["reasonCode"] = d.Action
		if e = setSystemSequence(ctx, tx, cp); e != nil {
			return e
		}
		if e = insertCheckpoint(ctx, tx, cp, "HISTORICAL"); e != nil {
			return e
		}
		// Do not cross an epoch to release a different active attempt.
		if e = projectCheckpoint(ctx, tx, r, a, cp); e != nil {
			return e
		}
		if d.Action == "SKIP_WITH_GAP" && a["segmentId"] != nil {
			_, e = tx.Exec(ctx, `UPDATE dl05_plan_progress pp SET resume_sequence=s.sequence+1,revision=pp.revision+1 FROM dl05_segments s WHERE s.segment_id=$1 AND pp.plan_id=s.plan_id AND pp.resume_sequence=s.sequence`, a["segmentId"])
			if e != nil {
				return e
			}
		}
	}
	_, e = tx.Exec(ctx, `INSERT INTO dl05_decisions(tenant_id,owner_id,run_id,decision_id,plan_id,attempt_id,operator_id,action,reason,expected_revision,document) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)`, p.TenantID, p.OwnerID, runID, d.DecisionId, r["currentPlanId"], d.AttemptId, p.InstanceID, d.Action, d.Reason, expectedRevision, q)
	if e != nil {
		return e
	}
	if e = bump(ctx, tx, runID); e != nil {
		return e
	}
	return tx.Commit(ctx)
}

// SealNotExecuted records a real no-effect result only after the guardian has
// fenced this Session and START has never committed. Its old executor is sealed
// atomically with the Inbox update, so an in-flight old START is rejected.
func (s *Store) SealNotExecuted(ctx context.Context, p Principal, runID, commandID, proof string) error {
	if p.Role != "CONTROL" {
		return fault("FORBIDDEN")
	}
	tx, e := s.begin(ctx)
	if e != nil {
		return e
	}
	defer tx.Rollback(context.Background())
	r, e := loadRun(ctx, tx, runID, true)
	if e != nil {
		return e
	}
	if e = authorize(p, r); e != nil {
		return e
	}
	if e = owner(ctx, tx, p, "room", str(r, "roomId")); e != nil {
		return e
	}
	cmd, e := commandFor(ctx, tx, r, commandID)
	if e != nil {
		return e
	}
	a, e := loadAttempt(ctx, tx, str(cmd, "attemptId"))
	if e != nil {
		return e
	}
	var fenced bool
	e = tx.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM dl05_run_terms t JOIN dl05_run_sessions rs ON rs.run_id=t.run_id WHERE t.run_id=$1 AND t.output_fence_proof=$2 AND rs.session_id=$3 AND rs.output_fenced_at IS NOT NULL)`, runID, proof, a["sessionId"]).Scan(&fenced)
	if e != nil {
		return e
	}
	if !fenced {
		return fault("OUTPUT_FENCE_UNPROVEN")
	}
	tag, e := tx.Exec(ctx, `UPDATE dl05_runtime_inbox SET status='NOT_EXECUTED',executor_sealed_at=clock_timestamp(),no_effect_proof=$2,terminal_at=clock_timestamp(),revision=revision+1 WHERE command_id=$1 AND started_at IS NULL AND status IN ('ACCEPTED','UNKNOWN')`, commandID, proof)
	if e != nil {
		return e
	}
	if tag.RowsAffected() != 1 {
		return fault("RECOVERY_UNKNOWN")
	}
	cp := systemCheckpoint(a, "INTERRUPTED", "FENCE_BARRIER", "backend-recovery", proof)
	cp["reasonCode"] = "NOT_EXECUTED"
	if e = setSystemSequence(ctx, tx, cp); e != nil {
		return e
	}
	if e = insertCheckpoint(ctx, tx, cp, "APPLIED"); e != nil {
		return e
	}
	if e = projectCheckpoint(ctx, tx, r, a, cp); e != nil {
		return e
	}
	// projectCheckpoint's general terminal path uses TERMINAL; retain the stronger
	// sealed no-effect assertion after it has updated the remaining projections.
	_, e = tx.Exec(ctx, `UPDATE dl05_runtime_inbox SET status='NOT_EXECUTED' WHERE command_id=$1`, commandID)
	if e != nil {
		return e
	}
	if e = audit(ctx, tx, r, a, "NOT_EXECUTED", proof); e != nil {
		return e
	}
	return tx.Commit(ctx)
}

// RecordAnswerText is an in-process journal seam for a trusted adapter. The
// frozen wire has no answer-prepared operation: Agent 4 must resolve that wiring
// with Agent 1 before enabling COMMENT_QUESTION across separate processes.
func (s *Store) RecordAnswerText(ctx context.Context, p Principal, runID, commandID, text string) error {
	if p.Role != "RUNTIME_JOURNAL" || text == "" || len([]rune(text)) > 2000 {
		return fault("FORBIDDEN")
	}
	tx, e := s.begin(ctx)
	if e != nil {
		return e
	}
	defer tx.Rollback(context.Background())
	r, e := loadRun(ctx, tx, runID, true)
	if e != nil {
		return e
	}
	if e = authorize(p, r); e != nil {
		return e
	}
	if e = boundProducer(ctx, tx, p, r); e != nil {
		return e
	}
	if _, e = s.validLease(ctx, tx, p, r, "ACTIVE", false); e != nil {
		return e
	}
	cmd, e := commandFor(ctx, tx, r, commandID)
	if e != nil {
		return e
	}
	if str(obj(cmd, "payload"), "mode") != "COMMENT_QUESTION" {
		return fault("COMMAND_CONFLICT")
	}
	var state, producer string
	e = tx.QueryRow(ctx, `SELECT status,producer_incarnation FROM dl05_runtime_inbox WHERE command_id=$1`, commandID).Scan(&state, &producer)
	if e != nil {
		return e
	}
	if producer != p.InstanceID || state != "ACCEPTED" {
		return fault("STATE_CONFLICT")
	}
	var old *string
	e = tx.QueryRow(ctx, `SELECT answer_text_hash FROM dl05_attempts WHERE command_id=$1`, commandID).Scan(&old)
	if e != nil {
		return e
	}
	h := textHash(text)
	if old != nil && *old != h {
		return fault("COMMAND_CONFLICT")
	}
	_, e = tx.Exec(ctx, `UPDATE dl05_attempts SET answer_text_hash=$2,updated_at=clock_timestamp() WHERE command_id=$1`, commandID, h)
	if e != nil {
		return e
	}
	// Store the exact answer as a bounded journal artifact; never in logs or audit.
	_, e = tx.Exec(ctx, `INSERT INTO dl05_answer_artifacts(command_id,answer_text,text_hash) VALUES($1,$2,$3) ON CONFLICT DO NOTHING`, commandID, text, h)
	if e != nil {
		return e
	}
	return tx.Commit(ctx)
}
