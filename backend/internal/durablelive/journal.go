package durablelive

import (
	"context"
	"encoding/json"
	"errors"
	"github.com/jackc/pgx/v5"
)

func decodeInto(b []byte, v any) error { return json.Unmarshal(b, v) }
func decodeArray(b []byte) ([]any, error) {
	m, e := Decode(append(append([]byte(`{"v":`), b...), '}'))
	if e != nil {
		return nil, e
	}
	return arr(m, "v"), nil
}
func commandFor(ctx context.Context, tx pgx.Tx, r Object, id string) (Object, error) {
	return jsonRow(tx.QueryRow(ctx, `SELECT envelope FROM dl05_outbox WHERE run_id=$1 AND command_id=$2`, r["runId"], id))
}
func boundProducer(ctx context.Context, tx pgx.Tx, p Principal, r Object) error {
	var producer string
	e := tx.QueryRow(ctx, `SELECT COALESCE(producer_incarnation,'') FROM dl05_run_terms WHERE run_id=$1 AND run_epoch=$2`, r["runId"], num(r, "runEpoch")).Scan(&producer)
	if e != nil {
		return e
	}
	if producer != p.InstanceID {
		return fault("FORBIDDEN")
	}
	return nil
}
func (s *Store) accept(ctx context.Context, tx pgx.Tx, p Principal, r, q Object) (Object, error) {
	cmd := obj(q, "command")
	if !scopeMatches(r, cmd) || commandHash(cmd) != str(cmd, "requestHash") {
		return nil, fault("COMMAND_CONFLICT")
	}
	stored, e := commandFor(ctx, tx, r, str(cmd, "commandId"))
	if e != nil {
		return nil, normErr(e)
	}
	if hash(stored) != hash(cmd) {
		return nil, fault("COMMAND_CONFLICT")
	}
	if e = checkEpoch(r, cmd); e != nil {
		return nil, e
	}
	if e = boundProducer(ctx, tx, p, r); e != nil {
		return nil, e
	}
	var receipt, state, producer string
	var rev int64
	e = tx.QueryRow(ctx, `SELECT receipt_id,status,producer_incarnation,revision FROM dl05_runtime_inbox WHERE command_id=$1`, cmd["commandId"]).Scan(&receipt, &state, &producer, &rev)
	if e == nil {
		if producer != p.InstanceID {
			return nil, fault("RECOVERY_UNKNOWN")
		}
		return Object{"accepted": true, "commandId": cmd["commandId"], "receiptId": receipt, "requestHash": cmd["requestHash"], "revision": rev, "state": state}, nil
	}
	if !errors.Is(e, pgx.ErrNoRows) {
		return nil, e
	}
	if _, e = s.validLease(ctx, tx, p, r, "ACTIVE", false); e != nil {
		return nil, e
	}
	if e = s.validateSession(ctx, tx, p, r); e != nil {
		return nil, e
	}
	if e = s.validatePayload(ctx, tx, p, r, obj(cmd, "payload"), true); e != nil {
		return nil, e
	}
	var sent bool
	e = tx.QueryRow(ctx, `SELECT send_started_at IS NOT NULL AND status IN ('CLAIMED','RECONCILING','ACCEPTED') FROM dl05_outbox WHERE command_id=$1`, cmd["commandId"]).Scan(&sent)
	if e != nil {
		return nil, e
	}
	if !sent {
		return nil, fault("STATE_CONFLICT")
	}
	receipt = freshID("receipt")
	_, e = tx.Exec(ctx, `INSERT INTO dl05_runtime_inbox(tenant_id,owner_id,run_id,attempt_id,run_epoch,command_id,request_hash,status,receipt_id,producer_incarnation) VALUES($1,$2,$3,$4,$5,$6,$7,'ACCEPTED',$8,$9)`, p.TenantID, p.OwnerID, r["runId"], cmd["attemptId"], num(cmd, "runEpoch"), cmd["commandId"], cmd["requestHash"], receipt, p.InstanceID)
	if e != nil {
		return nil, e
	}
	_, e = tx.Exec(ctx, `UPDATE dl05_attempts SET executor_incarnation=$2,last_checkpoint='RUNTIME_ACCEPTED',updated_at=clock_timestamp() WHERE attempt_id=$1 AND last_checkpoint='DISPATCHED'`, cmd["attemptId"], p.InstanceID)
	if e != nil {
		return nil, e
	}
	_, e = tx.Exec(ctx, `UPDATE dl05_outbox SET status='ACCEPTED',updated_at=clock_timestamp() WHERE command_id=$1 AND status IN ('CLAIMED','RECONCILING')`, cmd["commandId"])
	if e != nil {
		return nil, e
	}
	_, e = tx.Exec(ctx, `UPDATE interaction_receipts SET status='ACCEPTED' WHERE session_id=$1 AND utterance_id=$2 AND status='RESERVED'`, cmd["sessionId"], cmd["utteranceId"])
	if e != nil {
		return nil, e
	}
	a, e := loadAttempt(ctx, tx, str(cmd, "attemptId"))
	if e != nil {
		return nil, e
	}
	cp := systemCheckpoint(a, "RUNTIME_ACCEPTED", "INBOX_COMMIT", "backend-journal", receipt)
	if e = setSystemSequence(ctx, tx, cp); e != nil {
		return nil, e
	}
	if e = insertCheckpoint(ctx, tx, cp, "APPLIED"); e != nil {
		return nil, e
	}
	return Object{"accepted": true, "commandId": cmd["commandId"], "receiptId": receipt, "requestHash": cmd["requestHash"], "revision": int64(1), "state": "ACCEPTED"}, nil
}
func (s *Store) start(ctx context.Context, tx pgx.Tx, p Principal, r, q Object) (Object, error) {
	cmd, e := commandFor(ctx, tx, r, str(q, "commandId"))
	if e != nil {
		return nil, normErr(e)
	}
	if cmd["attemptId"] != q["attemptId"] || cmd["requestHash"] != q["requestHash"] || num(cmd, "runEpoch") != num(q, "runEpoch") {
		return nil, fault("COMMAND_CONFLICT")
	}
	if e = checkEpoch(r, q); e != nil {
		return nil, e
	}
	if e = boundProducer(ctx, tx, p, r); e != nil {
		return nil, e
	}
	var state, producer, receipt string
	var rev int64
	e = tx.QueryRow(ctx, `SELECT status,producer_incarnation,receipt_id,revision FROM dl05_runtime_inbox WHERE command_id=$1`, q["commandId"]).Scan(&state, &producer, &receipt, &rev)
	if e != nil {
		return nil, normErr(e)
	}
	if producer != p.InstanceID {
		return nil, fault("FORBIDDEN")
	}
	// Repeated START never returns the original true authorization, even when the
	// response was lost. Uncertainty here intentionally sacrifices availability.
	if state != "ACCEPTED" {
		return Object{"requestId": q["requestId"], "startAuthorized": false, "state": state, "revision": rev, "evidenceRef": receipt}, nil
	}
	if num(q, "expectedInboxRevision") != rev {
		return nil, fault("STATE_CONFLICT")
	}
	if _, e = s.validLease(ctx, tx, p, r, "ACTIVE", false); e != nil {
		return nil, e
	}
	if e = s.validateSession(ctx, tx, p, r); e != nil {
		return nil, e
	}
	if e = s.validatePayload(ctx, tx, p, r, obj(cmd, "payload"), true); e != nil {
		return nil, e
	}
	var valid bool
	e = tx.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM dl05_output_permits pm JOIN dl05_room_outputs ro ON ro.room_id=pm.room_id AND ro.output_binding_version=pm.output_binding_version AND ro.active_run_id=pm.run_id WHERE pm.permit_id=$1 AND pm.run_id=$2 AND pm.run_epoch=$3 AND pm.session_id=$4 AND pm.producer_incarnation=$5 AND pm.revoked_at IS NULL AND pm.expires_at>clock_timestamp())`, q["permitId"], r["runId"], num(q, "runEpoch"), cmd["sessionId"], p.InstanceID).Scan(&valid)
	if e != nil {
		return nil, e
	}
	if !valid {
		return nil, fault("OUTPUT_FENCE_UNPROVEN")
	}
	if str(obj(cmd, "payload"), "mode") == "COMMENT_QUESTION" {
		var prepared bool
		e = tx.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM dl05_answer_artifacts x JOIN dl05_attempts a USING(command_id) WHERE x.command_id=$1 AND x.text_hash=a.answer_text_hash)`, q["commandId"]).Scan(&prepared)
		if e != nil {
			return nil, e
		}
		if !prepared {
			return nil, fault("DEPENDENCY_UNAVAILABLE")
		}
	}
	tag, e := tx.Exec(ctx, `UPDATE dl05_runtime_inbox SET status='STARTED',started_at=clock_timestamp(),revision=revision+1 WHERE command_id=$1 AND status='ACCEPTED' AND revision=$2 AND executor_sealed_at IS NULL`, q["commandId"], rev)
	if e != nil {
		return nil, e
	}
	if tag.RowsAffected() != 1 {
		return nil, fault("STATE_CONFLICT")
	}
	return Object{"requestId": q["requestId"], "startAuthorized": true, "state": "STARTED", "revision": rev + 1, "evidenceRef": receipt}, nil
}
func (s *Store) query(ctx context.Context, tx pgx.Tx, p Principal, r, q Object) (Object, error) {
	cmd, e := commandFor(ctx, tx, r, str(q, "commandId"))
	if e != nil {
		return nil, normErr(e)
	}
	if str(cmd, "operation") != "EXECUTE_TURN" || num(cmd, "runEpoch") != num(q, "runEpoch") {
		return nil, fault("COMMAND_CONFLICT")
	}
	if p.Role == "RUNTIME_JOURNAL" {
		var bound string
		e = tx.QueryRow(ctx, `SELECT COALESCE(producer_incarnation,'') FROM dl05_run_terms WHERE run_id=$1 AND run_epoch=$2`, r["runId"], num(q, "runEpoch")).Scan(&bound)
		if e != nil {
			return nil, e
		}
		if bound != p.InstanceID {
			return nil, fault("FORBIDDEN")
		}
	}
	status := Object{"commandId": cmd["commandId"], "requestHash": cmd["requestHash"], "runEpoch": cmd["runEpoch"], "attemptId": cmd["attemptId"], "state": "UNKNOWN", "lastCheckpoint": nil, "receiptId": nil, "executorIncarnation": nil, "executorSealed": false, "revision": int64(1), "evidenceRef": nil}
	var state, receipt, producer string
	var rev int64
	var sealed bool
	e = tx.QueryRow(ctx, `SELECT status,receipt_id,producer_incarnation,revision,executor_sealed_at IS NOT NULL FROM dl05_runtime_inbox WHERE command_id=$1`, cmd["commandId"]).Scan(&state, &receipt, &producer, &rev, &sealed)
	if e != nil && !errors.Is(e, pgx.ErrNoRows) {
		return nil, e
	}
	if e == nil {
		status["state"] = state
		status["receiptId"] = receipt
		status["executorIncarnation"] = producer
		status["revision"] = rev
		status["executorSealed"] = sealed
		status["evidenceRef"] = receipt
	}
	cp, e := jsonRow(tx.QueryRow(ctx, `SELECT c.envelope FROM dl05_checkpoints c JOIN dl05_attempts a ON a.attempt_id=c.attempt_id AND a.last_checkpoint=c.state WHERE c.command_id=$1 AND c.projection_status='APPLIED' ORDER BY c.received_at DESC,c.checkpoint_id DESC LIMIT 1`, cmd["commandId"]))
	if e == nil {
		status["lastCheckpoint"] = cp
	}
	if e != nil && !errors.Is(e, pgx.ErrNoRows) {
		return nil, e
	}
	return Object{"requestId": q["requestId"], "status": status}, nil
}
