package durability

import (
	"context"
	"encoding/json"
	"time"

	"astralive/backend/internal/ids"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

const LeaseTTL = 10 * time.Second

type Store struct {
	DB    *pgxpool.Pool
	Owner string
}
type Run struct {
	TimelineEpoch int64  `json:"timelineEpoch"`
	SessionID     string `json:"sessionId"`
	Epoch         int64  `json:"runEpoch"`
	Token         int64  `json:"leaseToken"`
	Status        string `json:"status"`
	RemainingMS   int64  `json:"remainingMs"`
	BarrierSeq    int64  `json:"barrierSeq"`
}

func New(db *pgxpool.Pool) *Store { return &Store{db, ids.New("owner")} }

// LockAuthority serializes every admission, Stop and recovery on the same SQL row.
// Trusted scope is derived from BOTH Session and Room ownership and captured binding.
func LockAuthority(ctx context.Context, tx pgx.Tx, sid string) (string, string, string, error) {
	return lockAuthority(ctx, tx, sid, false)
}
func lockAuthority(ctx context.Context, tx pgx.Tx, sid string, cleanup bool) (string, string, string, error) {
	var tenant, user, binding string
	e := tx.QueryRow(ctx, `SELECT o.tenant_id,o.user_id,b.binding_id FROM live_sessions s
 JOIN resource_owners o ON o.kind='session' AND o.resource_id=s.id
 JOIN resource_owners ro ON ro.kind='room' AND ro.resource_id=s.room_id AND ro.tenant_id=o.tenant_id AND ro.user_id=o.user_id
 JOIN session_provider_bindings b ON b.session_id=s.id AND b.tenant_id=o.tenant_id AND b.user_id=o.user_id
 WHERE s.id=$1 AND ($2 OR s.status NOT IN ('ENDED','FAILED')) AND ($2 OR b.released_at IS NULL AND b.expires_at>clock_timestamp())
 FOR UPDATE OF s,o,ro,b`, sid, cleanup).Scan(&tenant, &user, &binding)
	return tenant, user, binding, e
}
func (s *Store) InitialRun(ctx context.Context, tx pgx.Tx, sid string) (Run, error) {
	t, u, b, e := LockAuthority(ctx, tx, sid)
	if e != nil {
		return Run{}, e
	}
	var exists bool
	e = tx.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM v05_recovery_leases WHERE session_id=$1)`, sid).Scan(&exists)
	if e != nil {
		return Run{}, e
	}
	if exists {
		return Run{}, ErrConflict
	}
	r := Run{SessionID: sid, Epoch: 1, Token: 1, Status: "ACTIVE", TimelineEpoch: 1}
	_, e = tx.Exec(ctx, `INSERT INTO v05_session_runs(session_id,run_epoch,tenant_id,user_id,owner_id,lease_token,status,provider_binding_id) VALUES($1,1,$2,$3,$4,1,'ACTIVE',$5)`, sid, t, u, s.Owner, b)
	if e != nil {
		return r, e
	}
	_, e = tx.Exec(ctx, `INSERT INTO v05_recovery_leases(session_id,tenant_id,user_id,owner_id,lease_token,run_epoch,expires_at) VALUES($1,$2,$3,$4,1,1,clock_timestamp()+interval '10 seconds')`, sid, t, u, s.Owner)
	return r, e
}
func (s *Store) Current(ctx context.Context, tx pgx.Tx, sid string, owned bool) (Run, error) {
	return s.current(ctx, tx, sid, owned, false)
}
func (s *Store) current(ctx context.Context, tx pgx.Tx, sid string, owned, cleanup bool) (Run, error) {
	if _, _, _, e := lockAuthority(ctx, tx, sid, cleanup); e != nil {
		if e == pgx.ErrNoRows {
			return Run{}, ErrFence
		}
		return Run{}, e
	}
	var r Run
	var owner string
	e := tx.QueryRow(ctx, `SELECT l.session_id,l.run_epoch,l.lease_token,r.status,l.owner_id,r.control_barrier_seq,r.current_timeline_epoch,
 GREATEST(0,floor(extract(epoch FROM(l.expires_at-clock_timestamp()))*1000))::bigint
 FROM v05_recovery_leases l JOIN v05_session_runs r USING(session_id,run_epoch)
 WHERE l.session_id=$1 FOR UPDATE OF l,r`, sid).Scan(&r.SessionID, &r.Epoch, &r.Token, &r.Status, &owner, &r.BarrierSeq, &r.TimelineEpoch, &r.RemainingMS)
	if e == nil && (r.RemainingMS <= 0 || owned && owner != s.Owner) {
		e = ErrFence
	}
	return r, e
}

// Enqueue must be called within the caller's business transaction. An idempotency replay returns the stored envelope.
func (s *Store) Enqueue(ctx context.Context, tx pgx.Tx, r Run, kind, key, trace, uid string, payload any) (Command, error) {
	p, e := json.Marshal(payload)
	if e != nil {
		return Command{}, e
	}
	c := Command{SchemaVersion: "0.5", CommandID: ids.New("cmd"), SessionID: r.SessionID, RunEpoch: r.Epoch, TraceID: trace, CommandType: kind, IdempotencyKey: key, CreatedAt: time.Now().UTC().Format(time.RFC3339Nano), Payload: p}
	if kind == "SPEAK" || kind == "FORCE_INTERRUPT" || kind == "STOP_SESSION" {
		c.NarrationID, c.SegmentID = json.RawMessage("null"), json.RawMessage("null")
		c.TimelineEpoch = r.TimelineEpoch
		if c.TimelineEpoch < 1 {
			c.TimelineEpoch = 1
		}
		c.Lane = "OPERATOR"
		var utterance struct {
			Source string `json:"source"`
		}
		_ = json.Unmarshal(p, &utterance)
		if utterance.Source == "PLATFORM_EVENT" {
			c.Lane = "AUDIENCE_ANSWER"
		}
		if utterance.Source == "AUTO_SCRIPT" {
			c.Lane = "NARRATION"
		}
		if utterance.Source == "SYSTEM" {
			c.Lane = "SYSTEM"
		}
	}
	raw, _ := json.Marshal(c)
	c.RequestFingerprint, e = Fingerprint(raw)
	if e != nil {
		return c, e
	}
	var old []byte
	e = tx.QueryRow(ctx, `SELECT payload_envelope FROM v05_outbox WHERE session_id=$1 AND run_epoch=$2 AND command_type=$3 AND idempotency_key=$4`, r.SessionID, r.Epoch, kind, key).Scan(&old)
	if e == nil {
		var existing Command
		if e = json.Unmarshal(old, &existing); e != nil {
			return c, e
		}
		if existing.RequestFingerprint != c.RequestFingerprint {
			return c, ErrConflict
		}
		return existing, nil
	}
	if e != pgx.ErrNoRows {
		return c, e
	}
	if r.Status != "ACTIVE" && kind != "STOP_SESSION" && kind != "BEGIN_RUN" {
		return c, ErrSealed
	}
	e = tx.QueryRow(ctx, `UPDATE v05_session_runs SET current_command_seq=current_command_seq+1 WHERE session_id=$1 AND run_epoch=$2 AND current_command_seq<9007199254740991 RETURNING current_command_seq`, r.SessionID, r.Epoch).Scan(&c.CommandSeq)
	if e != nil {
		return c, e
	}
	raw, _ = json.Marshal(c)
	_, e = tx.Exec(ctx, `INSERT INTO v05_outbox(command_id,tenant_id,user_id,session_id,run_epoch,command_seq,command_type,idempotency_key,request_fingerprint,trace_id,utterance_id,payload_envelope,valid_until)
 SELECT $1,tenant_id,user_id,session_id,run_epoch,$4,$5,$6,$7,$8,NULLIF($9,''),$10,$11 FROM v05_session_runs WHERE session_id=$2 AND run_epoch=$3`, c.CommandID, r.SessionID, r.Epoch, c.CommandSeq, kind, key, c.RequestFingerprint, trace, uid, raw, commandDeadline(ctx))
	return c, e
}
func (s *Store) Seal(ctx context.Context, tx pgx.Tx, r Run) error {
	_, e := tx.Exec(ctx, `UPDATE v05_session_runs SET status='STOPPING',sealed_at=clock_timestamp() WHERE session_id=$1 AND run_epoch=$2`, r.SessionID, r.Epoch)
	if e != nil {
		return e
	}
	_, e = tx.Exec(ctx, `UPDATE v05_outbox SET delivery_state=CASE WHEN delivery_state='CLAIMED' THEN 'UNKNOWN' ELSE 'CANCELLED' END,last_error_code='RUN_SEALED',updated_at=clock_timestamp()
 WHERE session_id=$1 AND run_epoch=$2 AND command_type<>'STOP_SESSION' AND delivery_state IN ('PENDING','CLAIMED')`, r.SessionID, r.Epoch)
	return e
}
func (s *Store) Renew(ctx context.Context) error {
	// Never resurrect expired ownership, even with the same process ID.
	_, e := s.DB.Exec(ctx, `UPDATE v05_recovery_leases l SET expires_at=clock_timestamp()+interval '10 seconds',renewed_at=clock_timestamp()
 FROM v05_session_runs r,live_sessions se,session_provider_bindings b,resource_owners o,resource_owners ro
 WHERE l.owner_id=$1 AND l.expires_at>clock_timestamp() AND r.session_id=l.session_id AND r.run_epoch=l.run_epoch
 AND r.status IN ('ACTIVE','STOPPING') AND se.id=l.session_id AND se.status NOT IN ('ENDED','FAILED')
 AND b.session_id=se.id AND b.released_at IS NULL AND b.expires_at>clock_timestamp()
 AND o.kind='session' AND o.resource_id=se.id AND o.tenant_id=l.tenant_id AND o.user_id=l.user_id
 AND ro.kind='room' AND ro.resource_id=se.room_id AND ro.tenant_id=l.tenant_id AND ro.user_id=l.user_id`, s.Owner)
	return e
}

type Claim struct {
	Command Command
	Raw     json.RawMessage
	Token   int64
	Attempt int
	Owner   string
}

func (s *Store) Claim(ctx context.Context) (Claim, error) {
	tx, e := s.DB.Begin(ctx)
	if e != nil {
		return Claim{}, e
	}
	defer tx.Rollback(ctx)
	// Expired CLAIMED is ambiguous: receipt reconciliation is required before redelivery.
	_, e = tx.Exec(ctx, `UPDATE v05_outbox SET delivery_state='UNKNOWN',unknown_since=COALESCE(unknown_since,clock_timestamp()),last_error_code='DELIVERY_LEASE_EXPIRED',updated_at=clock_timestamp() WHERE delivery_state='CLAIMED' AND lease_expires_at<=clock_timestamp()`)
	if e != nil {
		return Claim{}, e
	}
	var c Claim
	c.Owner = s.Owner
	e = tx.QueryRow(ctx, `WITH candidate AS (
 SELECT o.command_id FROM v05_outbox o JOIN v05_recovery_leases l USING(session_id,run_epoch)
 JOIN v05_session_runs r USING(session_id,run_epoch)
 WHERE o.delivery_state='PENDING' AND o.next_attempt_at<=clock_timestamp() AND o.attempt_count<5
 AND l.owner_id=$1 AND l.expires_at>clock_timestamp()
 AND (r.status='ACTIVE' OR r.status='STOPPING' AND o.command_type='STOP_SESSION' OR r.status='RECOVERY_REQUIRED' AND o.command_type='BEGIN_RUN')
 AND (o.command_type IN ('STOP_SESSION','FORCE_INTERRUPT','BEGIN_RUN') OR NOT EXISTS (
 SELECT 1 FROM v05_outbox prior WHERE prior.session_id=o.session_id AND prior.run_epoch=o.run_epoch AND prior.command_seq<o.command_seq AND prior.delivery_state IN ('PENDING','CLAIMED','UNKNOWN')))
 ORDER BY CASE o.command_type WHEN 'STOP_SESSION' THEN 0 WHEN 'FORCE_INTERRUPT' THEN 1 ELSE 2 END,o.created_at
 FOR UPDATE OF o SKIP LOCKED LIMIT 1)
 UPDATE v05_outbox o SET delivery_state='CLAIMED',attempt_count=attempt_count+1,lease_owner=$1,lease_token=lease_token+1,
 lease_expires_at=clock_timestamp()+interval '10 seconds',updated_at=clock_timestamp()
 FROM candidate c WHERE o.command_id=c.command_id RETURNING payload_envelope,lease_token,attempt_count`, s.Owner).Scan(&c.Raw, &c.Token, &c.Attempt)
	if e != nil {
		if e == pgx.ErrNoRows {
			if err := tx.Commit(ctx); err != nil {
				return c, err
			}
		}
		return c, e
	}
	if e = json.Unmarshal(c.Raw, &c.Command); e != nil {
		return c, e
	}
	return c, tx.Commit(ctx)
}
func (s *Store) Extend(ctx context.Context, c Claim) error {
	tag, e := s.DB.Exec(ctx, `UPDATE v05_outbox o SET lease_expires_at=clock_timestamp()+interval '10 seconds' FROM v05_recovery_leases l
 WHERE o.command_id=$1 AND o.delivery_state='CLAIMED' AND o.lease_owner=$2 AND o.lease_token=$3 AND o.lease_expires_at>clock_timestamp()
 AND l.session_id=o.session_id AND l.run_epoch=o.run_epoch AND l.owner_id=$2 AND l.expires_at>clock_timestamp()`, c.Command.CommandID, c.Owner, c.Token)
	if e == nil && tag.RowsAffected() != 1 {
		return ErrFence
	}
	return e
}
func (s *Store) Finish(ctx context.Context, c Claim, state, code string, delay time.Duration) error {
	tx, e := s.DB.Begin(ctx)
	if e != nil {
		return e
	}
	defer tx.Rollback(ctx)
	r, e := s.current(ctx, tx, c.Command.SessionID, true, c.Command.CommandType == "STOP_SESSION")
	if e != nil {
		return e
	}
	if r.Epoch != c.Command.RunEpoch {
		return ErrFence
	}
	if state == "FAILED" {
		var started bool
		e = tx.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM v05_inbox WHERE command_id=$1 AND execution_state IN ('STARTED','UNKNOWN','TERMINAL'))`, c.Command.CommandID).Scan(&started)
		if e != nil {
			return e
		}
		if started {
			state, code = "UNKNOWN", "RECOVERY_UNKNOWN"
		}
	}
	tag, e := tx.Exec(ctx, `UPDATE v05_outbox o SET delivery_state=$4,last_error_code=NULLIF($5,''),next_attempt_at=clock_timestamp()+$6::bigint*interval '1 millisecond',
 unknown_since=CASE WHEN $4='UNKNOWN' THEN COALESCE(unknown_since,clock_timestamp()) ELSE unknown_since END,acked_at=CASE WHEN $4='ACKED' THEN clock_timestamp() ELSE acked_at END,updated_at=clock_timestamp()
 WHERE o.command_id=$1 AND o.delivery_state='CLAIMED' AND o.lease_owner=$2 AND o.lease_token=$3 AND o.lease_expires_at>clock_timestamp()`, c.Command.CommandID, c.Owner, c.Token, state, code, delay.Milliseconds())
	if e != nil {
		return e
	}
	if tag.RowsAffected() != 1 {
		return ErrFence
	}
	if state == "CANCELLED" {
		_, e = tx.Exec(ctx, `UPDATE utterances u SET status='CANCELLED',completed_at=clock_timestamp(),updated_at=clock_timestamp() FROM v05_outbox o WHERE o.command_id=$1 AND o.utterance_id=u.id AND u.status='QUEUED' AND NOT EXISTS(SELECT 1 FROM v05_inbox i WHERE i.command_id=o.command_id AND i.execution_state IN ('STARTED','UNKNOWN','TERMINAL'))`, c.Command.CommandID)
		if e != nil {
			return e
		}
	}
	if state == "FAILED" {
		_, e = tx.Exec(ctx, `UPDATE utterances u SET status='FAILED',failure_code='RUNTIME_UNAVAILABLE',completed_at=clock_timestamp(),updated_at=clock_timestamp() FROM v05_outbox o WHERE o.command_id=$1 AND o.utterance_id=u.id AND u.status='QUEUED'`, c.Command.CommandID)
		if e != nil {
			return e
		}
	}
	if state == "ACKED" || state == "FAILED" {
		receiptState := "ACCEPTED"
		if state == "FAILED" {
			receiptState = "FAILED"
		}
		_, e = tx.Exec(ctx, `UPDATE interaction_receipts ir SET status=$2 FROM v05_interaction_commands ic WHERE ic.session_id=ir.session_id AND ic.trace_id=ir.trace_id AND ic.command_id=$1 AND ir.status='RESERVED'`, c.Command.CommandID, receiptState)
		if e != nil {
			return e
		}
	}
	return tx.Commit(ctx)
}

