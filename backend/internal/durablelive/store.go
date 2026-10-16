// Package durablelive implements the durable-live-1 repository and command journal.
// It never invokes LLM/TTS/GPU/HTTP while a PostgreSQL transaction is open.
package durablelive

import (
	"context"
	"encoding/json"
	"errors"
	"time"

	"astralive/backend/internal/ids"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
	"github.com/jackc/pgx/v5/pgxpool"
)

type Principal struct {
	Role       string
	TenantID   string
	OwnerID    string
	InstanceID string // authenticated service instance, never derived from body
}
type Store struct {
	DB            *pgxpool.Pool
	LeaseTTL      time.Duration
	RequiredSinks []string
	Facts         FactVerifier
}

func New(db *pgxpool.Pool, sinks []string) *Store {
	return &Store{DB: db, LeaseTTL: 15 * time.Second, RequiredSinks: append([]string(nil), sinks...)}
}

type Operation struct {
	OperationID    string   `json:"operationId"`
	Method         string   `json:"method"`
	Path           string   `json:"path"`
	Target         string   `json:"target"`
	Roles          []string `json:"roles"`
	RequestSchema  string   `json:"requestSchema"`
	ResponseSchema string   `json:"responseSchema"`
	SuccessStatus  int      `json:"successStatus"`
}

func Operations() []Operation {
	b, _ := specs.ReadFile("spec/protocol.json")
	var p struct {
		Operations []Operation `json:"operations"`
	}
	_ = json.Unmarshal(b, &p)
	return p.Operations
}
func operation(name string) (Operation, error) {
	for _, o := range Operations() {
		if o.OperationID == name {
			return o, nil
		}
	}
	return Operation{}, fault("RESOURCE_NOT_FOUND")
}
func (s *Store) begin(ctx context.Context) (pgx.Tx, error) {
	tx, e := s.DB.Begin(ctx)
	if e != nil {
		return nil, e
	}
	_, e = tx.Exec(ctx, "SET LOCAL lock_timeout='750ms'; SET LOCAL statement_timeout='3s'")
	if e != nil {
		_ = tx.Rollback(ctx)
		return nil, e
	}
	return tx, nil
}
func jsonRow(row pgx.Row) (Object, error) {
	var b []byte
	if e := row.Scan(&b); e != nil {
		return nil, e
	}
	return Decode(b)
}
func normErr(e error) error {
	var pe *pgconn.PgError
	if errors.As(e, &pe) {
		switch pe.Code {
		case "23505":
			return fault("COMMAND_CONFLICT")
		case "23503", "23514":
			return fault("INVALID_ARGUMENT")
		case "55P03":
			return fault("OVERLOADED")
		}
	}
	if errors.Is(e, pgx.ErrNoRows) {
		return fault("RESOURCE_NOT_FOUND")
	}
	return e
}

const runJSON = `jsonb_build_object('tenantId',tenant_id,'ownerId',owner_id,'runId',run_id,'roomId',room_id,'status',status,'runEpoch',run_epoch,'currentSessionId',current_session_id,'currentPlanId',current_plan_id,'startedAt',dl05_stamp(started_at),'updatedAt',dl05_stamp(updated_at),'endedAt',dl05_stamp(ended_at),'desiredState',desired_state,'recoveryPolicy',recovery_policy,'revision',state_revision,'stopRevision',stop_revision)`

func loadRun(ctx context.Context, tx pgx.Tx, id string, lock bool) (Object, error) {
	q := "SELECT " + runJSON + " FROM dl05_runs WHERE run_id=$1"
	if lock {
		q += " FOR UPDATE"
	}
	return jsonRow(tx.QueryRow(ctx, q, id))
}
func loadTurn(ctx context.Context, tx pgx.Tx, id string) (Object, error) {
	return jsonRow(tx.QueryRow(ctx, `SELECT document || jsonb_build_object('state',state,'revision',revision,'startedAt',dl05_stamp(started_at),'finishedAt',dl05_stamp(finished_at)) FROM dl05_turns WHERE turn_id=$1`, id))
}
func loadAttempt(ctx context.Context, tx pgx.Tx, id string) (Object, error) {
	return jsonRow(tx.QueryRow(ctx, `SELECT document || jsonb_build_object('lastCheckpoint',last_checkpoint,'executorIncarnation',executor_incarnation,'answerTextHash',answer_text_hash,'updatedAt',dl05_stamp(updated_at)) FROM dl05_attempts WHERE attempt_id=$1`, id))
}
func loadSlot(ctx context.Context, tx pgx.Tx, id string) (Object, error) {
	return jsonRow(tx.QueryRow(ctx, `SELECT jsonb_build_object('activeAttemptId',active_attempt_id,'boundaryCheckpointId',boundary_checkpoint_id,'slotVersion',slot_version) FROM dl05_run_slots WHERE run_id=$1`, id))
}

