package authority

import (
	"context"
	"crypto/ed25519"
	"encoding/base64"
	"errors"
	"time"

	"github.com/jackc/pgx/v5"
)

// ProvisionProcess mirrors deployment-provisioned identity. It is a repository
// composition seam, not a new remotely accessible enrollment operation.
func (s *Store) ProvisionProcess(ctx context.Context, p Actor, principal, role, incarnation, producer, keyID, source string, key []byte) error {
	if p.ID == "" || p.Incarnation == "" || p.Role != "CONTROL_REGISTRAR" || source == "" || principal == "" || incarnation == "" {
		return fail("FORBIDDEN")
	}
	var owns bool
	e := s.DB.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM resource_owners WHERE kind='room' AND resource_id=$1 AND tenant_id=$2 AND user_id=$3)`, p.Room, p.Tenant, p.Owner).Scan(&owns)
	if e != nil {
		return e
	}
	if !owns {
		return fail("FORBIDDEN")
	}
	_, e = s.DB.Exec(ctx, `INSERT INTO dl05_v2_processes(principal_id,tenant_id,owner_id,room_id,role,incarnation,producer,key_id,public_key,source_identity) VALUES($1,$2,$3,$4,$5,$6,NULLIF($7,''),NULLIF($8,''),$9,$10)`, principal, p.Tenant, p.Owner, p.Room, role, incarnation, producer, keyID, key, source)
	return normalize(e)
}

// RecordInstallation is invoked only after the trusted physical adapter observes
// installation. The source callback cannot receive or retain a SQL transaction.
func (s *Store) RecordInstallation(ctx context.Context, p Actor, binding Document) error {
	if p.Role != "CONTROL_REGISTRAR" || s.InstallationSource == nil || s.Validate == nil {
		return fail("FORBIDDEN")
	}
	if e := s.Validate("ReceiverBootstrapBinding", binding); e != nil {
		return e
	}
	observed, e := s.InstallationSource(ctx, p, clone(binding))
	if e != nil {
		return e
	}
	if hash(obj(observed, "binding")) != hash(binding) || text(observed, "state") != "CLOSED_INSTALLED" || number(observed, "installationRevision") < 1 || text(observed, "closedFenceProofRef") == "" || text(observed, "observedByPrincipalId") != p.ID {
		return fail("OUTPUT_FENCE_UNPROVEN")
	}
	c, e := s.resolve(ctx, Document{"binding": binding})
	if e != nil {
		return e
	}
	if e = validateScope(p, c); e != nil {
		return e
	}
	tx, e := s.begin(ctx)
	if e != nil {
		return e
	}
	defer tx.Rollback(ctx)
	st, e := s.lock(ctx, tx, p, c, false)
	if e != nil {
		return e
	}
	for _, k := range []string{"tenantId", "ownerId", "runId", "commandId", "attemptId", "sessionId", "runEpoch", "turnId", "utteranceId"} {
		if binding[k] != c[k] {
			return fail("COMMAND_CONFLICT")
		}
	}
	if text(binding, "producerIncarnation") != st.producer {
		return fail("FORBIDDEN")
	}
	if text(binding, "roomId") != p.Room {
		return fail("FORBIDDEN")
	}
	var good bool
	e = tx.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM dl05_v2_processes r CROSS JOIN dl05_v2_processes g JOIN dl05_room_outputs o ON o.room_id=$4 WHERE r.principal_id=$1 AND r.incarnation=$2 AND r.role='REGISTERED_RUNTIME' AND r.producer=$3 AND r.revoked_at IS NULL AND r.tenant_id=$5 AND r.owner_id=$6 AND r.room_id=$4 AND g.principal_id=$7 AND g.incarnation=$8 AND g.role='OUTPUT_GUARDIAN' AND g.revoked_at IS NULL AND g.tenant_id=$5 AND g.owner_id=$6 AND g.room_id=$4 AND o.output_binding_version=$9 AND o.guardian_id=$10 AND o.active_run_id=$11 AND o.expires_at>clock_timestamp())`, binding["runtimePrincipalId"], binding["runtimeIncarnation"], st.producer, p.Room, p.Tenant, p.Owner, observed["guardianPrincipalId"], binding["guardianIncarnation"], number(binding, "outputBindingVersion"), binding["guardianId"], c["runId"]).Scan(&good)
	if e != nil {
		return e
	}
	if !good {
		return fail("FORBIDDEN")
	}
	var savedHash, savedFence, savedGuardian, savedObserver string
	var savedRevision int64
	var retired bool
	e = tx.QueryRow(ctx, "SELECT binding_hash,fence_ref,guardian_principal,observed_by,installation_revision,retired_at IS NOT NULL FROM dl05_v2_installations WHERE proof_id=$1 AND command_id=$2", binding["physicalInstallProofRef"], c["commandId"]).Scan(&savedHash, &savedFence, &savedGuardian, &savedObserver, &savedRevision, &retired)
	if e == nil {
		if retired || savedHash != hash(binding) || savedFence != text(observed, "closedFenceProofRef") || savedGuardian != text(observed, "guardianPrincipalId") || savedObserver != p.ID || savedRevision != number(observed, "installationRevision") {
			return fail("EVIDENCE_CONFLICT")
		}
		return tx.Commit(ctx)
	}
	if !errors.Is(e, pgx.ErrNoRows) {
		return e
	}
	_, e = tx.Exec(ctx, `INSERT INTO dl05_v2_installations(proof_id,command_id,binding,binding_hash,installation_revision,runtime_principal,guardian_principal,observed_by,fence_ref) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9)`, binding["physicalInstallProofRef"], c["commandId"], binding, hash(binding), number(observed, "installationRevision"), binding["runtimePrincipalId"], observed["guardianPrincipalId"], p.ID, observed["closedFenceProofRef"])
	if e != nil {
		return normalize(e)
	}
	_ = st
	return tx.Commit(ctx)
}
func (s *Store) IssueStageChallenge(ctx context.Context, p Actor, binding Document) (Document, error) {
	if p.Role != "CONTROL_REGISTRAR" {
		return nil, fail("FORBIDDEN")
	}
	c, e := s.resolve(ctx, Document{"binding": binding})
	if e != nil {
		return nil, e
	}
	if e = validateScope(p, c); e != nil {
		return nil, e
	}
	tx, e := s.begin(ctx)
	if e != nil {
		return nil, e
	}
	defer tx.Rollback(ctx)
	st, e := s.lock(ctx, tx, p, c, false)
	if e != nil {
		return nil, e
	}
	var current bool
	var rev, lease int64
	e = tx.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM dl05_v2_installations WHERE command_id=$1 AND proof_id=$2 AND binding_hash=$3 AND retired_at IS NULL)`, c["commandId"], binding["physicalInstallProofRef"], hash(binding)).Scan(&current)
	if e != nil {
		return nil, e
	}
	if !current {
		return nil, fail("BOOTSTRAP_REQUIRED")
	}
	e = tx.QueryRow(ctx, `SELECT r.state_revision,l.lease_version FROM dl05_runs r JOIN dl05_run_leases l USING(run_id) WHERE r.run_id=$1`, c["runId"]).Scan(&rev, &lease)
	if e != nil {
		return nil, e
	}
	challenge := id("challenge")
	until := st.now.Add(time.Second)
	_, e = tx.Exec(ctx, `INSERT INTO dl05_v2_stage_challenges VALUES($1,$2,$3,$4,$5,$6,$7,$8)`, challenge, c["commandId"], binding["physicalInstallProofRef"], hash(binding), rev, lease, st.now, until)
	if e != nil {
		return nil, e
	}
	if e = tx.Commit(ctx); e != nil {
		return nil, e
	}
	return Document{"challenge": challenge, "challengeIssuedAt": stamp(st.now), "challengeExpiresAt": stamp(until)}, nil
}
func (s *Store) register(ctx context.Context, tx pgx.Tx, p Actor, st *state, q Document) (Document, error) {
	b, receipt := obj(q, "binding"), obj(q, "receipt")
	if hash(b) != text(receipt, "bindingHash") || text(b, "commandId") != text(st.c, "commandId") || text(b, "roomId") != p.Room {
		return nil, fail("ANSWER_CONFLICT")
	}
	var challengeHash string
	var issued, until time.Time
	var runRev, leaseVer int64
	e := tx.QueryRow(ctx, `SELECT binding_hash,issued_at,expires_at,run_revision,lease_version FROM dl05_v2_stage_challenges WHERE challenge=$1 AND command_id=$2 AND proof_id=$3`, receipt["challenge"], st.c["commandId"], b["physicalInstallProofRef"]).Scan(&challengeHash, &issued, &until, &runRev, &leaseVer)
	if e != nil {
		return nil, e
	}
	if e = tx.QueryRow(ctx, "SELECT clock_timestamp()").Scan(&st.now); e != nil {
		return nil, e
	}
	st.limit = minTime(st.limit, until)
	if challengeHash != hash(b) || !issued.Equal(date(receipt, "authorityIssuedAt")) || !until.Equal(date(receipt, "validUntil")) || !until.After(st.now) {
		return nil, fail("BINDING_EXPIRED")
	}
	var currentRun, currentLease int64
	if e = tx.QueryRow(ctx, `SELECT r.state_revision,l.lease_version FROM dl05_runs r JOIN dl05_run_leases l USING(run_id) WHERE r.run_id=$1`, st.c["runId"]).Scan(&currentRun, &currentLease); e != nil {
		return nil, e
	}
	if number(q, "expectedRunRevision") != currentRun || number(q, "expectedLeaseVersion") != currentLease || runRev != currentRun || leaseVer != currentLease || number(q, "expectedRegistrationRevision") != 0 {
		return nil, fail("STATE_CONFLICT")
	}
	var key []byte
	var installed Document
	installed, e = row(tx.QueryRow(ctx, `SELECT binding FROM dl05_v2_installations WHERE proof_id=$1 AND command_id=$2 AND retired_at IS NULL AND binding_hash=$3 AND installation_revision=$4`, b["physicalInstallProofRef"], st.c["commandId"], hash(b), number(receipt, "installationRevision")))
	if e != nil {
		return nil, e
	}
	if hash(installed) != hash(b) {
		return nil, fail("ANSWER_CONFLICT")
	}
	e = tx.QueryRow(ctx, `SELECT public_key FROM dl05_v2_processes WHERE principal_id=$1 AND key_id=$2 AND incarnation=$3 AND role='OUTPUT_GUARDIAN' AND tenant_id=$4 AND owner_id=$5 AND room_id=$6 AND revoked_at IS NULL FOR SHARE`, receipt["guardianPrincipalId"], receipt["keyId"], b["guardianIncarnation"], p.Tenant, p.Owner, p.Room).Scan(&key)
	if e != nil {
		return nil, fail("FORBIDDEN")
	}
	signature, e := base64.StdEncoding.DecodeString(text(receipt, "signature"))
	if e != nil || len(key) != 32 || !ed25519.Verify(ed25519.PublicKey(key), canon(without(receipt, "signature")), signature) {
		return nil, fail("FORBIDDEN")
	}
	if text(receipt, "guardianIncarnation") != text(b, "guardianIncarnation") {
		return nil, fail("FORBIDDEN")
	}
	check := *st
	check.b = b
	check.registration = Document{"state": "ACTIVE"}
	if e = check.registered(ctx, tx, p); e != nil {
		return nil, e
	}
	st.limit = minTime(st.limit, check.limit)
	if st.registration != nil {
		if text(st.registration, "registrationHash") != hash(b) || text(st.registration, "stageReceiptId") != text(receipt, "stageReceiptId") || text(st.registration, "state") != "ACTIVE" {
			return nil, fail("STATE_CONFLICT")
		}
		return Document{"requestId": q["requestId"], "registration": st.registration}, nil
	}
	_, e = tx.Exec(ctx, `INSERT INTO dl05_receiver_bootstraps(bootstrap_id,command_id,proof_id,registration_hash,binding,receipt) VALUES($1,$2,$3,$4,$5,$6)`, b["bootstrapId"], st.c["commandId"], b["physicalInstallProofRef"], hash(b), b, receipt)
	if e != nil {
		return nil, e
	}
	_, e = tx.Exec(ctx, `INSERT INTO dl05_v2_registration_state(bootstrap_id,state) VALUES($1,'ACTIVE')`, b["bootstrapId"])
	if e != nil {
		return nil, e
	}
	registration := Document{"binding": b, "registrationHash": hash(b), "revision": int64(1), "state": "ACTIVE", "registeredAt": stamp(st.now), "stageReceiptId": receipt["stageReceiptId"]}
	// Use exactly the committed timestamp in immutable wire readback.
	if e = tx.QueryRow(ctx, "SELECT registered_at FROM dl05_receiver_bootstraps WHERE bootstrap_id=$1", b["bootstrapId"]).Scan(&st.now); e != nil {
		return nil, e
	}
	registration["registeredAt"] = stamp(st.now)
	return Document{"requestId": q["requestId"], "registration": registration}, nil
}
func (s *Store) accept(ctx context.Context, tx pgx.Tx, p Actor, st *state, q Document) (Document, error) {
	c := obj(q, "command")
	if hash(c) != hash(st.c) || hash(without(c, "requestHash")) != text(c, "requestHash") || digest([]byte(text(obj(c, "payload"), "text"))) != text(obj(c, "payload"), "textHash") {
		return nil, fail("COMMAND_CONFLICT")
	}
	if p.Producer != text(q, "producerIncarnation") || p.Producer != st.producer {
		return nil, fail("FORBIDDEN")
	}
	if st.inbox == "" {
		var sent bool
		e := tx.QueryRow(ctx, `SELECT send_started_at IS NOT NULL FROM dl05_outbox WHERE command_id=$1`, c["commandId"]).Scan(&sent)
		if e != nil {
			return nil, e
		}
		if !sent {
			return nil, fail("STATE_CONFLICT")
		}
		_, e = tx.Exec(ctx, `INSERT INTO dl05_runtime_inbox(tenant_id,owner_id,run_id,attempt_id,run_epoch,command_id,request_hash,status,receipt_id,producer_incarnation) VALUES($1,$2,$3,$4,$5,$6,$7,'ACCEPTED',$8,$9)`, p.Tenant, p.Owner, c["runId"], c["attemptId"], number(c, "runEpoch"), c["commandId"], c["requestHash"], id("receipt"), p.Producer)
		if e != nil {
			return nil, e
		}
		st.inbox = "ACCEPTED"
		st.inboxRev = 1
	}
	_, e := tx.Exec(ctx, `INSERT INTO dl05_v2_commands(command_id,tenant_id,owner_id,run_id,attempt_id,session_id,room_id,run_epoch,producer,request_hash,contract_revision,command) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,'durable-live-2',$11) ON CONFLICT(command_id) DO NOTHING`, c["commandId"], p.Tenant, p.Owner, c["runId"], c["attemptId"], c["sessionId"], p.Room, number(c, "runEpoch"), p.Producer, c["requestHash"], c)
	if e != nil {
		return nil, e
	}
	var receipt, producer string
	e = tx.QueryRow(ctx, "SELECT receipt_id,producer_incarnation FROM dl05_runtime_inbox WHERE command_id=$1", c["commandId"]).Scan(&receipt, &producer)
	if e != nil {
		return nil, e
	}
	if producer != p.Producer {
		return nil, fail("FORBIDDEN")
	}
	return Document{"accepted": true, "commandId": c["commandId"], "receiptId": receipt, "requestHash": c["requestHash"], "revision": st.inboxRev, "state": st.inbox}, nil
}
func (s *Store) revoke(ctx context.Context, tx pgx.Tx, p Actor, st *state, q Document) (Document, error) {
	if st.b == nil || q["bootstrapId"] != st.b["bootstrapId"] {
		return nil, fail("BOOTSTRAP_REQUIRED")
	}
	if number(q, "expectedRegistrationRevision") != number(st.registration, "revision") {
		return nil, fail("STATE_CONFLICT")
	}
	if text(st.registration, "state") != "ACTIVE" {
		return nil, fail("REGISTRATION_REVOKED")
	}
	if e := invalidate(ctx, tx, st, text(q, "reason")); e != nil {
		return nil, e
	}
	out := clone(st.registration)
	out["state"] = "REVOKED"
	out["revision"] = number(out, "revision") + 1
	return Document{"requestId": q["requestId"], "registration": out}, nil
}
func invalidate(ctx context.Context, tx pgx.Tx, st *state, reason string) error {
	if _, e := tx.Exec(ctx, "INSERT INTO dl05_v2_audit(command_id,reason,evidence_ref) VALUES($1,$2,$3) ON CONFLICT DO NOTHING", st.c["commandId"], reason, "registration:"+text(st.b, "bootstrapId")); e != nil {
		return e
	}
	_, e := tx.Exec(ctx, `UPDATE dl05_v2_registration_state SET state='REVOKED',revision=revision+1,reason=$2,revoked_at=clock_timestamp() WHERE bootstrap_id=$1 AND state='ACTIVE'`, st.b["bootstrapId"], reason)
	if e != nil {
		return e
	}
	_, e = tx.Exec(ctx, `UPDATE dl05_v2_grant_state s SET state='REVOKED' FROM dl05_answer_grants g WHERE s.grant_id=g.grant_id AND g.command_id=$1 AND s.state='ISSUED'`, st.c["commandId"])
	if e != nil {
		return e
	}
	_, e = tx.Exec(ctx, `UPDATE dl05_v2_execution_state SET state='UNKNOWN' WHERE command_id=$1 AND state='ACTIVE'`, st.c["commandId"])
	return e
}

// ReadRegistration is a CONTROL repository readback after a registration ACK
// loss. It is not a new wire operation or execution grant. It remains available
// after proof expiry/Stop, returning immutable identity plus revocation knowledge.
func (s *Store) ReadRegistration(ctx context.Context, p Actor, bootstrapID string) (Document, error) {
	if p.Role != "CONTROL_REGISTRAR" {
		return nil, fail("FORBIDDEN")
	}
	c, e := s.resolve(ctx, Document{"bootstrapId": bootstrapID})
	if e != nil {
		return nil, normalize(e)
	}
	if e = validateScope(p, c); e != nil {
		return nil, e
	}
	tx, e := s.begin(ctx)
	if e != nil {
		return nil, e
	}
	defer tx.Rollback(ctx)
	st, e := s.lock(ctx, tx, p, c, true)
	if e != nil {
		return nil, normalize(e)
	}
	if st.b == nil || st.b["bootstrapId"] != bootstrapID {
		return nil, fail("RESOURCE_NOT_FOUND")
	}
	out := clone(st.registration)
	if s.Validate == nil {
		return nil, fail("DEPENDENCY_UNAVAILABLE")
	}
	if e = s.Validate("ReceiverRegistration", out); e != nil {
		return nil, e
	}
	return out, tx.Commit(ctx)
}