func (s *Store) Lookup(ctx context.Context, sid, id string) (json.RawMessage, error) {
	var raw []byte
	e := s.DB.QueryRow(ctx, `SELECT jsonb_build_object(
 'command',o.payload_envelope,'commandId',o.command_id,'sessionId',o.session_id,'runEpoch',o.run_epoch,'traceId',o.trace_id,
 'deliveryState',o.delivery_state,'attemptCount',o.attempt_count,'executionState',i.execution_state,'operationId',i.operation_id,
 'generationId',i.generation_id,'timelineEpoch',i.timeline_epoch,'executorIncarnation',i.executor_incarnation,'attemptId',i.execution_attempt_id,'lastReceiptSeq',i.last_receipt_seq,'receiptSeq',i.last_receipt_seq,
 'state',CASE WHEN i.execution_state='UNKNOWN' THEN 'unknown' ELSE latest.state END,'lastKnownState',latest.state,
 'observedAt',to_char(latest.observed_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.MS"Z"'),
 'producerIncarnation',latest.producer_incarnation,'evidenceType',latest.evidence_type,'evidenceRef',latest.evidence_ref,'reasonCode',latest.reason_code)
 FROM v05_outbox o JOIN live_sessions se ON se.id=o.session_id
 JOIN resource_owners so ON so.kind='session' AND so.resource_id=o.session_id AND so.tenant_id=o.tenant_id AND so.user_id=o.user_id
 JOIN resource_owners ro ON ro.kind='room' AND ro.resource_id=se.room_id AND ro.tenant_id=o.tenant_id AND ro.user_id=o.user_id
 LEFT JOIN v05_inbox i ON i.command_id=o.command_id AND i.session_id=o.session_id AND i.run_epoch=o.run_epoch
 LEFT JOIN LATERAL (SELECT * FROM v05_receipts rr WHERE rr.command_id=o.command_id AND rr.session_id=o.session_id AND rr.run_epoch=o.run_epoch ORDER BY receipt_seq DESC LIMIT 1) latest ON true
 WHERE o.session_id=$1 AND o.command_id=$2`, sid, id).Scan(&raw)
	return raw, e
}
func (s *Store) VerifyClaim(ctx context.Context, c Claim) error {
	tx, e := s.DB.Begin(ctx)
	if e != nil {
		return e
	}
	defer tx.Rollback(ctx)
	r, e := s.current(ctx, tx, c.Command.SessionID, true, c.Command.CommandType == "STOP_SESSION")
	if e != nil {
		return e
	}
	if r.Epoch != c.Command.RunEpoch {
		return ErrFence
	}
	if r.Status != "ACTIVE" && c.Command.CommandType != "STOP_SESSION" && c.Command.CommandType != "BEGIN_RUN" {
		return ErrSealed
	}
	var ok bool
	e = tx.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM v05_outbox WHERE valid_until>clock_timestamp() AND command_id=$1 AND delivery_state='CLAIMED' AND lease_owner=$2 AND lease_token=$3 AND lease_expires_at>clock_timestamp())`, c.Command.CommandID, c.Owner, c.Token).Scan(&ok)
	if e != nil {
		return e
	}
	if !ok {
		return ErrFence
	}
	return nil
}
func commandDeadline(ctx context.Context) time.Time {
	if t, ok := ctx.Deadline(); ok {
		return t
	}
	return time.Date(9999, 1, 1, 0, 0, 0, 0, time.UTC)
}

// Barrier retires all earlier media admission without incrementing the run incarnation.
func (s *Store) Barrier(ctx context.Context, tx pgx.Tx, c Command) error {
	_, e := tx.Exec(ctx, `UPDATE v05_session_runs SET control_barrier_seq=$3 WHERE session_id=$1 AND run_epoch=$2`, c.SessionID, c.RunEpoch, c.CommandSeq)
	if e != nil {
		return e
	}
	_, e = tx.Exec(ctx, `UPDATE utterances u SET status='CANCELLED',completed_at=clock_timestamp(),updated_at=clock_timestamp() FROM v05_outbox o
 WHERE o.session_id=$1 AND o.run_epoch=$2 AND o.command_seq<$3 AND o.utterance_id=u.id AND u.status='QUEUED'
 AND NOT EXISTS(SELECT 1 FROM v05_inbox i WHERE i.command_id=o.command_id AND i.execution_state IN ('STARTED','UNKNOWN','TERMINAL'))`, c.SessionID, c.RunEpoch, c.CommandSeq)
	if e != nil {
		return e
	}
	_, e = tx.Exec(ctx, `UPDATE v05_inbox SET execution_state='CANCELLED' WHERE session_id=$1 AND run_epoch=$2 AND command_seq<$3 AND execution_state='ACCEPTED'`, c.SessionID, c.RunEpoch, c.CommandSeq)
	if e != nil {
		return e
	}
	_, e = tx.Exec(ctx, `UPDATE v05_outbox SET delivery_state=CASE WHEN delivery_state='CLAIMED' AND EXISTS(SELECT 1 FROM v05_inbox i WHERE i.command_id=v05_outbox.command_id AND i.execution_state IN ('STARTED','UNKNOWN')) THEN 'UNKNOWN' ELSE 'CANCELLED' END,last_error_code='CONTROL_BARRIER'
 WHERE session_id=$1 AND run_epoch=$2 AND command_seq<$3 AND command_type<>'STOP_SESSION' AND delivery_state IN ('PENDING','CLAIMED')`, c.SessionID, c.RunEpoch, c.CommandSeq)
	return e
}

func (s *Store) CleanupRun(ctx context.Context, tx pgx.Tx, sid string) (Run, error) {
	r, e := s.current(ctx, tx, sid, false, true)
	if e != nil && e != ErrFence {
		return r, e
	}
	if e == ErrFence {
		_, e = tx.Exec(ctx, `UPDATE v05_recovery_leases SET owner_id=$2,lease_token=lease_token+1,expires_at=clock_timestamp()+interval '10 seconds' WHERE session_id=$1 AND expires_at<=clock_timestamp()`, sid, s.Owner)
		if e != nil {
			return r, e
		}
		r.Token++
		r.RemainingMS = 10000
		_, e = tx.Exec(ctx, `UPDATE v05_session_runs SET owner_id=$3,lease_token=$4 WHERE session_id=$1 AND run_epoch=$2`, sid, r.Epoch, s.Owner, r.Token)
		if e != nil {
			return r, e
		}
	}
	return r, nil
}
