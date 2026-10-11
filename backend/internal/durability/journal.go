package durability

import (
	"astralive/backend/internal/ids"
	"context"
	"encoding/json"
	"github.com/jackc/pgx/v5"
	"time"
)

type Acceptance struct {
	AttemptID      string `json:"attemptId,omitempty"`
	CommandID      string `json:"commandId"`
	SessionID      string `json:"sessionId"`
	RunEpoch       int64  `json:"runEpoch"`
	TraceID        string `json:"traceId"`
	State          string `json:"state"`
	Accepted       bool   `json:"accepted"`
	OperationID    string `json:"operationId"`
	Execute        bool   `json:"execute"`
	ExecutionState string `json:"executionState"`
	Run            Run    `json:"run"`
	ReceiptSeq     int64  `json:"receiptSeq"`
}

// Accept verifies the complete stored envelope, not just a caller-supplied fingerprint.
func (s *Store) Accept(ctx context.Context, raw json.RawMessage) (Acceptance, error) {
	var c Command
	if e := json.Unmarshal(raw, &c); e != nil {
		return Acceptance{}, e
	}
	if e := c.Validate(); e != nil {
		return Acceptance{}, e
	}
	hash, e := Fingerprint(raw)
	if e != nil || hash != c.RequestFingerprint {
		return Acceptance{}, ErrConflict
	}
	tx, e := s.DB.Begin(ctx)
	if e != nil {
		return Acceptance{}, e
	}
	defer tx.Rollback(ctx)
	r, e := s.current(ctx, tx, c.SessionID, false, c.CommandType == "STOP_SESSION")
	if e != nil {
		return Acceptance{}, e
	}
	if r.Epoch != c.RunEpoch || c.CommandSeq < r.BarrierSeq || c.TimelineEpoch != 0 && c.TimelineEpoch != r.TimelineEpoch {
		return Acceptance{}, ErrFence
	}
	if r.Status != "ACTIVE" && !(r.Status == "STOPPING" && c.CommandType == "STOP_SESSION") && !(r.Status == "RECOVERY_REQUIRED" && c.CommandType == "BEGIN_RUN") {
		return Acceptance{}, ErrSealed
	}
	var stored []byte
	var delivery string
	e = tx.QueryRow(ctx, `SELECT payload_envelope,delivery_state FROM v05_outbox WHERE valid_until>clock_timestamp() AND session_id=$1 AND run_epoch=$2 AND command_id=$3 FOR UPDATE`, c.SessionID, c.RunEpoch, c.CommandID).Scan(&stored, &delivery)
	if e != nil {
		return Acceptance{}, e
	}
	a, _ := Hash(stored)
	b, _ := Hash(raw)
	if a != b {
		return Acceptance{}, ErrConflict
	}
	if delivery == "CANCELLED" || delivery == "FAILED" {
		return Acceptance{}, ErrSealed
	}
	_, e = tx.Exec(ctx, `INSERT INTO v05_inbox(session_id,run_epoch,command_id,tenant_id,user_id,request_fingerprint,command_type,command_seq,operation_id)
 SELECT session_id,run_epoch,command_id,tenant_id,user_id,request_fingerprint,command_type,command_seq,$2 FROM v05_outbox WHERE command_id=$1 ON CONFLICT DO NOTHING`, c.CommandID, ids.New("op_runtime"))
	if e != nil {
		return Acceptance{}, e
	}
	_, e = tx.Exec(ctx, `INSERT INTO v05_receipts(session_id,run_epoch,command_id,receipt_seq,tenant_id,user_id,state,producer_incarnation,evidence_type,evidence_ref,observation_hash)
 SELECT session_id,run_epoch,command_id,1,tenant_id,user_id,'accepted',$2,'inbox_acceptance',operation_id,request_fingerprint FROM v05_inbox WHERE command_id=$1 ON CONFLICT DO NOTHING`, c.CommandID, s.Owner)
	if e != nil {
		return Acceptance{}, e
	}
	_, e = tx.Exec(ctx, `UPDATE v05_inbox SET last_receipt_seq=GREATEST(last_receipt_seq,1) WHERE command_id=$1`, c.CommandID)
	if e != nil {
		return Acceptance{}, e
	}
	out := Acceptance{Accepted: true, Run: r, CommandID: c.CommandID, SessionID: c.SessionID, RunEpoch: c.RunEpoch, TraceID: c.TraceID, State: "accepted"}
	e = tx.QueryRow(ctx, `SELECT operation_id,execution_state,last_receipt_seq,COALESCE(execution_attempt_id,'') FROM v05_inbox WHERE command_id=$1 AND session_id=$2 AND run_epoch=$3`, c.CommandID, c.SessionID, c.RunEpoch).Scan(&out.OperationID, &out.ExecutionState, &out.ReceiptSeq, &out.AttemptID)
	if e != nil {
		return out, e
	}
	out.Execute = out.ExecutionState == "ACCEPTED"
	return out, tx.Commit(ctx)
}
func (s *Store) StartAttempt(ctx context.Context, sid, id, incarnation string, token int64) (Acceptance, error) {
	if incarnation == "" {
		return Acceptance{}, ErrConflict
	}
	tx, e := s.DB.Begin(ctx)
	if e != nil {
		return Acceptance{}, e
	}
	defer tx.Rollback(ctx)
	var kind, trace string
	var sequence, epoch int64
	e = tx.QueryRow(ctx, `SELECT command_type,command_seq,run_epoch,trace_id FROM v05_outbox WHERE command_id=$1 AND session_id=$2`, id, sid).Scan(&kind, &sequence, &epoch, &trace)
	if e != nil {
		return Acceptance{}, e
	}
	r, e := s.current(ctx, tx, sid, false, kind == "STOP_SESSION")
	if e != nil {
		return Acceptance{}, e
	}
	if token != r.Token || epoch != r.Epoch {
		return Acceptance{}, ErrFence
	}
	if sequence < r.BarrierSeq {
		return Acceptance{}, ErrSealed
	}
	if r.Status != "ACTIVE" && kind != "STOP_SESSION" && kind != "BEGIN_RUN" {
		return Acceptance{}, ErrSealed
	}
	tag, e := tx.Exec(ctx, `UPDATE v05_inbox SET execution_state='STARTED',execution_attempt_id=$4,executor_incarnation=$5,execution_lease_token=$6,execution_started_at=clock_timestamp()
 WHERE command_id=$1 AND session_id=$2 AND run_epoch=$3 AND execution_state='ACCEPTED'`, id, sid, r.Epoch, ids.New("attempt"), incarnation, token)
	if e != nil {
		return Acceptance{}, e
	}
	if tag.RowsAffected() == 1 {
		_, e = tx.Exec(ctx, `INSERT INTO v05_receipts(session_id,run_epoch,command_id,receipt_seq,tenant_id,user_id,attempt_id,state,producer_incarnation,evidence_type,evidence_ref,observation_hash)
 SELECT session_id,run_epoch,command_id,2,tenant_id,user_id,execution_attempt_id,'accepted',executor_incarnation,'execution_started',execution_attempt_id,request_fingerprint FROM v05_inbox WHERE command_id=$1`, id)
		if e != nil {
			return Acceptance{}, e
		}
		_, e = tx.Exec(ctx, `UPDATE v05_inbox SET last_receipt_seq=2 WHERE command_id=$1`, id)
		if e != nil {
			return Acceptance{}, e
		}
	}
	out := Acceptance{Accepted: true, Execute: tag.RowsAffected() == 1, Run: r, CommandID: id, SessionID: sid, RunEpoch: epoch, TraceID: trace, State: "accepted"}
	e = tx.QueryRow(ctx, `SELECT operation_id,execution_state,last_receipt_seq,COALESCE(execution_attempt_id,'') FROM v05_inbox WHERE command_id=$1 AND session_id=$2 AND run_epoch=$3`, id, sid, r.Epoch).Scan(&out.OperationID, &out.ExecutionState, &out.ReceiptSeq, &out.AttemptID)
	if e != nil {
		return out, e
	}
	if !out.Execute { // STARTED cannot be retried, even by the same incarnation.
		_, e = tx.Exec(ctx, `UPDATE v05_inbox SET execution_state='UNKNOWN' WHERE command_id=$1 AND execution_state='STARTED'`, id)
		if e != nil {
			return out, e
		}
	}
	return out, tx.Commit(ctx)
}