const intentJSON = `jsonb_build_object('tenantId',tenant_id,'ownerId',owner_id,'runId',run_id,'intentId',intent_id,'attemptId',attempt_id,'turnId',turn_id,'sessionId',session_id,'utteranceId',utterance_id,'commandId',command_id,'idempotencyKey',idempotency_key,'runEpoch',run_epoch,'operation',operation,'requestHash',request_hash,'status',status,'nextAttemptAt',dl05_stamp(next_attempt_at),'claimedBy',claimed_by,'leaseExpiresAt',dl05_stamp(lease_expires_at),'claimVersion',claim_version,'sendStartedAt',dl05_stamp(send_started_at),'createdAt',dl05_stamp(created_at),'updatedAt',dl05_stamp(updated_at))`

func loadIntent(ctx context.Context, tx pgx.Tx, id string) (Object, error) {
	return jsonRow(tx.QueryRow(ctx, "SELECT "+intentJSON+" FROM dl05_outbox WHERE intent_id=$1", id))
}
func loadLease(ctx context.Context, tx pgx.Tx, id string) (Object, error) {
	return jsonRow(tx.QueryRow(ctx, `SELECT jsonb_build_object('tenantId',tenant_id,'ownerId',owner_id,'runId',run_id,'leaseOwner',lease_owner,'leaseExpiresAt',dl05_stamp(lease_expires_at),'fencingToken',fencing_token,'runEpoch',run_epoch,'leaseVersion',lease_version,'phase',phase) FROM dl05_run_leases WHERE run_id=$1`, id))
}
func authorize(p Principal, q Object) error {
	if p.InstanceID == "" || p.TenantID == "" || p.OwnerID == "" {
		return fault("UNAUTHENTICATED")
	}
	if p.TenantID != str(q, "tenantId") || p.OwnerID != str(q, "ownerId") {
		return fault("FORBIDDEN")
	}
	return nil
}
func owner(ctx context.Context, tx pgx.Tx, p Principal, kind, id string) error {
	var ok bool
	e := tx.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM resource_owners WHERE kind=$1 AND resource_id=$2 AND tenant_id=$3 AND user_id=$4)`, kind, id, p.TenantID, p.OwnerID).Scan(&ok)
	if e != nil {
		return e
	}
	if !ok {
		return fault("FORBIDDEN")
	}
	return nil
}
func revision(r, q Object) error {
	if num(r, "revision") != num(q, "expectedRevision") {
		return fault("STATE_CONFLICT")
	}
	return nil
}
func notStopped(r Object) error {
	if num(r, "stopRevision") > 0 || str(r, "desiredState") == "STOPPED" || str(r, "status") == "STOPPED" || str(r, "status") == "FAILED" {
		return fault("RUN_STOPPED")
	}
	return nil
}
func checkEpoch(r, q Object) error {
	if num(r, "runEpoch") != num(q, "runEpoch") {
		return fault("STALE_RUN_EPOCH")
	}
	return nil
}
func bump(ctx context.Context, tx pgx.Tx, id string) error {
	_, e := tx.Exec(ctx, `UPDATE dl05_runs SET state_revision=state_revision+1,updated_at=clock_timestamp() WHERE run_id=$1`, id)
	return e
}
func requestHash(q Object) string {
	m := Object{}
	for k, v := range q {
		if k != "requestId" && k != "expectedRevision" {
			m[k] = v
		}
	}
	return hash(m)
}

// Call is the schema-validated shared seam. Generated typed methods use it too.
// Every successful response is validated against the same frozen response schema.
func (s *Store) Call(ctx context.Context, p Principal, name string, raw []byte) (Object, error) {
	op, e := operation(name)
	if e != nil || op.Target != "BACKEND" {
		return nil, fault("RESOURCE_NOT_FOUND")
	}
	allowed := false
	for _, r := range op.Roles {
		allowed = allowed || r == p.Role
	}
	if !allowed {
		return nil, fault("FORBIDDEN")
	}
	q, e := Decode(raw)
	if e != nil {
		return nil, e
	}
	if e = validate(name+"Request", q); e != nil {
		return nil, e
	}
	if e = authorize(p, q); e != nil {
		return nil, e
	}
	if p.Role == "RUNTIME_JOURNAL" && str(q, "producerIncarnation") != "" && str(q, "producerIncarnation") != p.InstanceID {
		return nil, fault("FORBIDDEN")
	}
	if p.Role == "OUTPUT_GUARDIAN" && str(q, "guardianId") != p.InstanceID {
		return nil, fault("FORBIDDEN")
	}
	ctx, e = s.preflightFacts(ctx, p, name, q)
	if e != nil {
		return nil, e
	}
	tx, e := s.begin(ctx)
	if e != nil {
		return nil, e
	}
	defer tx.Rollback(context.Background())
	var r Object
	if name == "CreateBroadcastRun" {
		if e = owner(ctx, tx, p, "room", str(q, "roomId")); e != nil {
			return nil, e
		}
		if _, e = tx.Exec(ctx, `SELECT pg_advisory_xact_lock(hashtextextended($1,5))`, str(q, "runId")); e != nil {
			return nil, e
		}
	}
	if name == "ConfirmOutputFence" {
		peek, err := loadRun(ctx, tx, str(q, "runId"), false)
		if err != nil {
			return nil, normErr(err)
		}
		if err = authorize(p, peek); err != nil {
			return nil, err
		}
		// Room-before-run order also serializes a previously absent Room output.
		if _, e = tx.Exec(ctx, `SELECT pg_advisory_xact_lock(hashtextextended($1,6))`, str(peek, "roomId")); e != nil {
			return nil, e
		}
		if _, e = tx.Exec(ctx, `SELECT room_id FROM dl05_room_outputs WHERE room_id=$1 FOR UPDATE`, peek["roomId"]); e != nil {
			return nil, e
		}
	}
	if name != "CreateBroadcastRun" {
		r, e = loadRun(ctx, tx, str(q, "runId"), true)
		if e != nil {
			return nil, normErr(e)
		}
		if e = authorize(p, r); e != nil {
			return nil, e
		}
		if e = owner(ctx, tx, p, "room", str(r, "roomId")); e != nil {
			return nil, e
		}
	}
	// Authorization is always performed before idempotent response lookup.
	key := str(q, "idempotencyKey")
	if key != "" {
		var h string
		var b []byte
		e = tx.QueryRow(ctx, `SELECT request_hash,response FROM dl05_requests WHERE run_id=$1 AND operation=$2 AND idempotency_key=$3`, str(q, "runId"), name, key).Scan(&h, &b)
		if e == nil {
			if h != requestHash(q) {
				return nil, fault("COMMAND_CONFLICT")
			}
			out, e := Decode(b)
			if e != nil {
				return nil, e
			}
			if _, ok := out["requestId"]; ok {
				out["requestId"] = q["requestId"]
			}
			return out, tx.Commit(ctx)
		}
		if !errors.Is(e, pgx.ErrNoRows) {
			return nil, e
		}
	}
	var out Object
	switch name {
	case "CreateBroadcastRun":
		out, e = s.create(ctx, tx, p, q)
	case "SaveContentPlan":
		out, e = s.savePlan(ctx, tx, p, r, q)
	case "AdmitTurn":
		out, e = s.admit(ctx, tx, p, r, q)
	case "ClaimNextTurn":
		out, e = s.claimTurn(ctx, tx, p, r, q)
	case "DispatchTurn":
		out, e = s.dispatchTurn(ctx, tx, p, r, q)
	case "ResumeBroadcastRun":
		out, e = s.resume(ctx, tx, p, r, q)
	case "StopBroadcastRun":
		out, e = s.stop(ctx, tx, p, r, q)
	case "RestoreContentPlan":
		out, e = s.restore(ctx, tx, p, r, q)
	case "YieldAtSegmentBoundary":
		out, e = s.yield(ctx, tx, p, r, q)
	case "JournalAccept":
		out, e = s.accept(ctx, tx, p, r, q)
	case "JournalStart":
		out, e = s.start(ctx, tx, p, r, q)
	case "QueryExecutionStatus":
		out, e = s.query(ctx, tx, p, r, q)
	case "AcquireOutputPermit":
		out, e = s.permit(ctx, tx, p, r, q)
	case "ConfirmOutputFence":
		out, e = s.outputFence(ctx, tx, p, r, q)
	case "ConfirmRunFence":
		out, e = s.runFence(ctx, tx, p, r, q)
	case "ConfirmCheckpoint":
		out, e = s.checkpoint(ctx, tx, p, r, q)
	case "MarkExecutionUnknown":
		out, e = s.markUnknown(ctx, tx, p, r, q)
	default:
		e = fault("RESOURCE_NOT_FOUND")
	}
	if e != nil {
		return nil, normErr(e)
	}
	if e = validate(name+"Response", out); e != nil {
		return nil, e
	}
	if key != "" {
		_, e = tx.Exec(ctx, `INSERT INTO dl05_requests(tenant_id,owner_id,run_id,operation,idempotency_key,request_hash,response) VALUES($1,$2,$3,$4,$5,$6,$7)`, p.TenantID, p.OwnerID, str(q, "runId"), name, key, requestHash(q), out)
		if e != nil {
			return nil, e
		}
	}
	if e = tx.Commit(ctx); e != nil {
		return nil, e
	}
	return out, nil
}
func baseResponse(q Object) Object { return Object{"requestId": q["requestId"]} }
func (s *Store) create(ctx context.Context, tx pgx.Tx, p Principal, q Object) (Object, error) {
	if e := owner(ctx, tx, p, "room", str(q, "roomId")); e != nil {
		return nil, e
	}
	// Concurrent create with same run ID is serialized even before its row exists.
	_, e := tx.Exec(ctx, `SELECT pg_advisory_xact_lock(hashtextextended($1,5))`, str(q, "runId"))
	if e != nil {
		return nil, e
	}
	var exists bool
	e = tx.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM dl05_runs WHERE run_id=$1)`, q["runId"]).Scan(&exists)
	if e != nil {
		return nil, e
	}
	if exists {
		return nil, fault("COMMAND_CONFLICT")
	}
	_, e = tx.Exec(ctx, `INSERT INTO dl05_runs(tenant_id,owner_id,run_id,room_id,status,desired_state,recovery_policy,run_epoch) VALUES($1,$2,$3,$4,'CREATED','LIVE',$5,0)`, p.TenantID, p.OwnerID, q["runId"], q["roomId"], q["recoveryPolicy"])
	if e != nil {
		return nil, e
	}
	_, e = tx.Exec(ctx, `INSERT INTO dl05_run_slots(tenant_id,owner_id,run_id) VALUES($1,$2,$3)`, p.TenantID, p.OwnerID, q["runId"])
	if e != nil {
		return nil, e
	}
	r, e := loadRun(ctx, tx, str(q, "runId"), false)
	return Object{"requestId": q["requestId"], "run": r}, e
}
func (s *Store) validLease(ctx context.Context, tx pgx.Tx, p Principal, r Object, phase string, requireOwner bool) (Object, error) {
	if e := notStopped(r); e != nil {
		return nil, e
	}
	l, e := loadLease(ctx, tx, str(r, "runId"))
	if e != nil {
		return nil, fault("LEASE_LOST")
	}
	var valid bool
	e = tx.QueryRow(ctx, `SELECT lease_expires_at>clock_timestamp() FROM dl05_run_leases WHERE run_id=$1`, r["runId"]).Scan(&valid)
	if e != nil {
		return nil, e
	}
	if !valid || str(l, "phase") != phase || num(l, "runEpoch") != num(r, "runEpoch") || (requireOwner && str(l, "leaseOwner") != p.InstanceID) {
		return nil, fault("LEASE_LOST")
	}
	return l, nil
}
func (s *Store) validateSession(ctx context.Context, tx pgx.Tx, p Principal, r Object) error {
	sid := str(r, "currentSessionId")
	if sid == "" {
		return fault("DEPENDENCY_UNAVAILABLE")
	}
	if e := owner(ctx, tx, p, "session", sid); e != nil {
		return e
	}
	var ok bool
	e := tx.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM live_sessions s JOIN session_provider_bindings b ON b.session_id=s.id JOIN live_rooms ro ON ro.id=s.room_id WHERE s.id=$1 AND s.room_id=$2 AND s.status IN ('LIVE','DEGRADED') AND b.tenant_id=$3 AND b.user_id=$4 AND b.released_at IS NULL AND b.expires_at>clock_timestamp() AND (ro.active_product_id IS NOT DISTINCT FROM NULLIF(b.room_snapshot->>'activeProductId','')))`, sid, r["roomId"], p.TenantID, p.OwnerID).Scan(&ok)
	if e != nil {
		return e
	}
	if !ok {
		return fault("DEPENDENCY_UNAVAILABLE")
	}
	return nil
}
func freshID(prefix string) string { return ids.New(prefix) }
