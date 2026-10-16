package durablelive

import (
	"context"
	"errors"
	"github.com/jackc/pgx/v5"
	"time"
)

func (s *Store) resume(ctx context.Context, tx pgx.Tx, p Principal, r, q Object) (Object, error) {
	if e := notStopped(r); e != nil {
		return nil, e
	}
	if e := revision(r, q); e != nil {
		return nil, e
	}
	if num(q, "expectedPreviousEpoch") != num(r, "runEpoch") {
		return nil, fault("STALE_RUN_EPOCH")
	}
	if str(r, "status") != "CREATED" && str(r, "status") != "PAUSED" && str(r, "status") != "RECOVERING" {
		return nil, fault("STATE_CONFLICT")
	}
	if len(s.RequiredSinks) == 0 || s.LeaseTTL < time.Second || s.LeaseTTL > 15*time.Second {
		return nil, fault("INVALID_ARGUMENT")
	}
	var live bool
	e := tx.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM dl05_run_leases WHERE run_id=$1 AND lease_expires_at>clock_timestamp() AND phase<>'SEALED')`, r["runId"]).Scan(&live)
	if e != nil {
		return nil, e
	}
	if live {
		return nil, fault("LEASE_LOST")
	}
	epoch := num(r, "runEpoch") + 1
	if epoch > maxInteger {
		return nil, fault("STALE_RUN_EPOCH")
	}
	next := "RECOVERING"
	if str(r, "status") == "CREATED" {
		next = "PREPARING"
	}
	_, e = tx.Exec(ctx, `UPDATE dl05_run_terms SET phase='SEALED',sealed_at=clock_timestamp() WHERE run_id=$1 AND phase<>'SEALED'`, r["runId"])
	if e != nil {
		return nil, e
	}
	_, e = tx.Exec(ctx, `UPDATE dl05_output_permits SET revoked_at=COALESCE(revoked_at,clock_timestamp()) WHERE run_id=$1`, r["runId"])
	if e != nil {
		return nil, e
	}
	_, e = tx.Exec(ctx, `INSERT INTO dl05_run_terms(tenant_id,owner_id,run_id,run_epoch,lease_owner,phase,previous_epoch,required_sinks) VALUES($1,$2,$3,$4,$5,'PENDING_INSTALL',$6,$7)`, p.TenantID, p.OwnerID, r["runId"], epoch, p.InstanceID, num(r, "runEpoch"), s.RequiredSinks)
	if e != nil {
		return nil, e
	}
	_, e = tx.Exec(ctx, `INSERT INTO dl05_run_leases(tenant_id,owner_id,run_id,lease_owner,lease_expires_at,fencing_token,run_epoch,lease_version,phase) VALUES($1,$2,$3,$4,clock_timestamp()+$5::interval,$6,$6,1,'PENDING_INSTALL') ON CONFLICT(run_id) DO UPDATE SET lease_owner=excluded.lease_owner,lease_expires_at=excluded.lease_expires_at,fencing_token=excluded.fencing_token,run_epoch=excluded.run_epoch,lease_version=dl05_run_leases.lease_version+1,phase='PENDING_INSTALL'`, p.TenantID, p.OwnerID, r["runId"], p.InstanceID, s.LeaseTTL.String(), epoch)
	if e != nil {
		return nil, e
	}
	_, e = tx.Exec(ctx, `UPDATE dl05_runs SET run_epoch=$2,status=$3,desired_state='LIVE',state_revision=state_revision+1,updated_at=clock_timestamp() WHERE run_id=$1`, r["runId"], epoch, next)
	if e != nil {
		return nil, e
	}
	_, e = tx.Exec(ctx, `INSERT INTO dl05_decisions(tenant_id,owner_id,run_id,decision_id,operator_id,action,reason,expected_revision,document) VALUES($1,$2,$3,$4,$5,'RESUME','EXPLICIT_RESUME',$6,$7)`, p.TenantID, p.OwnerID, r["runId"], q["decisionId"], p.InstanceID, num(r, "revision"), q)
	if e != nil {
		return nil, e
	}
	run, e := loadRun(ctx, tx, str(r, "runId"), false)
	if e != nil {
		return nil, e
	}
	l, e := loadLease(ctx, tx, str(r, "runId"))
	return Object{"requestId": q["requestId"], "run": run, "lease": l}, e
}

// RenewLease is an authenticated CONTROL owner operation, not a Runtime RPC.
func (s *Store) RenewLease(ctx context.Context, p Principal, runID string, epoch, version int64) (RunLease, error) {
	var out RunLease
	if p.Role != "CONTROL" {
		return out, fault("FORBIDDEN")
	}
	tx, e := s.begin(ctx)
	if e != nil {
		return out, e
	}
	defer tx.Rollback(context.Background())
	r, e := loadRun(ctx, tx, runID, true)
	if e != nil {
		return out, e
	}
	if e = authorize(p, r); e != nil {
		return out, e
	}
	if e = owner(ctx, tx, p, "room", str(r, "roomId")); e != nil {
		return out, e
	}
	if e = notStopped(r); e != nil {
		return out, e
	}
	tag, e := tx.Exec(ctx, `UPDATE dl05_run_leases SET lease_expires_at=clock_timestamp()+$5::interval,lease_version=lease_version+1,updated_at=clock_timestamp() WHERE run_id=$1 AND run_epoch=$2 AND lease_version=$3 AND lease_owner=$4 AND phase IN ('ACTIVE','PENDING_INSTALL') AND lease_expires_at>clock_timestamp()`, runID, epoch, version, p.InstanceID, s.LeaseTTL.String())
	if e != nil {
		return out, e
	}
	if tag.RowsAffected() != 1 {
		return out, fault("LEASE_LOST")
	}
	l, e := loadLease(ctx, tx, runID)
	if e != nil {
		return out, e
	}
	b, e := Canonical(l)
	if e != nil {
		return out, e
	}
	if e = decodeInto(b, &out); e != nil {
		return out, e
	}
	return out, tx.Commit(ctx)
}

// SessionAdmission is an in-process integration seam, not a new wire protocol.
// Caller obtains these facts through the existing Provider Binding / Worker ACL.
// A missing/unfresh Worker proof fails closed; no credential snapshots are copied.
type SessionAdmission struct {
	SessionID           string
	ProducerIncarnation string
	WorkerReady         bool
	CheckedAt           time.Time
}

func (s *Store) AttachSession(ctx context.Context, p Principal, runID string, epoch int64, a SessionAdmission) error {
	if p.Role != "CONTROL" || !a.WorkerReady || time.Since(a.CheckedAt) > 2*time.Second || a.CheckedAt.After(time.Now()) || a.ProducerIncarnation == "" {
		return fault("DEPENDENCY_UNAVAILABLE")
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
	if epoch != num(r, "runEpoch") {
		return fault("STALE_RUN_EPOCH")
	}
	if _, e = s.validLease(ctx, tx, p, r, "PENDING_INSTALL", true); e != nil {
		return e
	}
	// Serialize adoption with legacy Utterance FK admission. The deferred DB
	// trigger rejects a legacy insert that commits after this mode switch.
	if _, e = tx.Exec(ctx, `SELECT id FROM live_sessions WHERE id=$1 FOR UPDATE`, a.SessionID); e != nil {
		return e
	}
	var legacyBusy bool
	e = tx.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM utterances u WHERE session_id=$1 AND status NOT IN ('COMPLETED','INTERRUPTED','FAILED','CANCELLED') AND NOT EXISTS(SELECT 1 FROM dl05_attempts a WHERE a.utterance_id=u.id))`, a.SessionID).Scan(&legacyBusy)
	if e != nil {
		return e
	}
	if legacyBusy {
		return fault("STATE_CONFLICT")
	}
	r["currentSessionId"] = a.SessionID
	if e = s.validateSession(ctx, tx, p, r); e != nil {
		return e
	}
	var bound string
	e = tx.QueryRow(ctx, `SELECT COALESCE(producer_incarnation,'') FROM dl05_run_terms WHERE run_id=$1 AND run_epoch=$2`, runID, epoch).Scan(&bound)
	if e != nil {
		return e
	}
	if bound != "" && bound != a.ProducerIncarnation {
		return fault("COMMAND_CONFLICT")
	}
	var binding string
	e = tx.QueryRow(ctx, `SELECT binding_id FROM session_provider_bindings WHERE session_id=$1`, a.SessionID).Scan(&binding)
	if e != nil {
		return e
	}
	_, e = tx.Exec(ctx, `INSERT INTO dl05_run_sessions(tenant_id,owner_id,run_id,run_session_id,session_id,binding_id,introduced_epoch) VALUES($1,$2,$3,$4,$5,$6,$7) ON CONFLICT(session_id) DO NOTHING`, p.TenantID, p.OwnerID, runID, freshID("rs"), a.SessionID, binding, epoch)
	if e != nil {
		return e
	}
	var same bool
	e = tx.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM dl05_run_sessions WHERE run_id=$1 AND session_id=$2 AND tenant_id=$3 AND owner_id=$4)`, runID, a.SessionID, p.TenantID, p.OwnerID).Scan(&same)
	if e != nil {
		return e
	}
	if !same {
		return fault("FORBIDDEN")
	}
	_, e = tx.Exec(ctx, `UPDATE dl05_run_sessions SET retired_at=COALESCE(retired_at,clock_timestamp()) WHERE run_id=$1 AND session_id<>$2`, runID, a.SessionID)
	if e != nil {
		return e
	}
	_, e = tx.Exec(ctx, `UPDATE dl05_run_terms SET producer_incarnation=$3 WHERE run_id=$1 AND run_epoch=$2`, runID, epoch, a.ProducerIncarnation)
	if e != nil {
		return e
	}
	_, e = tx.Exec(ctx, `UPDATE dl05_runs SET current_session_id=$2,state_revision=state_revision+1,updated_at=clock_timestamp() WHERE run_id=$1`, runID, a.SessionID)
	if e != nil {
		return e
	}
	return tx.Commit(ctx)
}
func (s *Store) outputFence(ctx context.Context, tx pgx.Tx, p Principal, r, q Object) (Object, error) {
	if e := checkEpoch(r, q); e != nil {
		return nil, e
	}
	if e := revision(r, q); e != nil {
		return nil, e
	}
	if p.InstanceID != str(q, "guardianId") {
		return nil, fault("FORBIDDEN")
	}
	var previous int64
	e := tx.QueryRow(ctx, `SELECT previous_epoch FROM dl05_run_terms WHERE run_id=$1 AND run_epoch=$2`, r["runId"], q["runEpoch"]).Scan(&previous)
	if e != nil {
		return nil, e
	}
	if previous != num(q, "retiredEpoch") && num(q, "retiredEpoch") != num(r, "runEpoch") {
		return nil, fault("STALE_RUN_EPOCH")
	}
	var oldRun, guardian string
	var version int64
	e = tx.QueryRow(ctx, `SELECT COALESCE(active_run_id,''),guardian_id,output_binding_version FROM dl05_room_outputs WHERE room_id=$1`, r["roomId"]).Scan(&oldRun, &guardian, &version)
	if e != nil && !errors.Is(e, pgx.ErrNoRows) {
		return nil, e
	}
	if guardian != "" && guardian != p.InstanceID {
		return nil, fault("OUTPUT_FENCE_UNPROVEN")
	}
	if oldRun != "" && oldRun != str(r, "runId") {
		var fenced bool
		e = tx.QueryRow(ctx, `SELECT NOT EXISTS(SELECT 1 FROM dl05_run_sessions WHERE run_id=$1 AND output_fenced_at IS NULL) AND EXISTS(SELECT 1 FROM dl05_runs WHERE run_id=$1 AND status IN ('STOPPED','FAILED'))`, oldRun).Scan(&fenced)
		if e != nil {
			return nil, e
		}
		if !fenced {
			return nil, fault("OUTPUT_FENCE_UNPROVEN")
		}
	}
	// OUTPUT_GUARDIAN asserts that all old sink connections are closed. Ordinary
	// Runtime tokens cannot manufacture this independent proof.
	version++
	_, e = tx.Exec(ctx, `UPDATE dl05_output_permits SET revoked_at=COALESCE(revoked_at,clock_timestamp()) WHERE room_id=$1`, r["roomId"])
	if e != nil {
		return nil, e
	}
	_, e = tx.Exec(ctx, `INSERT INTO dl05_output_bindings(room_id,output_binding_version,tenant_id,owner_id,run_id,guardian_id,fence_proof_ref) VALUES($1,$2,$3,$4,$5,$6,$7)`, r["roomId"], version, p.TenantID, p.OwnerID, r["runId"], p.InstanceID, q["evidenceRef"])
	if e != nil {
		return nil, e
	}
	_, e = tx.Exec(ctx, `INSERT INTO dl05_room_outputs(room_id,tenant_id,owner_id,active_run_id,output_binding_version,guardian_id,expires_at,fence_proof_ref) VALUES($1,$2,$3,$4,$5,$6,clock_timestamp(),$7) ON CONFLICT(room_id) DO UPDATE SET active_run_id=excluded.active_run_id,output_binding_version=excluded.output_binding_version,guardian_id=excluded.guardian_id,fence_proof_ref=excluded.fence_proof_ref,expires_at=excluded.expires_at`, r["roomId"], p.TenantID, p.OwnerID, r["runId"], version, p.InstanceID, q["evidenceRef"])
	if e != nil {
		return nil, e
	}
	_, e = tx.Exec(ctx, `UPDATE dl05_run_sessions SET output_fenced_at=clock_timestamp() WHERE run_id=$1 AND introduced_epoch<=$2`, r["runId"], q["retiredEpoch"])
	if e != nil {
		return nil, e
	}
	receipt := freshID("fence")
	_, e = tx.Exec(ctx, `UPDATE dl05_run_terms SET output_fence_proof=$3,guardian_id=$4,fence_receipt_id=$5 WHERE run_id=$1 AND run_epoch=$2`, r["runId"], q["runEpoch"], q["evidenceRef"], p.InstanceID, receipt)
	if e != nil {
		return nil, e
	}
	if e = bump(ctx, tx, str(r, "runId")); e != nil {
		return nil, e
	}
	return Object{"requestId": q["requestId"], "runRevision": num(r, "revision") + 1, "fenceReceiptId": receipt}, nil
}
func (s *Store) runFence(ctx context.Context, tx pgx.Tx, p Principal, r, q Object) (Object, error) {
	if e := checkEpoch(r, q); e != nil {
		return nil, e
	}
	if e := notStopped(r); e != nil {
		return nil, e
	}
	l, e := loadLease(ctx, tx, str(r, "runId"))
	if e != nil {
		return nil, e
	}
	phase := str(l, "phase")
	if phase != "PENDING_INSTALL" && phase != "ACTIVE" {
		return nil, fault("LEASE_LOST")
	}
	if _, e = s.validLease(ctx, tx, p, r, phase, false); e != nil {
		return nil, e
	}
	if str(r, "currentSessionId") != str(q, "sessionId") {
		return nil, fault("FORBIDDEN")
	}
	if e = s.validateSession(ctx, tx, p, r); e != nil {
		return nil, e
	}
	var producer, proof, receipt string
	e = tx.QueryRow(ctx, `SELECT COALESCE(producer_incarnation,''),COALESCE(output_fence_proof,''),COALESCE(fence_receipt_id,'') FROM dl05_run_terms WHERE run_id=$1 AND run_epoch=$2`, r["runId"], q["runEpoch"]).Scan(&producer, &proof, &receipt)
	if e != nil {
		return nil, e
	}
	if producer != p.InstanceID || producer != str(q, "producerIncarnation") {
		return nil, fault("FORBIDDEN")
	}
	if proof == "" || proof != str(q, "guardianProofRef") || receipt != str(q, "fenceReceiptId") {
		return nil, fault("OUTPUT_FENCE_UNPROVEN")
	}
	var unresolved bool
	e = tx.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM dl05_attempts a JOIN dl05_run_sessions rs ON rs.session_id=a.session_id WHERE a.run_id=$1 AND a.run_epoch<$2 AND a.last_checkpoint NOT IN ('COMPLETED','INTERRUPTED') )`, r["runId"], q["runEpoch"]).Scan(&unresolved)
	if e != nil {
		return nil, e
	}
	if unresolved {
		return nil, fault("RECOVERY_UNKNOWN")
	}
	if phase == "PENDING_INSTALL" {
		_, e = tx.Exec(ctx, `UPDATE dl05_run_terms SET phase='ACTIVE',activated_at=clock_timestamp() WHERE run_id=$1 AND run_epoch=$2`, r["runId"], q["runEpoch"])
		if e != nil {
			return nil, e
		}
		_, e = tx.Exec(ctx, `UPDATE dl05_run_leases SET phase='ACTIVE' WHERE run_id=$1`, r["runId"])
		if e != nil {
			return nil, e
		}
		_, e = tx.Exec(ctx, `UPDATE dl05_runs SET status='LIVE',started_at=COALESCE(started_at,clock_timestamp()),state_revision=state_revision+1,updated_at=clock_timestamp() WHERE run_id=$1`, r["runId"])
		if e != nil {
			return nil, e
		}
	}
	run, e := loadRun(ctx, tx, str(r, "runId"), false)
	if e != nil {
		return nil, e
	}
	return Object{"requestId": q["requestId"], "runRevision": run["revision"], "runEpoch": q["runEpoch"], "phase": "ACTIVE"}, nil
}
func (s *Store) permit(ctx context.Context, tx pgx.Tx, p Principal, r, q Object) (Object, error) {
	if e := checkEpoch(r, q); e != nil {
		return nil, e
	}
	l, e := s.validLease(ctx, tx, p, r, "ACTIVE", false)
	if e != nil {
		return nil, e
	}
	if str(r, "currentSessionId") != str(q, "sessionId") {
		return nil, fault("FORBIDDEN")
	}
	if e = s.validateSession(ctx, tx, p, r); e != nil {
		return nil, e
	}
	var producer, guardian, proof string
	e = tx.QueryRow(ctx, `SELECT COALESCE(producer_incarnation,''),COALESCE(guardian_id,''),COALESCE(output_fence_proof,'') FROM dl05_run_terms WHERE run_id=$1 AND run_epoch=$2`, r["runId"], q["runEpoch"]).Scan(&producer, &guardian, &proof)
	if e != nil {
		return nil, e
	}
	if producer != p.InstanceID || guardian != str(q, "guardianId") || proof == "" {
		return nil, fault("OUTPUT_FENCE_UNPROVEN")
	}
	var binding int64
	e = tx.QueryRow(ctx, `SELECT output_binding_version FROM dl05_room_outputs WHERE room_id=$1 AND active_run_id=$2 AND guardian_id=$3 AND fence_proof_ref=$4`, r["roomId"], r["runId"], guardian, proof).Scan(&binding)
	if e != nil {
		return nil, fault("OUTPUT_FENCE_UNPROVEN")
	}
	var issued, expires time.Time
	e = tx.QueryRow(ctx, `WITH tick AS MATERIALIZED(SELECT clock_timestamp() t) SELECT tick.t,LEAST(tick.t+interval '1 second',l.lease_expires_at) FROM dl05_run_leases l CROSS JOIN tick WHERE l.run_id=$1`, r["runId"]).Scan(&issued, &expires)
	if e != nil {
		return nil, e
	}
	ttl := expires.Sub(issued).Milliseconds()
	if ttl < 1 {
		return nil, fault("LEASE_LOST")
	}
	if ttl > 1000 {
		ttl = 1000
	}
	// A newly issued output right invalidates any earlier Session barrier.
	if _, e = tx.Exec(ctx, `UPDATE dl05_run_sessions SET output_fenced_at=NULL WHERE run_id=$1 AND session_id=$2`, r["runId"], q["sessionId"]); e != nil {
		return nil, e
	}
	id := freshID("permit")
	_, e = tx.Exec(ctx, `INSERT INTO dl05_output_permits(tenant_id,owner_id,run_id,session_id,run_epoch,lease_version,permit_id,producer_incarnation,guardian_id,issued_at,expires_at,fence_proof_ref,room_id,output_binding_version) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)`, p.TenantID, p.OwnerID, r["runId"], q["sessionId"], q["runEpoch"], l["leaseVersion"], id, p.InstanceID, guardian, issued, expires, proof, r["roomId"], binding)
	if e != nil {
		return nil, e
	}
	return Object{"requestId": q["requestId"], "permitId": id, "runEpoch": q["runEpoch"], "leaseVersion": l["leaseVersion"], "ttlMs": ttl, "issuedAt": stamp(issued), "expiresAt": stamp(expires), "roomId": r["roomId"], "outputBindingVersion": binding, "sessionId": q["sessionId"], "producerIncarnation": p.InstanceID}, nil
}