// Grant is checked by Runtime before new generation/publication, then bounded by a monotonic expiry.
func (s *Store) Grant(ctx context.Context, sid string, epoch int64) (Run, error) {
	tx, e := s.DB.Begin(ctx)
	if e != nil {
		return Run{}, e
	}
	defer tx.Rollback(ctx)
	r, e := s.Current(ctx, tx, sid, false)
	if e != nil {
		return r, e
	}
	if r.Epoch != epoch || r.Status != "ACTIVE" {
		return r, ErrSealed
	}
	return r, nil
}

type Observation struct {
	SessionID    string `json:"sessionId"`
	RunEpoch     int64  `json:"runEpoch"`
	CommandID    string `json:"commandId"`
	ReceiptSeq   int64  `json:"receiptSeq"`
	State        string `json:"state"`
	Outcome      string `json:"outcome,omitempty"`
	Producer     string `json:"producerIncarnation"`
	EvidenceType string `json:"evidenceType"`
	EvidenceRef  string `json:"evidenceRef"`
	ReasonCode   string `json:"reasonCode,omitempty"`
}

func (s *Store) Observe(ctx context.Context, o Observation) error {
	// Timeline states belong to B/C proof validation and are deliberately not accepted by this ordinary-Speak seam.
	if o.ReceiptSeq < 1 || o.RunEpoch < 1 || o.Producer == "" || o.EvidenceRef == "" || o.EvidenceType != "control_cleanup" || o.State != "completed" {
		return ErrConflict
	}
	tx, e := s.DB.Begin(ctx)
	if e != nil {
		return e
	}
	defer tx.Rollback(ctx)
	var kind, producer, state string
	e = tx.QueryRow(ctx, `SELECT command_type,COALESCE(executor_incarnation,''),execution_state FROM v05_inbox WHERE session_id=$1 AND run_epoch=$2 AND command_id=$3`, o.SessionID, o.RunEpoch, o.CommandID).Scan(&kind, &producer, &state)
	if e != nil {
		return e
	}
	r, e := s.current(ctx, tx, o.SessionID, false, kind == "STOP_SESSION")
	if e != nil {
		return e
	}
	if r.Epoch != o.RunEpoch {
		return ErrFence
	}
	if kind == "SPEAK" || producer != o.Producer {
		return ErrConflict
	}
	raw, _ := json.Marshal(o)
	hash, _ := Hash(raw)
	var existing string
	e = tx.QueryRow(ctx, `SELECT observation_hash FROM v05_receipts WHERE session_id=$1 AND run_epoch=$2 AND command_id=$3 AND receipt_seq=$4`, o.SessionID, o.RunEpoch, o.CommandID, o.ReceiptSeq).Scan(&existing)
	if e == nil {
		if existing != hash {
			return ErrConflict
		}
		return nil
	}
	if e != pgx.ErrNoRows {
		return e
	}
	if state != "STARTED" {
		return ErrConflict
	}
	_, e = tx.Exec(ctx, `INSERT INTO v05_receipts(session_id,run_epoch,command_id,receipt_seq,tenant_id,user_id,state,producer_incarnation,evidence_type,evidence_ref,observation_hash)
 SELECT session_id,run_epoch,command_id,$2,tenant_id,user_id,$3,$4,$5,$6,$7 FROM v05_inbox WHERE command_id=$1`, o.CommandID, o.ReceiptSeq, o.State, o.Producer, o.EvidenceType, o.EvidenceRef, hash)
	if e != nil {
		return e
	}
	_, e = tx.Exec(ctx, `UPDATE v05_inbox SET execution_state='TERMINAL',terminal_at=clock_timestamp(),last_receipt_seq=$2 WHERE command_id=$1`, o.CommandID, o.ReceiptSeq)
	if e != nil {
		return e
	}
	return tx.Commit(ctx)
}

// DurableEvent wraps the frozen legacy event without adding fields to its v1 DTO.
type DurableEvent struct {
	AttemptID     string          `json:"attemptId,omitempty"`
	GenerationID  *int64          `json:"generationId,omitempty"`
	TimelineEpoch *int64          `json:"timelineEpoch,omitempty"`
	SchemaVersion string          `json:"schemaVersion"`
	EventID       string          `json:"eventId"`
	SessionID     string          `json:"sessionId"`
	RunEpoch      int64           `json:"runEpoch"`
	Producer      string          `json:"producerIncarnation"`
	ProducerSeq   int64           `json:"producerSeq"`
	CommandID     string          `json:"commandId"`
	TraceID       string          `json:"traceId"`
	OccurredAt    time.Time       `json:"occurredAt"`
	EventType     string          `json:"eventType"`
	Source        string          `json:"source"`
	Payload       json.RawMessage `json:"payload"`
}

func (s *Store) Ingest(ctx context.Context, raw json.RawMessage) (bool, error) {
	var ev DurableEvent
	if e := json.Unmarshal(raw, &ev); e != nil {
		return false, e
	}
	if ev.SchemaVersion != "0.5" || ev.EventID == "" || ev.SessionID == "" || ev.RunEpoch < 1 || ev.RunEpoch > MaxEpoch || ev.Producer == "" || ev.ProducerSeq < 1 || ev.ProducerSeq > MaxEpoch || ev.CommandID == "" || ev.Source != "AI_RUNTIME" || ev.OccurredAt.IsZero() {
		return false, ErrConflict
	}
	h, e := EventHash(raw)
	if e != nil {
		return false, e
	}
	tx, e := s.DB.Begin(ctx)
	if e != nil {
		return false, e
	}
	defer tx.Rollback(ctx)
	// Historical events remain auditable after lease expiry/Stop; only projection checks the current fence.
	var tenant, user string
	e = tx.QueryRow(ctx, `SELECT i.tenant_id,i.user_id FROM v05_inbox i JOIN resource_owners o ON o.kind='session' AND o.resource_id=i.session_id AND o.tenant_id=i.tenant_id AND o.user_id=i.user_id
 JOIN live_sessions se ON se.id=i.session_id JOIN resource_owners ro ON ro.kind='room' AND ro.resource_id=se.room_id AND ro.tenant_id=i.tenant_id AND ro.user_id=i.user_id WHERE i.session_id=$1 AND i.run_epoch=$2 AND i.command_id=$3 AND i.executor_incarnation=$4`, ev.SessionID, ev.RunEpoch, ev.CommandID, ev.Producer).Scan(&tenant, &user)
	if e != nil {
		return false, e
	}
	if ev.AttemptID != "" || ev.GenerationID != nil || ev.TimelineEpoch != nil {
		var match bool
		e = tx.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM v05_inbox WHERE session_id=$1 AND run_epoch=$2 AND command_id=$3 AND ($4='' OR execution_attempt_id=$4) AND ($5::bigint IS NULL OR generation_id=$5) AND ($6::bigint IS NULL OR timeline_epoch=$6))`, ev.SessionID, ev.RunEpoch, ev.CommandID, ev.AttemptID, ev.GenerationID, ev.TimelineEpoch).Scan(&match)
		if e != nil {
			return false, e
		}
		if !match {
			return false, ErrConflict
		}
	}
	var existing string
	e = tx.QueryRow(ctx, `SELECT envelope_hash FROM v05_events WHERE event_id=$1 OR (session_id=$2 AND run_epoch=$3 AND producer_incarnation=$4 AND producer_seq=$5)`, ev.EventID, ev.SessionID, ev.RunEpoch, ev.Producer, ev.ProducerSeq).Scan(&existing)
	if e == nil {
		if h != existing {
			return false, ErrConflict
		}
		return false, nil
	}
	if e != pgx.ErrNoRows {
		return false, e
	}
	var seq int64
	e = tx.QueryRow(ctx, `UPDATE v05_session_runs SET current_event_seq=current_event_seq+1 WHERE session_id=$1 AND run_epoch=$2 RETURNING current_event_seq`, ev.SessionID, ev.RunEpoch).Scan(&seq)
	if e != nil {
		return false, e
	}
	_, e = tx.Exec(ctx, `INSERT INTO v05_events(event_id,tenant_id,user_id,session_id,run_epoch,event_seq,producer_incarnation,producer_seq,event_type,command_id,trace_id,occurred_at,envelope_hash,envelope) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)`, ev.EventID, tenant, user, ev.SessionID, ev.RunEpoch, seq, ev.Producer, ev.ProducerSeq, ev.EventType, ev.CommandID, ev.TraceID, ev.OccurredAt, h, raw)
	if e != nil {
		return false, e
	}
	return true, tx.Commit(ctx)
}

func (s *Store) ReconcileIncarnation(ctx context.Context, sid, id, incarnation string) error {
	_, e := s.DB.Exec(ctx, `UPDATE v05_inbox SET execution_state='UNKNOWN' WHERE session_id=$1 AND command_id=$2 AND executor_incarnation<>$3 AND execution_state='STARTED'`, sid, id, incarnation)
	return e
}

// StartMedia journals an immutable media attempt and generation before provider/sink side effects.
// An already allocated attempt is UNKNOWN to a fresh caller, never a permission to replay audio.
func (s *Store) StartMedia(ctx context.Context, sid, id, producer string, floor int64) (Run, int64, error) {
	if floor < 0 || floor >= MaxEpoch {
		return Run{}, 0, ErrFence
	}
	tx, e := s.DB.Begin(ctx)
	if e != nil {
		return Run{}, 0, e
	}
	defer tx.Rollback(ctx)
	r, e := s.Current(ctx, tx, sid, false)
	if e != nil {
		return r, 0, e
	}
	if r.Status != "ACTIVE" {
		return r, 0, ErrSealed
	}
	var allowed bool
	e = tx.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM v05_inbox WHERE command_id=$1 AND session_id=$2 AND run_epoch=$3 AND command_type='SPEAK' AND execution_state='STARTED' AND generation_id IS NULL AND executor_incarnation=$4 AND execution_lease_token=$5 AND command_seq>=$6)`, id, sid, r.Epoch, producer, r.Token, r.BarrierSeq).Scan(&allowed)
	if e != nil {
		return r, 0, e
	}
	if !allowed {
		return r, 0, ErrFence
	}
	var generation int64
	e = tx.QueryRow(ctx, `UPDATE v05_session_runs SET generation_high_watermark=GREATEST(generation_high_watermark,$3)+1 WHERE session_id=$1 AND run_epoch=$2 AND generation_high_watermark<9007199254740991 RETURNING generation_high_watermark`, sid, r.Epoch, floor).Scan(&generation)
	if e != nil {
		return r, 0, e
	}
	_, e = tx.Exec(ctx, `UPDATE v05_inbox SET generation_id=$2,timeline_epoch=$3,last_receipt_seq=last_receipt_seq+1 WHERE command_id=$1`, id, generation, r.TimelineEpoch)
	if e != nil {
		return r, 0, e
	}
	_, e = tx.Exec(ctx, `INSERT INTO v05_receipts(session_id,run_epoch,command_id,receipt_seq,tenant_id,user_id,attempt_id,state,producer_incarnation,evidence_type,evidence_ref,range_sinks,observation_hash)
 SELECT session_id,run_epoch,command_id,last_receipt_seq,tenant_id,user_id,execution_attempt_id,'generating',executor_incarnation,'execution_started',execution_attempt_id,jsonb_build_object('generationId',generation_id,'timelineEpoch',timeline_epoch),request_fingerprint FROM v05_inbox WHERE command_id=$1`, id)
	if e != nil {
		return r, 0, e
	}
	return r, generation, tx.Commit(ctx)
}