// PrepareFence persists the allocated management command after an independent
// guardian proof has been recorded. It never installs or invents a future epoch.
func (s *Store) PrepareFence(ctx context.Context, p Principal, runID, key string) (DispatchIntent, error) {
	var out DispatchIntent
	if p.Role != "CONTROL" {
		return out, fault("FORBIDDEN")
	}
	tx, e := s.begin(ctx)
	if e != nil {
		return out, e
	}
	defer tx.Rollback(context.Background())
	r, e := loadRun(ctx, tx, runID, true)
	if e != nil {
		return out, e
	}
	if e = authorize(p, r); e != nil {
		return out, e
	}
	if e = owner(ctx, tx, p, "room", str(r, "roomId")); e != nil {
		return out, e
	}
	l, e := s.validLease(ctx, tx, p, r, "PENDING_INSTALL", true)
	if e != nil {
		return out, e
	}
	existing, e := jsonRow(tx.QueryRow(ctx, "SELECT "+intentJSON+` FROM dl05_outbox WHERE run_id=$1 AND operation='INSTALL_FENCE' AND idempotency_key=$2`, runID, key))
	if e == nil {
		b, _ := Canonical(existing)
		return out, decodeInto(b, &out)
	}
	if !errors.Is(e, pgx.ErrNoRows) {
		return out, e
	}
	var producer, proof string
	var previous int64
	e = tx.QueryRow(ctx, `SELECT COALESCE(producer_incarnation,''),COALESCE(output_fence_proof,''),previous_epoch FROM dl05_run_terms WHERE run_id=$1 AND run_epoch=$2`, runID, num(r, "runEpoch")).Scan(&producer, &proof, &previous)
	if e != nil {
		return out, e
	}
	if producer == "" || proof == "" || str(r, "currentSessionId") == "" {
		return out, fault("OUTPUT_FENCE_UNPROVEN")
	}
	cmd := Object{"schemaVersion": "0.5", "contractRevision": RevisionName, "requestId": freshID("req"), "tenantId": p.TenantID, "ownerId": p.OwnerID, "runId": runID, "expectedRevision": r["revision"], "sessionId": r["currentSessionId"], "runEpoch": r["runEpoch"], "expectedPreviousEpoch": previous, "leaseVersion": l["leaseVersion"], "producerIncarnation": producer, "guardianProofRef": proof, "idempotencyKey": key, "commandId": freshID("cmd"), "intentId": freshID("intent"), "traceId": freshID("trace"), "createdAt": stamp(time.Now()), "operation": "INSTALL_FENCE"}
	cmd["requestHash"] = commandHash(cmd)
	if e = validate("FenceInstallRequest", cmd); e != nil {
		return out, e
	}
	if e = insertIntent(ctx, tx, p, r, cmd); e != nil {
		return out, e
	}
	in, e := loadIntent(ctx, tx, str(cmd, "intentId"))
	if e != nil {
		return out, e
	}
	b, _ := Canonical(in)
	if e = decodeInto(b, &out); e != nil {
		return out, e
	}
	return out, tx.Commit(ctx)
}
